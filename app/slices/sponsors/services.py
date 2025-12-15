# app/slices/sponsors/services.py
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, func, select

from app.extensions import db, event_bus
from app.extensions.contracts import finance_v2
from app.extensions.contracts.governance_v2 import (
    get_sponsor_capability_policy,
    get_sponsor_lifecycle_policy,
    get_sponsor_pledge_policy,
)
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.lib.jsonutil import stable_dumps
from app.services import poc as poc_svc

from .models import (
    Allocation,
    Sponsor,
    SponsorCapabilityIndex,
    SponsorHistory,
    SponsorPledgeIndex,
    SponsorPOC,
)

# -----------------
# Wrappers & Helpers
# -----------------

log = logging.getLogger(__name__)

# History sections (these labels are part of our own internal structure;
# the *allowed values* within those sections come from Board policy.)
CAPS_SECTION = "sponsor:capability:v1"
PLEDGE_SECTION = "sponsor:pledge:v1"
NOTE_MAX = 120  # shared misc cap for short-string notes


def _ensure_reqid(request_id: str) -> None:
    if not request_id or not isinstance(request_id, str):
        raise ValueError("request_id required")
    if len(request_id) < 8:
        # just a sanity guard; IDs come from caller (usually contracts)
        raise ValueError("request_id too short")


def _split(flat_key: str) -> Tuple[str, str]:
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
    payload: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
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
    flat: Dict[str, Dict[str, Any]] = {}

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
                out: Dict[str, Any] = {}
                if "has" in obj:
                    out["has"] = bool(obj["has"])
                else:
                    # default missing "has" → True
                    out["has"] = True
                note_raw = obj.get("note")
                if note_raw is not None:
                    note = str(note_raw).strip()
                    if note:
                        out["note"] = note[:NOTE_MAX]
                flat[flat_key] = out
            else:
                raise ValueError("invalid capability payload value")

    return flat


def get_allocation_by_ulid(allocation_ulid: str) -> Allocation:
    """
    Slice-local helper to look up an Allocation by ULID.

    The Extensions contract (sponsors_v2.allocation_spend) calls this
    so it doesn't have to reach into the Sponsors tables directly.
    """
    if not allocation_ulid:
        raise ValueError("allocation_ulid is required")

    row = db.session.execute(
        select(Allocation).where(Allocation.ulid == allocation_ulid)
    ).scalar_one_or_none()
    if not row:
        raise ValueError(f"allocation {allocation_ulid} not found")

    return row


# -----------------
# Validate Caps
# -----------------


