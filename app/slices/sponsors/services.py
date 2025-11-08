# app/slices/sponsors/services.py
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import desc, func

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms, utcnow_naive
from app.lib.jsonutil import stable_dumps

from .models import (
    Sponsor,
    SponsorCapabilityIndex,
    SponsorHistory,
    SponsorPledgeIndex,
)

# ---------------- Controlled vocabulary (move to Governance later) ----------------
SPONSOR_CAPS: dict[str, tuple[str, ...]] = {
    "funding": (
        "cash_grant",
        "restricted_grant",
        "event_sponsorship",
        "matching_gifts",
    ),
    "in_kind": (
        "in_kind_food",
        "in_kind_goods",
        "in_kind_services",
        "facility_use",
        "equipment_loan",
        "volunteer_hours",
    ),
    "meta": ("unclassified",),
}

CAPS_SECTION = "sponsor:capability:v1"
PLEDGE_SECTION = "sponsor:pledge:v1"
NOTE_MAX = 120

READINESS_ALLOWED = {"draft", "review", "active", "suspended"}
MOU_ALLOWED = {"none", "pending", "active", "expired", "terminated"}

# ---------------- helpers ----------------


def _ensure_reqid(rid: Optional[str]) -> str:
    if not rid or not str(rid).strip():
        raise ValueError("request_id must be non-empty")
    return str(rid)


def _split(flat_key: str) -> Tuple[str, str]:
    if "." not in flat_key:
        raise ValueError(f"invalid key '{flat_key}' (expected 'domain.key')")
    d, k = flat_key.split(".", 1)
    return d.strip(), k.strip()


def _validate_caps(payload: Dict[str, Any]) -> Dict[str, dict]:
    norm: Dict[str, dict] = {}
    for flat, obj in (payload or {}).items():
        d, k = _split(flat)
        if d not in SPONSOR_CAPS or k not in SPONSOR_CAPS[d]:
            raise ValueError(f"unknown capability '{d}.{k}'")
        if not isinstance(obj, dict) or "has" not in obj:
            raise ValueError(f"missing 'has' in '{flat}'")
        has = bool(obj["has"])
        note = obj.get("note")
        if note is not None:
            note = str(note).strip()[:NOTE_MAX] or None
        norm[f"{d}.{k}"] = {"has": has, **({"note": note} if note else {})}
    return norm


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


# ---------------- core: sponsor row ----------------


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


# ---------------- capabilities: replace & patch ----------------


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


# ---------------- readiness/mou helpers ----------------


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
    if status not in READINESS_ALLOWED:
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
        changed_fields={"readiness_status": status, "prev": prev},
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
    if status not in MOU_ALLOWED:
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
        changed_fields={"mou_status": status, "prev": prev},
    )


# ---------------- pledges ----------------

PLEDGE_ALLOWED_TYPES = {"cash", "in_kind"}
PLEDGE_ALLOWED_STATUS = {"proposed", "active", "fulfilled", "cancelled"}


def _latest_pledges(sponsor_ulid: str) -> Dict[str, dict]:
    h = (
        db.session.query(SponsorHistory)
        .filter_by(sponsor_ulid=sponsor_ulid, section=PLEDGE_SECTION)
        .order_by(desc(SponsorHistory.version))
        .first()
    )
    return json.loads(h.data_json) if h else {}


def _validate_pledge_payload(p: dict) -> dict:
    """
    Required: pledge_ulid, type, status
    Cash: currency, stated_amount (int cents)
    In-kind: in_kind_category, estimated_value (int units/cents optional), currency optional if using value
    """
    out = {}
    pu = str(p.get("pledge_ulid") or "").strip()
    if len(pu) != 26:
        raise ValueError("pledge_ulid required (26)")
    t = (p.get("type") or "").strip().lower()
    if t not in PLEDGE_ALLOWED_TYPES:
        raise ValueError("invalid pledge type")
    st = (p.get("status") or "").strip().lower()
    if st not in PLEDGE_ALLOWED_STATUS:
        raise ValueError("invalid pledge status")

    out["pledge_ulid"] = pu
    out["type"] = t
    out["status"] = st
    out["notes"] = (
        str(p.get("notes")).strip()[:NOTE_MAX] if p.get("notes") else None
    )

    # restriction (optional)
    rest = p.get("restriction") or None
    if rest:
        out["restriction"] = {
            "fund_code": str(rest.get("fund_code") or "").strip()[:32],
            "purpose": str(rest.get("purpose") or "").strip()[:64],
        }
    # schedule (optional; passthrough minimal)
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
    if status not in PLEDGE_ALLOWED_STATUS:
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
    row.updated_at_utc = now_iso8601_ms()
    # bump sponsor ops
    s = db.session.get(Sponsor, row.sponsor_ulid)
    if s:
        s.pledge_last_update_utc = row.updated_at_utc
        s.last_touch_utc = row.updated_at_utc
    db.session.commit()
    event_bus.emit(
        domain="sponsors",
        operation="pleddge_update",
        actor_ulid=actor_ulid,
        target_ulid=row.sponsor_ulid,
        request_id=request_id,
        happened_at_utc=row.updated_at_utc,
        refs={"pledge_ulid": pledge_ulid},
    )


# ---------------- views/search ----------------


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
        from sqlalchemy import or_, and_

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
