# app/slices/sponsors/services.py
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import desc, func

from app.extensions import db, event_bus
from app.extensions.contracts import entity_v2
from app.extensions.errors import ContractError
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps

from . import services_poc as poc
from . import taxonomy as tax
from .mapper import (
    SponsorPOCView,
    SponsorView,
    map_sponsor_poc_list,
    map_sponsor_view,
)
from .models import (
    Sponsor,
    SponsorCapabilityIndex,
    SponsorHistory,
    SponsorPledgeIndex,
    SponsorPOC,
)

# -----------------
# Constants and conventions
# ------------------

CAPS_SECTION = "sponsor:capability:v1"
PLEDGE_SECTION = "sponsor:pledge:v1"
PROSPECT_REAL_SECTION = "sponsor:prospect_realization:v1"

POC_RELATION = "poc"  # table-level convention, not board policy
_SPONSOR_POC_SPEC = poc.POCSpec(
    owner_col="sponsor_entity_ulid",
    allowed_scopes=tuple(tax.POC_SCOPES),
    default_scope=str(tax.DEFAULT_POC_SCOPE),
    max_rank=int(tax.POC_MAX_RANK),
)

_ALLOWED_CAPS = frozenset(tax.all_capability_codes())
_NOTE_MAX = int(tax.SPONSOR_CAPABILITY_NOTE_MAX)

# -----------------
# Taxonomy-backed
# helpers
# -----------------


def note_max() -> int:
    return int(tax.SPONSOR_CAPABILITY_NOTE_MAX)


def allowed_capability_codes() -> list[str]:
    return tax.all_capability_codes()


def readiness_allowed() -> set[str]:
    return set(tax.SPONSOR_READINESS_CODES)


def mou_allowed() -> set[str]:
    return set(tax.SPONSOR_MOU_CODES)


def _default_readiness() -> str:
    return str(tax.SPONSOR_READINESS_DEFAULT).strip().lower()


def _default_mou() -> str:
    return str(tax.SPONSOR_MOU_DEFAULT).strip().lower()


# -----------------
# Contract Error
# normalization
# -----------------


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    # If we’re already looking at a ContractError, just bubble it up unchanged
    if isinstance(exc, ContractError):
        return exc

    msg = str(exc) or exc.__class__.__name__

    if isinstance(exc, ValueError):
        return ContractError(
            code="bad_argument",
            where=where,
            message=msg,
            http_status=400,
        )
    if isinstance(exc, PermissionError):
        return ContractError(
            code="permission_denied",
            where=where,
            message=msg,
            http_status=403,
        )
    if isinstance(exc, LookupError):
        return ContractError(
            code="not_found",
            where=where,
            message=msg,
            http_status=404,
        )

    # Fallback: unexpected system/runtime error
    return ContractError(
        code="internal_error",
        where=where,
        message="unexpected error in contract; see logs",
        http_status=500,
        data={"exc_type": exc.__class__.__name__},
    )


# -----------------
# Point of Contact
# wrappers
# -----------------


