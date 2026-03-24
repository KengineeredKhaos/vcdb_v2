# app/slices/sponsors/services_crm.py

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.extensions import db, event_bus
from app.extensions.contracts import calendar_v2
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps

from . import taxonomy_crm as tax
from .mapper import (
    SponsorCRMEditorView,
    SponsorOpportunityMatchView,
    SponsorPostureView,
    SponsorProfileNoteHintsView,
    map_sponsor_crm_editor,
    map_sponsor_posture,
    map_sponsor_profile_note_hints,
)
from .models import (
    FundingProspect,
    Sponsor,
    SponsorCRMFactorIndex,
    SponsorFundingIntent,
    SponsorHistory,
)
from .services import (
    CAPS_SECTION,
    RESTR_SECTION,
    _ensure_reqid,
    _latest_snapshot,
    _next_version,
    get_profile_hints,
)

CRM_SECTION = "sponsor:crm_factors:v1"

_ALLOWED_KEYS = frozenset(tax.all_crm_factor_keys())
_ALLOWED_STRENGTHS = frozenset(tax.all_crm_strengths())
_ALLOWED_SOURCES = frozenset(tax.all_crm_sources())


def allowed_crm_factor_keys() -> list[str]:
    return tax.all_crm_factor_keys()


def allowed_crm_strengths() -> list[str]:
    return tax.all_crm_strengths()


def allowed_crm_sources() -> list[str]:
    return tax.all_crm_sources()


def _latest_crm_snapshot(
    sponsor_entity_ulid: str,
) -> dict[str, dict[str, Any]]:
    data = _latest_snapshot(sponsor_entity_ulid, CRM_SECTION)
    return data if isinstance(data, dict) else {}