def _validate_caps(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Validate and normalise a sponsor capability payload against Board policy.

    - Normalises nested/flat payload shapes.
    - Ensures every capability code is in the Governance capability policy.
    - Trims note fields to NOTE_MAX chars.

    Returns a dict keyed by flat capability code, for example:

        {
          "funding.cash_grant": {"has": True, "note": "Board approved"},
          "in_kind.volunteer_hours": {"has": False},
        }
    """
    flat = _flatten_caps_payload(payload)
    if not flat:
        return flat

    policy = get_sponsor_capability_policy()
    # Governance policy exposes *flat* capability codes, e.g. "funding.cash_grant".
    # (See policy_sponsor_capabilities.json + governance_v2.SponsorCapsDTO.)
    allowed_flat: set[str] = policy.all_codes  # set of strings

    unknown = sorted(k for k in flat.keys() if k not in allowed_flat)
    if unknown:
        raise ValueError(f"invalid capability keys: {', '.join(unknown)}")

    return flat


def _latest_caps(sponsor_ulid: str) -> Dict[str, dict]:
    h = (
        db.session.query(SponsorHistory)
        .filter_by(sponsor_ulid=sponsor_ulid, section=CAPS_SECTION)
        .order_by(desc(SponsorHistory.version))
        .first()
    )
    return json.loads(h.data_json) if h else {}


def _next_version(sponsor_ulid: str, section: str) -> int:
    cur = (
        db.session.query(func.max(SponsorHistory.version))
        .filter_by(sponsor_ulid=sponsor_ulid, section=section)
        .scalar()
    )
    return int(cur or 0) + 1


def allowed_capabilities() -> List[str]:
    """
    Convenience helper: return all allowed flat capability codes from policy,
    sorted for U.I. / CLI.
    """
    policy = get_sponsor_capability_policy()
    return sorted(policy.all_codes)


# -----------------
# Point of Contact
# wrappers for
# app.services.poc
# -----------------


def sponsor_link_poc(
    *,
    org_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int = 0,
    is_primary: bool = False,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    return poc_svc.link_poc(
        db.session,
        POCModel=SponsorPOC,
        domain="sponsors",
        org_ulid=org_ulid,
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
    org_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int | None = None,
    is_primary: bool | None = None,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    return poc_svc.update_poc(
        db.session,
        POCModel=SponsorPOC,
        domain="sponsors",
        org_ulid=org_ulid,
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
    org_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    return poc_svc.unlink_poc(
        db.session,
        POCModel=SponsorPOC,
        domain="sponsors",
        org_ulid=org_ulid,
        person_entity_ulid=person_entity_ulid,
        scope=scope,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def sponsor_list_pocs(*, org_ulid: str) -> list[dict]:
    return poc_svc.list_pocs(
        db.session, POCModel=SponsorPOC, org_ulid=org_ulid
    )


# -----------------
# core: sponsor row
# -----------------


def ensure_sponsor(
    *, entity_ulid: str, request_id: str, actor_ulid: Optional[str]
) -> str:
    _ensure_reqid(request_id)
    s = db.session.query(Sponsor).filter_by(entity_ulid=entity_ulid).first()
    if not s:
        now = now_iso8601_ms()
        s = Sponsor(
            entity_ulid=entity_ulid,
            first_seen_utc=now,
            last_touch_utc=now,
            readiness_status="draft",
            mou_status="none",
        )
        db.session.add(s)
        db.session.commit()
        event_bus.emit(
            domain="sponsors",
            operation="created_insert",
            actor_ulid=actor_ulid,
            target_ulid=s.ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"entity_ulid": entity_ulid},
        )
    else:
        s.last_touch_utc = now_iso8601_ms()
        db.session.commit()
    return s.ulid


# -----------------
# Capabilities:
# replace & patch
# -----------------


def upsert_capabilities(
    *,
    sponsor_ulid: str,
    payload: Dict[str, Any],
    request_id: str,
    actor_ulid: Optional[str],
) -> str | None:
    _ensure_reqid(request_id)
    s = db.session.get(Sponsor, sponsor_ulid)
    if not s:
        raise ValueError("sponsor not found")
    norm = _validate_caps(payload)
    last = _latest_caps(sponsor_ulid)
    if last and stable_dumps(last) == stable_dumps(norm):
        s.last_touch_utc = now_iso8601_ms()
        db.session.commit()
        return None

    before = {k for k, v in last.items() if v.get("has")}
    after = {k for k, v in norm.items() if v.get("has")}
    added, removed = sorted(after - before), sorted(before - after)

    ver = _next_version(sponsor_ulid, CAPS_SECTION)
    hist = SponsorHistory(
        sponsor_ulid=sponsor_ulid,
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
            sponsor_ulid=sponsor_ulid
        )
    }
    now = now_iso8601_ms()
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
                    sponsor_ulid=sponsor_ulid,
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
    db.session.commit()

    for flat in added:
        d, k = _split(flat)
        event_bus.emit(
            domain="sponsors",
            operation="capability_add",
            actor_ulid=actor_ulid,
            target_ulid=sponsor_ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )
    for flat in removed:
        d, k = _split(flat)
        event_bus.emit(
            domain="sponsors",
            operation="capability_remove",
            actor_ulid=actor_ulid,
            target_ulid=sponsor_ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )
    return hist.ulid


def patch_capabilities(
    *,
    sponsor_ulid: str,
    payload: Dict[str, Any],
    request_id: str,
    actor_ulid: Optional[str],
) -> str | None:
    _ensure_reqid(request_id)
    s = db.session.get(Sponsor, sponsor_ulid)
    if not s:
        raise ValueError("sponsor not found")
    patch = _validate_caps(payload)
    last = _latest_caps(sponsor_ulid)
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
                merged[flat]["note"] = str(note)[:NOTE_MAX]
    if stable_dumps(merged) == stable_dumps(last):
        s.last_touch_utc = now_iso8601_ms()
        db.session.commit()
        return None

    before = {k for k, v in last.items() if v.get("has")}
    after = {k for k, v in merged.items() if v.get("has")}
    added, removed = sorted(after - before), sorted(before - after)

    ver = _next_version(sponsor_ulid, CAPS_SECTION)
    hist = SponsorHistory(
        sponsor_ulid=sponsor_ulid,
        section=CAPS_SECTION,
        version=ver,
        data_json=stable_dumps(merged),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    # touch only affected keys in projection (no deletions)
    now = now_iso8601_ms()
    for flat, obj in patch.items():
        d, k = _split(flat)
        active = bool(obj.get("has"))
        row = (
            db.session.query(SponsorCapabilityIndex)
            .filter_by(sponsor_ulid=sponsor_ulid, domain=d, key=k)
            .first()
        )
        if row:
            row.active = active
            row.updated_at_utc = now
        else:
            db.session.add(
                SponsorCapabilityIndex(
                    sponsor_ulid=sponsor_ulid,
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
    db.session.commit()

    for flat in added:
        d, k = _split(flat)
        event_bus.emit(
            domain="sponsors",
            operation="capablity_add",
            actor_ulid=actor_ulid,
            target_ulid=sponsor_ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )
    for flat in removed:
        d, k = _split(flat)
        event_bus.emit(
            domain="sponsors",
            operation="capability_remove",
            actor_ulid=actor_ulid,
            target_ulid=sponsor_ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )
    return hist.ulid


# -----------------
# Readiness/MOU
# helpers
# -----------------


def set_readiness_status(
    *,
    sponsor_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: Optional[str],
) -> None:
    _ensure_reqid(request_id)
    s = db.session.get(Sponsor, sponsor_ulid)
    if not s:
        raise ValueError("sponsor not found")

    status = (status or "").strip().lower()

    lifecycle = get_sponsor_lifecycle_policy()
    allowed_readiness = set(lifecycle["readiness_allowed"])
    if status not in allowed_readiness:
        raise ValueError("invalid readiness_status")

    if s.readiness_status == status:
        return

    prev = s.readiness_status
    s.readiness_status = status
    s.last_touch_utc = now_iso8601_ms()
    db.session.commit()

    event_bus.emit(
        domain="sponsors",
        operation="readiness_update",
        actor_ulid=actor_ulid,
        target_ulid=sponsor_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        changed={"readiness_status": status, "prev": prev},
    )


def set_mou_status(
    *,
    sponsor_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: Optional[str],
) -> None:
    _ensure_reqid(request_id)
    s = db.session.get(Sponsor, sponsor_ulid)
    if not s:
        raise ValueError("sponsor not found")

    status = (status or "").strip().lower()

    lifecycle = get_sponsor_lifecycle_policy()
    allowed_mou = set(lifecycle["mou_allowed"])
    if status not in allowed_mou:
        raise ValueError("invalid mou_status")

    if s.mou_status == status:
        return

    prev = s.mou_status
    s.mou_status = status
    s.last_touch_utc = now_iso8601_ms()
    db.session.commit()

    event_bus.emit(
        domain="sponsors",
        operation="mou_update",
        actor_ulid=actor_ulid,
        target_ulid=sponsor_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        changed={"mou_status": status, "prev": prev},
    )


# -----------------
# Pledges
# -----------------


def _pledge_policy() -> dict:
    """
    Thin wrapper around Governance pledge policy.

    Returns a dict with:
      - types:     list of {code, label}
      - statuses:  list of {code, label}
      - transitions: optional {status -> [next...]}
    """
    return get_sponsor_pledge_policy()


def _allowed_pledge_types() -> set[str]:
    policy = _pledge_policy()
    # JSON shape: "types": [{ "code": "...", "label": "..." }, ...]
    return {t["code"] for t in policy.get("types", [])}


def _allowed_pledge_statuses() -> set[str]:
    policy = _pledge_policy()
    # JSON shape: "statuses": [{ "code": "...", "label": "..." }, ...]
    return {s["code"] for s in policy.get("statuses", [])}


def _latest_pledges(sponsor_ulid: str) -> Dict[str, dict]:
    h = (
        db.session.query(SponsorHistory)
        .filter_by(sponsor_ulid=sponsor_ulid, section=PLEDGE_SECTION)
        .order_by(desc(SponsorHistory.version))
        .first()
    )
    return json.loads(h.data_json) if h else {}


# -----------------
# Prospect Realizations
# -----------------

PROSPECT_REAL_SECTION = "sponsor:prospect_realization:v1"


def _latest_prospect_realizations(sponsor_ulid: str) -> dict:
    """
    Load the latest Funding Prospect realization snapshot for this sponsor.

    Shape (data_json):
        {
          "<prospect_ulid>": {
            "realized_total_cents": int,
            "entries": [
              {
                "amount_cents": int,
                "happened_at_utc": str,
                "journal_ulid": str | None,
                "source": str | None,
              },
              ...
            ],
          },
          ...
        }
    """
    h = (
        db.session.query(SponsorHistory)
        .filter_by(sponsor_ulid=sponsor_ulid, section=PROSPECT_REAL_SECTION)
        .order_by(desc(SponsorHistory.version))
        .first()
    )
    return json.loads(h.data_json) if h else {}


def record_prospect_realization(
    *,
    sponsor_ulid: str,
    prospect_ulid: str,
    amount_cents: int,
    request_id: str,
    actor_ulid: Optional[str],
    journal_ulid: Optional[str] = None,
    source: Optional[str] = None,
    happened_at_utc: Optional[str] = None,
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
      2) Call this function with the same sponsor_ulid / prospect_ulid /
         amount_cents and (optionally) the Finance journal_ulid.
    """
    _ensure_reqid(request_id)

    # 1) Validate sponsor
    s = db.session.get(Sponsor, sponsor_ulid)
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
    if pledge_row and pledge_row.sponsor_ulid != sponsor_ulid:
        raise ValueError("prospect/pledge does not belong to sponsor")

    as_of = happened_at_utc or now_iso8601_ms()

    # 4) Load latest snapshot and append realization
    latest = _latest_prospect_realizations(sponsor_ulid)
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
    now = now_iso8601_ms()

    if not changed:
        # Nothing mutated; still touch sponsor for freshness.
        s.last_touch_utc = now
        db.session.commit()
        return {
            "sponsor_ulid": sponsor_ulid,
            "prospect_ulid": prospect_ulid,
            "realized_total_cents": total,
            "last_amount_cents": int(amount_cents),
            "history_ulid": None,
        }

    ver = _next_version(sponsor_ulid, PROSPECT_REAL_SECTION)
    hist = SponsorHistory(
        sponsor_ulid=sponsor_ulid,
        section=PROSPECT_REAL_SECTION,
        version=ver,
        data_json=stable_dumps(merged),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    s.last_touch_utc = now
    db.session.commit()

    # Emit a Sponsors-side CRM event (no money moves here)
    event_bus.emit(
        domain="sponsors",
        operation="prospect.realization",
        actor_ulid=actor_ulid,
        target_ulid=sponsor_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "prospect_ulid": prospect_ulid,
            "history_ulid": hist.ulid,
            "journal_ulid": journal_ulid,
        },
        changed={
            "amount_cents": int(amount_cents),
            "realized_total_cents": total,
        },
    )

    return {
        "sponsor_ulid": sponsor_ulid,
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
        str(p.get("notes")).strip()[:NOTE_MAX] if p.get("notes") else None
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
    sponsor_ulid: str,
    pledge: dict,
    request_id: str,
    actor_ulid: Optional[str],
) -> str:
    """
    Create or update a pledge (by pledge_ulid) in History; update projection; emit names-only event.
    """
    _ensure_reqid(request_id)
    s = db.session.get(Sponsor, sponsor_ulid)
    if not s:
        raise ValueError("sponsor not found")

    valid = _validate_pledge_payload(pledge)
    latest = _latest_pledges(sponsor_ulid)
    merged = dict(latest)
    merged[valid["pledge_ulid"]] = valid

    changed = stable_dumps(merged) != stable_dumps(latest)
    if not changed:
        s.last_touch_utc = now_iso8601_ms()
        db.session.commit()
        return list(merged.keys())[0]  # return pledge id anyway

    ver = _next_version(sponsor_ulid, PLEDGE_SECTION)
    hist = SponsorHistory(
        sponsor_ulid=sponsor_ulid,
        section=PLEDGE_SECTION,
        version=ver,
        data_json=stable_dumps(merged),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    # projection row upsert
    now = now_iso8601_ms()
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
                sponsor_ulid=sponsor_ulid,
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
    db.session.commit()

    event_bus.emit(
        domain="sponsors",
        operation="pledge_upsert",
        actor_ulid=actor_ulid,
        target_ulid=sponsor_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"pledge_ulid": pid, "version_ptr": hist.ulid},
    )

    return pid


def set_pledge_status(
    *,
    pledge_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: Optional[str],
) -> None:
    _ensure_reqid(request_id)
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

    prev = row.status
    row.status = status
    row.updated_at_utc = now_iso8601_ms()
    db.session.commit()

    event_bus.emit(
        domain="sponsors",
        operation="pledge_status_update",
        actor_ulid=actor_ulid,
        target_ulid=row.sponsor_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        changed={"pledge_ulid": pledge_ulid, "status": status, "prev": prev},
    )


# -----------------
# FLOW: allocation spend → finance journal
# -----------------


def spend_allocation(
    *,
    allocation_ulid: str,
    amount_cents: int,
    request_id: str,
    actor_ulid: str | None = None,
    category: str | None = None,
    vendor: str | None = None,
    occurred_on: str | None = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Spend against a Sponsor Allocation, posting an expense to Finance and
    emitting a ledger event.

    This is real wiring:
      - Looks up the Allocation row.
      - Builds a Finance expense payload (fund + project).
      - Calls finance_v2.log_expense (journal entry).
      - Emits sponsors.allocation.spent into the Ledger.

    Policy checks (caps, status, RBAC spending authority) can layer on
    later, but this function should never be a stub.
    """
    as_of = occurred_on or now_iso8601_ms()

    # 1) Load the Allocation row (slice owns the SQL)
    alloc = db.session.execute(
        select(Allocation).where(Allocation.ulid == allocation_ulid)
    ).scalar_one_or_none()
    if not alloc:
        raise LookupError(f"allocation {allocation_ulid} not found")

    # FIXME: align these attribute names to your real model
    fund_id = alloc.fund_ulid  # finance_fund.ulid
    project_id = alloc.project_ulid  # calendar.project_ulid
    sponsor_ulid = alloc.sponsor_ulid  # sponsor_allocation.ulid

    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")

    # 2) Build Finance expense payload
    payload = {
        "fund_id": fund_id,
        "project_id": project_id,
        "occurred_on": as_of,
        "vendor": vendor or "allocation-spend",
        "amount_cents": int(amount_cents),
        "category": category or "sponsor_allocation",
        # Optional: tie back to this allocation in Finance
        "external_ref": allocation_ulid,
        "memo": f"Sponsor allocation {allocation_ulid} spend",
    }

    # 3) Call Finance contract: real journal entry
    expense = finance_v2.log_expense(payload, dry_run=dry_run)

    # 4) (Optional but recommended) update allocation totals / status
    # FIXME: match your real allocation fields here
    if not dry_run:
        if hasattr(alloc, "spent_cents"):
            alloc.spent_cents = int(getattr(alloc, "spent_cents") or 0) + int(
                amount_cents
            )
        db.session.add(alloc)
        db.session.commit()

        # 5) Emit Ledger spine
        event_bus.emit(
            domain="sponsors",
            operation="allocation.spent",
            request_id=request_id,
            actor_ulid=actor_ulid,
            target_ulid=sponsor_ulid,
            refs={
                "allocation_ulid": allocation_ulid,
                "fund_id": fund_id,
                "project_id": project_id,
                "journal_id": expense.id,
            },
            changed={"amount_cents": int(amount_cents)},
            meta={
                "category": expense.category,
                "occurred_on": expense.occurred_on,
            },
            happened_at_utc=as_of,
            chain_key="finance",
        )

    return {
        "allocation_ulid": allocation_ulid,
        "amount_cents": int(amount_cents),
        "expense_id": expense.id,
        "fund_id": fund_id,
        "project_id": project_id,
        "dry_run": bool(dry_run),
    }


# -----------------
# views/search
# -----------------


def sponsor_view(sponsor_ulid: str) -> Optional[dict]:
    s = db.session.get(Sponsor, sponsor_ulid)
    if not s:
        return None
    caps = (
        db.session.query(SponsorCapabilityIndex)
        .filter_by(sponsor_ulid=s.ulid, active=True)
        .all()
    )
    pledges = (
        db.session.query(SponsorPledgeIndex)
        .filter_by(sponsor_ulid=s.ulid)
        .all()
    )
    return {
        "sponsor_ulid": s.ulid,
        "entity_ulid": s.entity_ulid,
        "admin_review_required": s.admin_review_required,
        "readiness_status": s.readiness_status,
        "mou_status": s.mou_status,
        "active_capabilities": [
            {"domain": c.domain, "key": c.key} for c in caps
        ],
        "pledges": [
            {
                "pledge_ulid": p.pledge_ulid,
                "type": p.type,
                "status": p.status,
                "has_restriction": p.has_restriction,
                "est_value_number": p.est_value_number,
                "currency": p.currency,
                "updated_at_utc": p.updated_at_utc,
            }
            for p in pledges
        ],
        "capability_last_update_utc": s.capability_last_update_utc,
        "pledge_last_update_utc": s.pledge_last_update_utc,
        "first_seen_utc": s.first_seen_utc,
        "last_touch_utc": s.last_touch_utc,
        "created_at_utc": s.created_at_utc,
        "updated_at_utc": s.updated_at_utc,
    }


def find_sponsors(
    *,
    any_of: Optional[list[tuple[str, str]]] = None,
    readiness_in: Optional[list[str]] = None,
    has_active_pledges: Optional[bool] = None,
    admin_review_required: Optional[bool] = None,
    page: int = 1,
    per: int = 50,
) -> tuple[list[dict], int]:
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
                db.session.query(SponsorCapabilityIndex.sponsor_ulid)
                .filter_by(domain=d, key=k, active=True)
                .with_entities(SponsorCapabilityIndex.sponsor_ulid)
            )
        ids = set()
        for sub in ors:
            ids.update([r[0] for r in sub.all()])
        if ids:
            q = q.filter(Sponsor.ulid.in_(list(ids)))
        else:
            return [], 0
    # has_active_pledges
    if has_active_pledges is not None:
        sub_ids = [
            r[0]
            for r in db.session.query(SponsorPledgeIndex.sponsor_ulid)
            .filter(SponsorPledgeIndex.status.in_(("proposed", "active")))
            .distinct()
            .all()
        ]
        if has_active_pledges:
            q = q.filter(Sponsor.ulid.in_(sub_ids or ["_none_"]))
        else:
            if sub_ids:
                q = q.filter(~Sponsor.ulid.in_(sub_ids))
    total = q.count()
    rows = (
        q.order_by(Sponsor.updated_at_utc.desc())
        .offset((page - 1) * per)
        .limit(per)
        .all()
    )
    return [sponsor_view(r.ulid) for r in rows], total