def sponsor_link_poc(
    *,
    sponsor_entity_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int = 0,
    is_primary: bool = False,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    entity_v2.require_person_entity_ulid(
        entity_ulid=person_entity_ulid, where="sponsors.sponsor_link_poc"
    )
    return poc.link_poc(
        session=db.session(),
        POCModel=SponsorPOC,
        spec=_SPONSOR_POC_SPEC,
        domain="sponsors",
        owner_ulid=sponsor_entity_ulid,
        person_entity_ulid=person_entity_ulid,
        scope=scope,
        rank=rank,
        is_primary=is_primary,
        window=window,
        org_role=org_role,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def sponsor_update_poc(
    *,
    sponsor_entity_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int | None = None,
    is_primary: bool | None = None,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    entity_v2.require_person_entity_ulid(
        entity_ulid=person_entity_ulid,
        where="sponsors.sponsor_update_poc",
    )
    return poc.update_poc(
        session=db.session(),
        POCModel=SponsorPOC,
        spec=_SPONSOR_POC_SPEC,
        domain="sponsors",
        owner_ulid=sponsor_entity_ulid,
        person_entity_ulid=person_entity_ulid,
        scope=scope,
        rank=rank,
        is_primary=is_primary,
        window=window,
        org_role=org_role,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def sponsor_unlink_poc(
    *,
    sponsor_entity_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    entity_v2.require_person_entity_ulid(
        entity_ulid=person_entity_ulid, where="sponsors.sponsor_unlink_poc"
    )
    return poc.unlink_poc(
        session=db.session(),
        POCModel=SponsorPOC,
        spec=_SPONSOR_POC_SPEC,
        domain="sponsors",
        owner_ulid=sponsor_entity_ulid,
        person_entity_ulid=person_entity_ulid,
        scope=scope,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def sponsor_list_pocs(*, sponsor_entity_ulid: str) -> list[SponsorPOCView]:
    rows = poc.list_pocs(
        session=db.session(),
        POCModel=SponsorPOC,
        spec=_SPONSOR_POC_SPEC,
        owner_ulid=sponsor_entity_ulid,
    )
    return map_sponsor_poc_list(rows)


# -----------------
# Wrappers & Helpers
# -----------------


def _ensure_reqid(rid: str | None) -> str:
    if not rid or not str(rid).strip():
        raise ValueError("request_id must be non-empty")
    return str(rid).strip()


def _split(flat_key: str) -> tuple[str, str]:
    """
    Split 'domain.key' into ('domain', 'key').
    """
    if "." not in flat_key:
        raise ValueError("flat capability key must be 'domain.code'")
    d, k = flat_key.split(".", 1)
    d = d.strip()
    k = k.strip()
    if not d or not k:
        raise ValueError("invalid flat capability key")
    return d, k


def _flatten_caps_payload(
    payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    Normalise capability payload into flat keys.

    Accepts two shapes:

      1) Flat:
         {
             "funding.cash_grant": true,
             "in_kind.in_kind_goods": {"has": false, "note": "..." },
         }

      2) Nested:
         {
             "funding": {
                 "cash_grant": true,
                 "restricted_grant": {"has": true, "note": "Board restricted"},
             },
             "in_kind": {
                 "in_kind_goods": {"has": false},
             },
         }

    Returns a mapping of flat keys to objects of the form:
        { "<domain>.<code>": {"has": bool, "note": str?}, ... }
    """
    flat: dict[str, dict[str, Any]] = {}

    if not payload:
        return flat

    for key, value in payload.items():
        # Shape 1: already "domain.code"
        if "." in key:
            flat_key = key
            obj = value
            items = [(flat_key, obj)]
        else:
            # Shape 2: nested by domain
            domain = key
            if not isinstance(value, dict):
                raise ValueError(
                    "nested capabilities must be objects per domain"
                )
            items = []
            for sub_key, sub_val in value.items():
                items.append((f"{domain}.{sub_key}", sub_val))

        for flat_key, obj in items:
            # Normalise to {"has": bool, "note": str?}
            if isinstance(obj, bool):
                flat[flat_key] = {"has": bool(obj)}
            elif isinstance(obj, dict):
                out: dict[str, Any] = {}
                if "has" in obj:
                    out["has"] = bool(obj["has"])
                else:
                    # default missing "has" → True
                    out["has"] = True
                note_raw = obj.get("note")
                if note_raw is not None:
                    note = str(note_raw).strip()
                    if note:
                        out["note"] = note[:_NOTE_MAX]
                flat[flat_key] = out
            else:
                raise ValueError("invalid capability payload value")

    return flat


# -----------------
# History
# -----------------


def _latest_snapshot(
    sponsor_entity_ulid: str, section: str
) -> dict[str, dict]:
    h = (
        db.session.query(SponsorHistory)
        .filter_by(sponsor_entity_ulid=sponsor_entity_ulid, section=section)
        .order_by(desc(SponsorHistory.version))
        .first()
    )
    data = json.loads(h.data_json) if h else {}
    return data if isinstance(data, dict) else {}


# -----------------
# Validate Caps
# -----------------


def _validate_caps(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    flat = _flatten_caps_payload(payload)
    if not flat:
        return flat

    unknown = sorted(k for k in flat if k not in _ALLOWED_CAPS)
    if unknown:
        raise ValueError(f"invalid capability keys: {', '.join(unknown)}")

    return flat


def _latest_caps(sponsor_entity_ulid: str) -> dict[str, dict]:
    return _latest_snapshot(sponsor_entity_ulid, CAPS_SECTION)


def _next_version(sponsor_entity_ulid: str, section: str) -> int:
    cur = (
        db.session.query(func.max(SponsorHistory.version))
        .filter_by(sponsor_entity_ulid=sponsor_entity_ulid, section=section)
        .scalar()
    )
    return int(cur or 0) + 1


# -----------------
# core: sponsor row
# -----------------


def ensure_sponsor(
    *, sponsor_entity_ulid: str, request_id: str, actor_ulid: str | None
) -> str:
    _ensure_reqid(request_id)
    # facet must be attached to an org entity
    entity_v2.require_org_entity_ulid(
        sponsor_entity_ulid, allow_archived=False
    )

    s = db.session.get(Sponsor, sponsor_entity_ulid)
    now = now_iso8601_ms()

    if not s:
        s = Sponsor(
            entity_ulid=sponsor_entity_ulid,
            first_seen_utc=now,
            last_touch_utc=now,
            readiness_status=_default_readiness(),
            mou_status=_default_mou(),
        )
        db.session.add(s)
        db.session.flush()

        event_bus.emit(
            domain="sponsors",
            operation="created_insert",
            actor_ulid=actor_ulid,
            target_ulid=s.entity_ulid,  # facet pk
            request_id=request_id,
            happened_at_utc=now,
            refs={"entity_ulid": s.entity_ulid},
        )
    else:
        s.last_touch_utc = now
        db.session.flush()

    return s.entity_ulid


# -----------------
# Capabilities:
# replace & patch
# -----------------


def upsert_capabilities(
    *,
    sponsor_entity_ulid: str,
    payload: dict[str, Any],
    request_id: str,
    actor_ulid: str | None,
) -> str | None:
    _ensure_reqid(request_id)
    now = now_iso8601_ms()
    s = db.session.get(Sponsor, sponsor_entity_ulid)
    if not s:
        raise ValueError("sponsor not found")
    norm = _validate_caps(payload)
    last = _latest_caps(sponsor_entity_ulid)
    if last and stable_dumps(last) == stable_dumps(norm):
        s.last_touch_utc = now
        db.session.flush()
        return None

    before = {k for k, v in last.items() if v.get("has")}
    after = {k for k, v in norm.items() if v.get("has")}
    added, removed = sorted(after - before), sorted(before - after)

    ver = _next_version(sponsor_entity_ulid, CAPS_SECTION)
    hist = SponsorHistory(
        sponsor_entity_ulid=sponsor_entity_ulid,
        section=CAPS_SECTION,
        version=ver,
        data_json=stable_dumps(norm),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    # rebuild projection fully
    existing = {
        (c.domain, c.key): c
        for c in db.session.query(SponsorCapabilityIndex).filter_by(
            sponsor_entity_ulid=sponsor_entity_ulid
        )
    }

    seen: set[tuple[str, str]] = set()
    for flat, obj in norm.items():
        d, k = _split(flat)
        active = bool(obj.get("has"))
        seen.add((d, k))
        row = existing.get((d, k))
        if row:
            row.active = active
            row.updated_at_utc = now
        else:
            db.session.add(
                SponsorCapabilityIndex(
                    sponsor_entity_ulid=sponsor_entity_ulid,
                    domain=d,
                    key=k,
                    active=active,
                    updated_at_utc=now,
                )
            )
    for (d, k), row in existing.items():
        if (d, k) not in seen:
            db.session.delete(row)

    s.capability_last_update_utc = now
    s.last_touch_utc = now
    s.admin_review_required = "meta.unclassified" in after
    if not s.admin_review_required and s.readiness_status == "draft":
        s.readiness_status = "review"
    db.session.flush()

    for flat in added:
        d, k = _split(flat)
        event_bus.emit(
            domain="sponsors",
            operation="capability_add",
            actor_ulid=actor_ulid,
            target_ulid=sponsor_entity_ulid,
            request_id=request_id,
            happened_at_utc=now,
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )
    for flat in removed:
        d, k = _split(flat)
        event_bus.emit(
            domain="sponsors",
            operation="capability_remove",
            actor_ulid=actor_ulid,
            target_ulid=sponsor_entity_ulid,
            request_id=request_id,
            happened_at_utc=now,
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )
    return hist.ulid


def patch_capabilities(
    *,
    sponsor_entity_ulid: str,
    payload: dict[str, Any],
    request_id: str,
    actor_ulid: str | None,
) -> str | None:
    _ensure_reqid(request_id)
    now = now_iso8601_ms()
    s = db.session.get(Sponsor, sponsor_entity_ulid)
    if not s:
        raise ValueError("sponsor not found")
    patch = _validate_caps(payload)
    last = _latest_caps(sponsor_entity_ulid)
    merged = {k: dict(v) for k, v in last.items()}
    for flat, obj in patch.items():
        if flat not in merged:
            merged[flat] = {}
        if "has" in obj:
            merged[flat]["has"] = bool(obj["has"])
        if "note" in obj:
            note = obj["note"]
            if note is None or str(note).strip() == "":
                merged[flat].pop("note", None)
            else:
                merged[flat]["note"] = str(note)[:_NOTE_MAX]
    if stable_dumps(merged) == stable_dumps(last):
        s.last_touch_utc = now
        db.session.flush()
        return None

    before = {k for k, v in last.items() if v.get("has")}
    after = {k for k, v in merged.items() if v.get("has")}
    added, removed = sorted(after - before), sorted(before - after)

    ver = _next_version(sponsor_entity_ulid, CAPS_SECTION)
    hist = SponsorHistory(
        sponsor_entity_ulid=sponsor_entity_ulid,
        section=CAPS_SECTION,
        version=ver,
        data_json=stable_dumps(merged),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    # touch only affected keys in projection (no deletions)
    for flat, obj in patch.items():
        d, k = _split(flat)
        active = bool(obj.get("has"))
        row = (
            db.session.query(SponsorCapabilityIndex)
            .filter_by(
                sponsor_entity_ulid=sponsor_entity_ulid, domain=d, key=k
            )
            .first()
        )
        if row:
            row.active = active
            row.updated_at_utc = now
        else:
            db.session.add(
                SponsorCapabilityIndex(
                    sponsor_entity_ulid=sponsor_entity_ulid,
                    domain=d,
                    key=k,
                    active=active,
                    updated_at_utc=now,
                )
            )

    s.capability_last_update_utc = now
    s.last_touch_utc = now
    s.admin_review_required = "meta.unclassified" in after
    if not s.admin_review_required and s.readiness_status == "draft":
        s.readiness_status = "review"
    db.session.flush()

    for flat in added:
        d, k = _split(flat)
        event_bus.emit(
            domain="sponsors",
            operation="capability_add",
            actor_ulid=actor_ulid,
            target_ulid=sponsor_entity_ulid,
            request_id=request_id,
            happened_at_utc=now,
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )
    for flat in removed:
        d, k = _split(flat)
        event_bus.emit(
            domain="sponsors",
            operation="capability_remove",
            actor_ulid=actor_ulid,
            target_ulid=sponsor_entity_ulid,
            request_id=request_id,
            happened_at_utc=now,
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )
    return hist.ulid


# -----------------
# Readiness/MOU
# helpers
# -----------------


def set_readiness_status(
    *,
    sponsor_entity_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: str | None,
) -> None:
    _ensure_reqid(request_id)
    now = now_iso8601_ms()
    s = db.session.get(Sponsor, sponsor_entity_ulid)
    if not s:
        raise ValueError("sponsor not found")

    status = (status or "").strip().lower()
    if status not in readiness_allowed():
        raise ValueError("invalid readiness_status")

    if s.readiness_status == status:
        return

    s.readiness_status = status
    s.last_touch_utc = now
    db.session.flush()

    event_bus.emit(
        domain="sponsors",
        operation="readiness_update",
        actor_ulid=actor_ulid,
        target_ulid=sponsor_entity_ulid,
        request_id=request_id,
        happened_at_utc=now,
        changed={"fields": ["readiness_status", "prev"]},
    )


def set_mou_status(
    *,
    sponsor_entity_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: str | None,
) -> None:
    _ensure_reqid(request_id)
    now = now_iso8601_ms()
    s = db.session.get(Sponsor, sponsor_entity_ulid)
    if not s:
        raise ValueError("sponsor not found")

    status = (status or "").strip().lower()
    if status not in mou_allowed():
        raise ValueError("invalid mou_status")

    if s.mou_status == status:
        return

    s.mou_status = status
    s.last_touch_utc = now
    db.session.flush()

    event_bus.emit(
        domain="sponsors",
        operation="mou_update",
        actor_ulid=actor_ulid,
        target_ulid=sponsor_entity_ulid,
        request_id=request_id,
        happened_at_utc=now,
        changed={"fields": ["mou_status", "prev"]},
    )


# -----------------
# Pledges
# -----------------


def _allowed_pledge_types() -> set[str]:
    return set(tax.SPONSOR_PLEDGE_TYPE_CODES)


def _allowed_pledge_statuses() -> set[str]:
    return set(tax.SPONSOR_PLEDGE_STATUS_CODES)


def _latest_pledges(sponsor_entity_ulid: str) -> dict[str, dict]:
    return _latest_snapshot(sponsor_entity_ulid, PLEDGE_SECTION)


# -----------------
# Prospect Realizations
# -----------------


def _latest_prospect_realizations(sponsor_entity_ulid: str) -> dict:
    return _latest_snapshot(sponsor_entity_ulid, PROSPECT_REAL_SECTION)


def record_prospect_realization(
    *,
    sponsor_entity_ulid: str,
    prospect_ulid: str,
    amount_cents: int,
    request_id: str,
    actor_ulid: str | None,
    journal_ulid: str | None = None,
    source: str | None = None,
    happened_at_utc: str | None = None,
) -> dict:
    """
    Record realized income against a Sponsor Funding Prospect / Pledge.

    This function does **not** move money and does not touch Finance tables.
    It is purely CRM bookkeeping on the Sponsors side:

      - Validates sponsor exists.
      - (Optionally) sanity-checks that prospect_ulid matches an existing pledge.
      - Appends a realization entry into SponsorHistory (prospect section).
      - Recomputes realized_total_cents for that prospect.
      - Emits a sponsors.prospect.realization event.

    The expectation is that callers will:

      1) Log the inbound donation in Finance via finance_v2.log_donation(...).
      2) Call this function with the same sponsor_entity_ulid / prospect_ulid /
         amount_cents and (optionally) the Finance journal_ulid.
    """
    _ensure_reqid(request_id)
    now = now_iso8601_ms()

    # 1) Validate sponsor
    s = db.session.get(Sponsor, sponsor_entity_ulid)
    if not s:
        raise ValueError("sponsor not found")

    # 2) Basic amount validation
    if not isinstance(amount_cents, int):
        raise ValueError("amount_cents must be an int")
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")

    # 3) Optional pledge sanity check: if we have a pledge index row, ensure it
    #    belongs to this sponsor. If not found, we still allow the realization.
    pledge_row = (
        db.session.query(SponsorPledgeIndex)
        .filter_by(pledge_ulid=prospect_ulid)
        .first()
    )
    if pledge_row and pledge_row.sponsor_entity_ulid != sponsor_entity_ulid:
        raise ValueError("prospect/pledge does not belong to sponsor")

    as_of = happened_at_utc or now

    # 4) Load latest snapshot and append realization
    latest = _latest_prospect_realizations(sponsor_entity_ulid)
    merged = {k: dict(v) for k, v in latest.items()}

    record = dict(merged.get(prospect_ulid) or {})
    total = int(record.get("realized_total_cents") or 0)
    entries = list(record.get("entries") or [])

    entry = {
        "amount_cents": int(amount_cents),
        "happened_at_utc": as_of,
        "journal_ulid": journal_ulid,
        "source": source,
    }
    entries.append(entry)
    total += int(amount_cents)

    record["realized_total_cents"] = total
    record["entries"] = entries
    merged[prospect_ulid] = record

    changed = stable_dumps(merged) != stable_dumps(latest)

    if not changed:
        # Nothing mutated; still touch sponsor for freshness.
        s.last_touch_utc = now
        db.session.flush()
        return {
            "sponsor_entity_ulid": sponsor_entity_ulid,
            "prospect_ulid": prospect_ulid,
            "realized_total_cents": total,
            "last_amount_cents": int(amount_cents),
            "history_ulid": None,
        }

    ver = _next_version(sponsor_entity_ulid, PROSPECT_REAL_SECTION)
    hist = SponsorHistory(
        sponsor_entity_ulid=sponsor_entity_ulid,
        section=PROSPECT_REAL_SECTION,
        version=ver,
        data_json=stable_dumps(merged),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    s.last_touch_utc = now
    db.session.flush()

    # Emit a Sponsors-side CRM event (no money moves here)
    event_bus.emit(
        domain="sponsors",
        operation="prospect_realization",
        actor_ulid=actor_ulid,
        target_ulid=sponsor_entity_ulid,
        request_id=request_id,
        happened_at_utc=now,
        refs={
            "prospect_ulid": prospect_ulid,
            "history_ulid": hist.ulid,
            "journal_ulid": journal_ulid,
        },
        changed={"fields": ["amount_cents", "realized_total_cents"]},
    )

    return {
        "sponsor_entity_ulid": sponsor_entity_ulid,
        "prospect_ulid": prospect_ulid,
        "realized_total_cents": total,
        "last_amount_cents": int(amount_cents),
        "history_ulid": hist.ulid,
    }


def _validate_pledge_payload(p: dict) -> dict:
    """
    Normalise and validate a pledge payload against Board policy.

    Required fields:
      - pledge_ulid (26 chars)
      - type (must be in policy_sponsor_pledge.types[*].code)
      - status (must be in policy_sponsor_pledge.statuses[*].code)

    Cash:
      - currency (default "USD")
      - stated_amount (int cents, >= 0)

    In-kind:
      - in_kind_category (string)
      - optional estimated_value (int >= 0) and currency
    """
    out: dict = {}

    pu = str(p.get("pledge_ulid") or "").strip()
    if len(pu) != 26:
        raise ValueError("pledge_ulid required (26)")
    out["pledge_ulid"] = pu

    allowed_types = _allowed_pledge_types()
    allowed_status = _allowed_pledge_statuses()

    t = (p.get("type") or "").strip().lower()
    if t not in allowed_types:
        raise ValueError("invalid pledge type")
    out["type"] = t

    st = (p.get("status") or "").strip().lower()
    if st not in allowed_status:
        raise ValueError("invalid pledge status")
    out["status"] = st

    out["notes"] = (
        str(p.get("notes")).strip()[:note_max] if p.get("notes") else None
    )

    # Restriction (optional)
    rest = p.get("restriction") or None
    if rest:
        out["restriction"] = {
            "fund_code": str(rest.get("fund_code") or "").strip()[:32],
            "purpose": str(rest.get("purpose") or "").strip()[:64],
        }

    # Schedule (optional; pass-through)
    if p.get("schedule"):
        out["schedule"] = p["schedule"]

    if t == "cash":
        cur = (p.get("currency") or "USD").upper()[:8]
        amt = p.get("stated_amount")
        if not isinstance(amt, int) or amt < 0:
            raise ValueError("stated_amount (int, cents) required for cash")
        out["currency"] = cur
        out["stated_amount"] = amt
    else:  # in_kind
        cat = (p.get("in_kind_category") or "").strip()
        if not cat:
            raise ValueError("in_kind_category required for in_kind")
        out["in_kind_category"] = cat
        if "estimated_value" in p and p["estimated_value"] is not None:
            if (
                not isinstance(p["estimated_value"], int)
                or p["estimated_value"] < 0
            ):
                raise ValueError(
                    "estimated_value must be int >=0 when provided"
                )
            out["estimated_value"] = p["estimated_value"]
            out["currency"] = (p.get("currency") or "USD").upper()[:8]
        if p.get("valuation_basis"):
            out["valuation_basis"] = str(p["valuation_basis"])[:32]

    return out


def upsert_pledge(
    *,
    sponsor_entity_ulid: str,
    pledge: dict,
    request_id: str,
    actor_ulid: str | None,
) -> str:
    """
    Create or update a pledge (by pledge_ulid) in History; update projection; emit names-only event.
    """
    _ensure_reqid(request_id)
    now = now_iso8601_ms()
    s = db.session.get(Sponsor, sponsor_entity_ulid)
    if not s:
        raise ValueError("sponsor not found")

    valid = _validate_pledge_payload(pledge)
    latest = _latest_pledges(sponsor_entity_ulid)
    merged = dict(latest)
    merged[valid["pledge_ulid"]] = valid

    changed = stable_dumps(merged) != stable_dumps(latest)
    if not changed:
        s.last_touch_utc = now
        db.session.flush()
        return list(merged.keys())[0]  # return pledge id anyway

    ver = _next_version(sponsor_entity_ulid, PLEDGE_SECTION)
    hist = SponsorHistory(
        sponsor_entity_ulid=sponsor_entity_ulid,
        section=PLEDGE_SECTION,
        version=ver,
        data_json=stable_dumps(merged),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    # projection row upsert
    pid = valid["pledge_ulid"]
    has_rest = bool(valid.get("restriction"))
    est_val = (
        valid.get("stated_amount")
        if valid["type"] == "cash"
        else valid.get("estimated_value")
    )
    cur = valid.get("currency")

    row = (
        db.session.query(SponsorPledgeIndex)
        .filter_by(pledge_ulid=pid)
        .first()
    )
    if row:
        row.type = valid["type"]
        row.status = valid["status"]
        row.has_restriction = has_rest
        row.est_value_number = est_val
        row.currency = cur
        row.updated_at_utc = now
    else:
        db.session.add(
            SponsorPledgeIndex(
                sponsor_entity_ulid=sponsor_entity_ulid,
                pledge_ulid=pid,
                type=valid["type"],
                status=valid["status"],
                has_restriction=has_rest,
                est_value_number=est_val,
                currency=cur,
                updated_at_utc=now,
            )
        )

    s.pledge_last_update_utc = now
    s.last_touch_utc = now
    db.session.flush()

    event_bus.emit(
        domain="sponsors",
        operation="pledge_upsert",
        actor_ulid=actor_ulid,
        target_ulid=sponsor_entity_ulid,
        request_id=request_id,
        happened_at_utc=now,
        refs={"pledge_ulid": pid, "version_ptr": hist.ulid},
    )

    return pid


def set_pledge_status(
    *,
    pledge_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: str | None,
) -> None:
    _ensure_reqid(request_id)
    now = now_iso8601_ms()
    status = (status or "").strip().lower()

    allowed_status = _allowed_pledge_statuses()
    if status not in allowed_status:
        raise ValueError("invalid pledge status")

    row = (
        db.session.query(SponsorPledgeIndex)
        .filter_by(pledge_ulid=pledge_ulid)
        .first()
    )
    if not row:
        raise ValueError("pledge not found")
    if row.status == status:
        return

    row.status = status
    row.updated_at_utc = now
    db.session.flush()

    event_bus.emit(
        domain="sponsors",
        operation="pledge_status_update",
        actor_ulid=actor_ulid,
        target_ulid=row.sponsor_entity_ulid,
        request_id=request_id,
        happened_at_utc=now,
        changed={"fields": ["pledge_ulid", "status", "prev"]},
    )


# -----------------
# views/search
# -----------------


def sponsor_view(sponsor_entity_ulid: str) -> SponsorView | None:
    s = db.session.get(Sponsor, sponsor_entity_ulid)
    if not s:
        return None
    caps = (
        db.session.query(SponsorCapabilityIndex)
        .filter_by(sponsor_entity_ulid=sponsor_entity_ulid, active=True)
        .all()
    )
    pledges = (
        db.session.query(SponsorPledgeIndex)
        .filter_by(sponsor_entity_ulid=s.entity_ulid)
        .all()
    )
    return map_sponsor_view(s, caps, pledges)


def find_sponsors(
    *,
    any_of: list[tuple[str, str]] | None = None,
    readiness_in: list[str] | None = None,
    has_active_pledges: bool | None = None,
    admin_review_required: bool | None = None,
    page: int = 1,
    per: int = 50,
) -> tuple[list[SponsorView], int]:
    q = db.session.query(Sponsor)
    if readiness_in:
        q = q.filter(Sponsor.readiness_status.in_(list(set(readiness_in))))
    if admin_review_required is not None:
        q = q.filter(
            Sponsor.admin_review_required.is_(bool(admin_review_required))
        )
    # any_of capabilities (OR)
    if any_of:
        ors = []
        for d, k in any_of:
            ors.append(
                db.session.query(SponsorCapabilityIndex.sponsor_entity_ulid)
                .filter_by(domain=d, key=k, active=True)
                .with_entities(SponsorCapabilityIndex.sponsor_entity_ulid)
            )
        ids = set()
        for sub in ors:
            ids.update([r[0] for r in sub.all()])
        if ids:
            q = q.filter(Sponsor.entity_ulid.in_(list(ids)))
        else:
            return [], 0
    # has_active_pledges
    if has_active_pledges is not None:
        sub_ids = [
            r[0]
            for r in db.session.query(SponsorPledgeIndex.sponsor_entity_ulid)
            .filter(SponsorPledgeIndex.status.in_(("proposed", "active")))
            .distinct()
            .all()
        ]
        if has_active_pledges:
            q = q.filter(Sponsor.entity_ulid.in_(sub_ids or ["_none_"]))
        else:
            if sub_ids:
                q = q.filter(~Sponsor.entity_ulid.in_(sub_ids))
    total = q.count()
    rows = (
        q.order_by(Sponsor.updated_at_utc.desc())
        .offset((page - 1) * per)
        .limit(per)
        .all()
    )
    views = [sponsor_view(r.entity_ulid) for r in rows]
    return [v for v in views if v is not None], total