def _normalize_crm_payload(
    payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    norm: dict[str, dict[str, Any]] = {}
    if not payload:
        return norm

    for raw_key, raw_val in payload.items():
        key = str(raw_key or "").strip()
        if not key:
            continue

        if isinstance(raw_val, bool):
            norm[key] = {
                "has": bool(raw_val),
                "strength": "observed",
                "source": "operator",
            }
            continue

        if not isinstance(raw_val, dict):
            raise ValueError("invalid crm factor payload value")

        item: dict[str, Any] = {}
        item["has"] = bool(raw_val.get("has", True))

        strength = str(raw_val.get("strength") or "observed").strip()
        source = str(raw_val.get("source") or "operator").strip()

        item["strength"] = strength
        item["source"] = source

        note_raw = raw_val.get("note")
        if note_raw is not None:
            note = str(note_raw).strip()
            if note:
                item["note"] = note[:300]

        norm[key] = item

    return norm


def _validate_crm_payload(
    payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    norm = _normalize_crm_payload(payload)
    if not norm:
        return norm

    unknown = sorted(k for k in norm if k not in _ALLOWED_KEYS)
    if unknown:
        raise ValueError(f"invalid crm factor keys: {', '.join(unknown)}")

    bad_strength = sorted(
        k
        for k, v in norm.items()
        if str(v.get("strength") or "") not in _ALLOWED_STRENGTHS
    )
    if bad_strength:
        raise ValueError(
            "invalid crm factor strength for keys: " + ", ".join(bad_strength)
        )

    bad_source = sorted(
        k
        for k, v in norm.items()
        if str(v.get("source") or "") not in _ALLOWED_SOURCES
    )
    if bad_source:
        raise ValueError(
            "invalid crm factor source for keys: " + ", ".join(bad_source)
        )

    return norm


def _rebuild_crm_index(
    *,
    sponsor_entity_ulid: str,
    snapshot: dict[str, dict[str, Any]],
    now: str,
) -> None:
    existing = {
        row.key: row
        for row in db.session.query(SponsorCRMFactorIndex).filter_by(
            sponsor_entity_ulid=sponsor_entity_ulid
        )
    }

    seen: set[str] = set()

    for key, item in snapshot.items():
        seen.add(key)
        bucket = tax.bucket_for_factor(key)
        if not bucket:
            raise ValueError(f"unknown crm factor bucket for key: {key}")

        active = bool(item.get("has"))
        strength = str(item.get("strength") or "observed")
        source = str(item.get("source") or "operator")

        row = existing.get(key)
        if row:
            row.bucket = bucket
            row.active = active
            row.strength = strength
            row.source = source
            row.updated_at_utc = now
        else:
            db.session.add(
                SponsorCRMFactorIndex(
                    sponsor_entity_ulid=sponsor_entity_ulid,
                    bucket=bucket,
                    key=key,
                    active=active,
                    strength=strength,
                    source=source,
                    updated_at_utc=now,
                )
            )

    for key, row in existing.items():
        if key not in seen:
            db.session.delete(row)


def get_crm_factors(sponsor_entity_ulid: str) -> dict[str, Any]:
    return _latest_crm_snapshot(sponsor_entity_ulid)


def set_crm_factors(
    *,
    sponsor_entity_ulid: str,
    payload: dict[str, Any],
    request_id: str,
    actor_ulid: str | None,
) -> str | None:
    _ensure_reqid(request_id)
    now = now_iso8601_ms()

    sponsor = db.session.get(Sponsor, sponsor_entity_ulid)
    if not sponsor:
        raise ValueError("sponsor not found")

    norm = _validate_crm_payload(payload)
    last = _latest_crm_snapshot(sponsor_entity_ulid)

    if stable_dumps(last) == stable_dumps(norm):
        sponsor.last_touch_utc = now
        db.session.flush()
        return None

    ver = _next_version(sponsor_entity_ulid, CRM_SECTION)
    hist = SponsorHistory(
        sponsor_entity_ulid=sponsor_entity_ulid,
        section=CRM_SECTION,
        version=ver,
        data_json=stable_dumps(norm),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    _rebuild_crm_index(
        sponsor_entity_ulid=sponsor_entity_ulid,
        snapshot=norm,
        now=now,
    )

    sponsor.last_touch_utc = now
    db.session.flush()

    event_bus.emit(
        domain="sponsors",
        operation="crm_factors_update",
        actor_ulid=actor_ulid,
        target_ulid=sponsor_entity_ulid,
        request_id=request_id,
        happened_at_utc=now,
        refs={"version_ptr": hist.ulid},
        changed={"fields": ["crm_factors"]},
    )
    return hist.ulid


def patch_crm_factors(
    *,
    sponsor_entity_ulid: str,
    payload: dict[str, Any],
    request_id: str,
    actor_ulid: str | None,
) -> str | None:
    _ensure_reqid(request_id)

    sponsor = db.session.get(Sponsor, sponsor_entity_ulid)
    if not sponsor:
        raise ValueError("sponsor not found")

    if not isinstance(payload, dict):
        raise ValueError("invalid crm factor patch payload")

    current = _latest_crm_snapshot(sponsor_entity_ulid)
    merged: dict[str, dict[str, Any]] = {
        str(k): dict(v)
        for k, v in current.items()
        if isinstance(k, str) and isinstance(v, dict)
    }

    for raw_key, raw_val in payload.items():
        key = str(raw_key or "").strip()
        if not key:
            continue

        if key not in _ALLOWED_KEYS:
            raise ValueError(f"invalid crm factor keys: {key}")

        if raw_val is None:
            merged.pop(key, None)
            continue

        one = _validate_crm_payload({key: raw_val})
        if key in one:
            merged[key] = one[key]

    return set_crm_factors(
        sponsor_entity_ulid=sponsor_entity_ulid,
        payload=merged,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def get_sponsor_profile_note_hints(
    sponsor_entity_ulid: str,
) -> SponsorProfileNoteHintsView:
    sponsor = db.session.get(Sponsor, sponsor_entity_ulid)
    if not sponsor:
        raise ValueError("sponsor not found")

    snapshot = get_profile_hints(sponsor_entity_ulid) or {}
    return map_sponsor_profile_note_hints(
        sponsor_entity_ulid=sponsor_entity_ulid,
        snapshot=snapshot,
    )


def _crm_factor_payload(
    *,
    strength: str = "observed",
    note: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "has": True,
        "strength": strength,
        "source": "inferred",
    }
    if note:
        text = str(note).strip()
        if text:
            item["note"] = text[:300]
    return item


def derive_crm_factors_from_history(
    sponsor_entity_ulid: str,
) -> dict[str, dict[str, Any]]:
    sponsor = db.session.get(Sponsor, sponsor_entity_ulid)
    if not sponsor:
        raise ValueError("sponsor not found")

    out: dict[str, dict[str, Any]] = {}

    caps = _latest_snapshot(sponsor_entity_ulid, CAPS_SECTION)
    restr = _latest_snapshot(sponsor_entity_ulid, RESTR_SECTION)

    # -----------------
    # Capability-backed
    # -----------------
    if bool(caps.get("funding.cash_grant", {}).get("has")):
        out["style_cash_grant"] = _crm_factor_payload()

    if bool(caps.get("funding.restricted_grant", {}).get("has")):
        out["restriction_purpose_bound"] = _crm_factor_payload()

    if bool(caps.get("in_kind.in_kind_goods", {}).get("has")):
        out["style_in_kind_goods"] = _crm_factor_payload()

    if bool(caps.get("in_kind.in_kind_services", {}).get("has")):
        out["style_service_support"] = _crm_factor_payload()

    # -----------------
    # Restriction-backed
    # -----------------
    if bool(restr.get("restrictions.unrestricted", {}).get("has")):
        out["restriction_flexible"] = _crm_factor_payload()

    if bool(restr.get("restrictions.local", {}).get("has")):
        out["restriction_geo_local_only"] = _crm_factor_payload()

    if bool(restr.get("restrictions.veteran", {}).get("has")):
        out["restriction_population_veterans_only"] = _crm_factor_payload()

    # -----------------
    # Relationship-backed
    # -----------------
    intents = (
        db.session.query(SponsorFundingIntent)
        .filter_by(sponsor_entity_ulid=sponsor_entity_ulid)
        .all()
    )

    fulfilled = sum(1 for row in intents if row.status == "fulfilled")
    committedish = sum(
        1 for row in intents if row.status in {"committed", "fulfilled"}
    )
    withdrawn = sum(1 for row in intents if row.status == "withdrawn")

    if fulfilled >= 1:
        out["relationship_prior_success"] = _crm_factor_payload()

    if committedish >= 2 or fulfilled >= 2:
        out["relationship_repeat_supporter"] = _crm_factor_payload(
            strength="recurring"
        )

    if fulfilled >= 2 and withdrawn == 0:
        out["relationship_follow_through_strong"] = _crm_factor_payload(
            strength="strong_pattern"
        )
    elif fulfilled >= 1 and withdrawn >= 1:
        out["relationship_follow_through_mixed"] = _crm_factor_payload(
            strength="observed"
        )

    active_prospects = (
        db.session.query(FundingProspect)
        .filter(
            FundingProspect.sponsor_entity_ulid == sponsor_entity_ulid,
            FundingProspect.status.in_(("prospect", "approach", "active")),
        )
        .count()
    )

    if active_prospects >= 1 and committedish == 0 and fulfilled == 0:
        out["relationship_new_prospect"] = _crm_factor_payload()

    return out


def sync_derived_crm_factors(
    *,
    sponsor_entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> str | None:
    current = _latest_crm_snapshot(sponsor_entity_ulid)
    derived = derive_crm_factors_from_history(sponsor_entity_ulid)

    patch: dict[str, Any] = {}

    # Remove stale inferred factors that no longer derive.
    for key, item in current.items():
        if not isinstance(item, dict):
            continue
        if str(item.get("source") or "") != "inferred":
            continue
        if key not in derived:
            patch[key] = None

    # Add/update inferred factors, but never overwrite
    # operator/observed factors.
    for key, item in derived.items():
        cur = current.get(key)
        if not isinstance(cur, dict):
            patch[key] = item
            continue
        cur_source = str(cur.get("source") or "").strip()
        if cur_source == "inferred":
            patch[key] = item

    if not patch:
        return None

    return patch_crm_factors(
        sponsor_entity_ulid=sponsor_entity_ulid,
        payload=patch,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def get_sponsor_crm_editor(
    sponsor_entity_ulid: str,
) -> SponsorCRMEditorView:
    sponsor = db.session.get(Sponsor, sponsor_entity_ulid)
    if not sponsor:
        raise ValueError("sponsor not found")

    snapshot = _latest_crm_snapshot(sponsor_entity_ulid)
    return map_sponsor_crm_editor(
        sponsor_entity_ulid=sponsor_entity_ulid,
        snapshot=snapshot,
    )


def get_sponsor_posture(
    sponsor_entity_ulid: str,
) -> SponsorPostureView:
    sponsor = db.session.get(Sponsor, sponsor_entity_ulid)
    if not sponsor:
        raise ValueError("sponsor not found")

    snapshot = _latest_crm_snapshot(sponsor_entity_ulid)
    return map_sponsor_posture(
        sponsor_entity_ulid=sponsor_entity_ulid,
        snapshot=snapshot,
    )


_MATCH_BAND_ORDER = {
    "likely_fit": 0,
    "maybe_fit": 1,
    "caution": 2,
}


def _active_posture_keys(view: SponsorPostureView) -> set[str]:
    out: set[str] = set()
    for rows in view.factors_by_bucket.values():
        for row in rows:
            if row.active:
                out.add(row.key)
    return out


def _context_restriction_keys(context) -> set[str]:
    out = set(context.policy.default_restriction_keys or ())
    summary = getattr(context.policy, "source_profile_summary", None)
    if summary is not None:
        out |= set(summary.default_restriction_keys or ())
    return {str(k).strip() for k in out if str(k).strip()}


def _context_mission_keys(context) -> set[str]:
    out: set[str] = set()

    spending_class = str(context.planning.spending_class or "").strip()
    if spending_class == "basic_needs":
        out.add("mission_basic_needs")
    elif spending_class == "events":
        out.add("mission_events_outreach")
    elif spending_class == "admin":
        out.add("mission_general_ops")

    tags = {
        str(tag).strip().lower()
        for tag in (context.planning.tag_any or ())
        if str(tag).strip()
    }
    if any("welcome_home" in tag or "housing" in tag for tag in tags):
        out.add("mission_housing")
    if any("food" in tag or "grocery" in tag for tag in tags):
        out.add("mission_food_support")

    profile_key = str(context.planning.source_profile_key or "").strip()
    restrictions = _context_restriction_keys(context)

    if "local_veterans" in profile_key or (
        "local_only" in restrictions and "vet_only" in restrictions
    ):
        out.add("mission_local_veterans")

    return out


def _fit_band(
    *,
    positives: list[str],
    cautions: list[str],
) -> str:
    pos = len(positives)
    cau = len(cautions)

    if pos >= 3 and cau == 0:
        return "likely_fit"
    if cau >= 2 or pos == 0:
        return "caution"
    return "maybe_fit"


def _suggested_next_action(
    *,
    fit_band: str,
    manual_review_recommended: bool,
    active_keys: set[str],
) -> str:
    has_docs_signal = bool(
        {
            "restriction_docs_required",
            "restriction_receipts_required",
            "friction_docs_heavy",
            "friction_receipt_packet_sensitive",
        }
        & active_keys
    )

    if fit_band == "likely_fit":
        if manual_review_recommended:
            return "manual_review"
        if has_docs_signal:
            return "proceed_with_docs"
        return "proceed_outreach"

    if fit_band == "maybe_fit":
        if manual_review_recommended:
            return "manual_review"
        if has_docs_signal:
            return "proceed_with_docs"
        return "hold_for_more_info"

    return (
        "manual_review" if manual_review_recommended else "hold_for_more_info"
    )


def compute_opportunity_match(
    *,
    sponsor_entity_ulid: str,
    funding_demand_ulid: str,
) -> SponsorOpportunityMatchView:
    sponsor = db.session.get(Sponsor, sponsor_entity_ulid)
    if not sponsor:
        raise ValueError("sponsor not found")

    context = calendar_v2.get_funding_demand_context(funding_demand_ulid)
    posture = get_sponsor_posture(sponsor_entity_ulid)
    note_hints = get_sponsor_profile_note_hints(sponsor_entity_ulid)

    active_keys = _active_posture_keys(posture)
    desired_missions = _context_mission_keys(context)
    restriction_keys = _context_restriction_keys(context)

    positives: list[str] = []
    cautions: list[str] = []

    matched_missions = desired_missions & active_keys
    if matched_missions:
        labels = []
        for key in sorted(matched_missions):
            spec = tax.factor_spec(key)
            if spec:
                labels.append(spec.label.lower())
        if labels:
            positives.append("Mission alignment: " + ", ".join(labels) + ".")

    if "relationship_repeat_supporter" in active_keys:
        positives.append("Repeat support history exists.")
    elif "relationship_prior_success" in active_keys:
        positives.append("Prior successful support exists.")

    if bool(context.workflow.reimbursement_expected):
        if (
            "style_reimbursement" in active_keys
            or "restriction_reimbursement_preferred" in active_keys
        ):
            positives.append(
                "Support style aligns with reimbursement workflow."
            )
        if "restriction_advance_funding_rare" in active_keys:
            cautions.append("Sponsor rarely prefers advance funding.")
    else:
        if (
            "style_cash_grant" in active_keys
            or "style_one_time_support" in active_keys
            or "style_recurring_support" in active_keys
        ):
            positives.append("Support style aligns with direct funding.")

    if "project_bound" in restriction_keys:
        if "restriction_purpose_bound" in active_keys:
            positives.append(
                "Restriction posture aligns with project-bound scope."
            )

    if "local_only" in restriction_keys:
        if "restriction_geo_local_only" in active_keys:
            positives.append(
                "Restriction posture aligns with local-only scope."
            )
    elif "restriction_geo_local_only" in active_keys:
        cautions.append("Sponsor often expects local-only scope.")

    if "vet_only" in restriction_keys:
        if "restriction_population_veterans_only" in active_keys:
            positives.append(
                "Restriction posture aligns with veteran-only scope."
            )
    elif "restriction_population_veterans_only" in active_keys:
        cautions.append("Sponsor often expects veteran-only scope.")

    if "restriction_flexible" in active_keys and not restriction_keys:
        positives.append(
            "Flexible restriction posture may fit this opportunity."
        )

    if (
        "restriction_docs_required" in active_keys
        or "friction_docs_heavy" in active_keys
    ):
        cautions.append(
            "Documentation expectations may require extra preparation."
        )

    if bool(context.workflow.reimbursement_expected) and (
        "restriction_receipts_required" in active_keys
        or "friction_receipt_packet_sensitive" in active_keys
    ):
        cautions.append("Receipt packet discipline is likely needed.")

    if "friction_board_review" in active_keys:
        cautions.append("Board review commonly required.")

    if "friction_manual_review_common" in active_keys:
        cautions.append("This sponsor often merits manual review.")

    if "relationship_prior_decline" in active_keys:
        cautions.append("Prior decline history exists.")

    if "relationship_follow_through_mixed" in active_keys:
        cautions.append("Follow-through history is mixed.")

    manual_review_recommended = bool(
        {
            "friction_board_review",
            "friction_manual_review_common",
            "relationship_prior_decline",
            "relationship_follow_through_mixed",
        }
        & active_keys
    )

    fit_band = _fit_band(
        positives=positives,
        cautions=cautions,
    )

    return SponsorOpportunityMatchView(
        sponsor_entity_ulid=sponsor_entity_ulid,
        funding_demand_ulid=funding_demand_ulid,
        fit_band=fit_band,
        positive_reasons=tuple(positives),
        caution_reasons=tuple(cautions),
        manual_review_recommended=manual_review_recommended,
        suggested_next_action=_suggested_next_action(
            fit_band=fit_band,
            manual_review_recommended=manual_review_recommended,
            active_keys=active_keys,
        ),
        profile_note_hints=note_hints.hints,
    )


def list_opportunity_matches(
    funding_demand_ulid: str,
) -> list[SponsorOpportunityMatchView]:
    rows = db.session.execute(
        select(Sponsor).order_by(Sponsor.entity_ulid.asc())
    ).scalars()

    out = [
        compute_opportunity_match(
            sponsor_entity_ulid=row.entity_ulid,
            funding_demand_ulid=funding_demand_ulid,
        )
        for row in rows
    ]

    out.sort(
        key=lambda row: (
            _MATCH_BAND_ORDER[row.fit_band],
            row.manual_review_recommended,
            -len(row.positive_reasons),
            len(row.caution_reasons),
            row.sponsor_entity_ulid,
        )
    )
    return out
