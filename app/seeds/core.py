# app/seeds/core.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, Iterable

from app.extensions import db
from app.lib.ids import new_ulid
from app.lib.chrono import now_iso8601_ms

# -------- Entity (minimal org + person) ----------
from app.slices.entity.models import Entity
try:
    from app.slices.entity.models import EntityOrg  # if present
except Exception:  # pragma: no cover
    EntityOrg = None  # type: ignore

try:
    from app.slices.entity.models import EntityPerson  # if present
except Exception:  # pragma: no cover
    EntityPerson = None  # type: ignore

# -------- Customers ------------------------------
try:
    from app.slices.customers.models import Customer
except Exception:
    Customer = None  # type: ignore

# -------- Resources ------------------------------
from app.slices.resources.models import (
    Resource,
    ResourceCapabilityIndex,
    ResourceHistory,
)

# -------- Sponsors -------------------------------
from app.slices.sponsors.models import (
    Sponsor,
    SponsorCapabilityIndex,
    SponsorHistory,
    SponsorPledgeIndex,
)

# ---------------- Utils ----------------
def _iso_now():
    return now_iso8601_ms()

def _infer_domain(key: str) -> str:
    veterans = {"va_forms", "claims_help"}
    housing = {"housing", "furniture", "welcome_home_kit"}
    if key in veterans:
        return "veterans_affairs"
    if key in housing:
        return "housing"
    return "basic_needs"

def _flatten_caps_json(d: Dict[str, bool]) -> str:
    import json
    return json.dumps({k: {"has": bool(v)} for k, v in (d or {}).items()}, ensure_ascii=False)

# ---------------- Seeds ----------------
@dataclass(frozen=True)
class SeedCustomerResult:
    entity_ulid: str
    customer_ulid: str

@dataclass(frozen=True)
class SeedResourceResult:
    entity_ulid: str
    resource_ulid: str
    code: str

@dataclass(frozen=True)
class SeedSponsorResult:
    entity_ulid: str
    sponsor_ulid: str
    code: str

def _ensure_org_entity(*, org_name: str = "Seeded Org", entity_ulid: Optional[str] = None) -> str:
    e_ulid = entity_ulid or new_ulid()
    now = _iso_now()

    if not db.session.get(Entity, e_ulid):
        e = Entity(ulid=e_ulid, kind="org")
        if hasattr(e, "created_at_utc"): e.created_at_utc = now
        if hasattr(e, "updated_at_utc"): e.updated_at_utc = now
        db.session.add(e)
        db.session.flush()

    if EntityOrg is not None:
        org = db.session.query(EntityOrg).filter_by(entity_ulid=e_ulid).one_or_none()
        if org is None:
            org = EntityOrg(entity_ulid=e_ulid, org_name=org_name)
            if hasattr(org, "created_at_utc"): org.created_at_utc = now
            if hasattr(org, "updated_at_utc"): org.updated_at_utc = now
            db.session.add(org)
            db.session.flush()

    return e_ulid

def seed_minimal_customer(*, first: str = "TEST", last: str = "USER") -> SeedCustomerResult:
    """
    Canon: named Person required before Customer.
    """
    assert EntityPerson is not None and Customer is not None, "EntityPerson/Customer models required"
    now = _iso_now()
    e_ulid, c_ulid = new_ulid(), new_ulid()

    e = Entity(ulid=e_ulid, kind="person")
    if hasattr(e, "created_at_utc"): e.created_at_utc = now
    if hasattr(e, "updated_at_utc"): e.updated_at_utc = now

    p = EntityPerson(entity_ulid=e_ulid, first_name=first, last_name=last)
    if hasattr(p, "created_at_utc"): p.created_at_utc = now
    if hasattr(p, "updated_at_utc"): p.updated_at_utc = now

    c = Customer(ulid=c_ulid, entity_ulid=e_ulid)
    if hasattr(c, "created_at_utc"): c.created_at_utc = now
    if hasattr(c, "updated_at_utc"): c.updated_at_utc = now

    db.session.add_all([e, p, c])
    db.session.commit()
    return SeedCustomerResult(entity_ulid=e_ulid, customer_ulid=c_ulid)

def seed_active_resource(
    *,
    code: str = "res-dev-001",
    label: str = "Sample Dev Resource",
    capabilities: Optional[Dict[str, bool]] = None,
    readiness_status: str = "active",   # draft|review|active|suspended
    mou_status: str = "active",         # none|pending|active|expired|terminated
    entity_ulid: Optional[str] = None,
) -> SeedResourceResult:
    caps = capabilities or {"housing": True, "furniture": True, "barber": False}
    e_ulid = _ensure_org_entity(entity_ulid=entity_ulid, org_name=label)
    now = _iso_now()
    r_ulid = new_ulid()

    r = Resource(
        ulid=r_ulid,
        entity_ulid=e_ulid,
        admin_review_required=False,
        readiness_status=readiness_status,
        mou_status=mou_status,
        first_seen_utc=now,
        last_touch_utc=now,
        capability_last_update_utc=now,
    )
    if hasattr(r, "created_at_utc"): r.created_at_utc = now
    if hasattr(r, "updated_at_utc"): r.updated_at_utc = now
    db.session.add(r)
    db.session.flush()

    hist = ResourceHistory(
        resource_ulid=r_ulid,
        section="resource:capability:v1",
        version=1,
        data_json=_flatten_caps_json(caps),
        created_by_actor=None,
    )
    if hasattr(hist, "created_at_utc"): hist.created_at_utc = now
    if hasattr(hist, "updated_at_utc"): hist.updated_at_utc = now
    db.session.add(hist)

    for key, active in caps.items():
        idx = ResourceCapabilityIndex(
            resource_ulid=r_ulid,
            domain=_infer_domain(key),
            key=key,
            active=bool(active),
        )
        if hasattr(idx, "created_at_utc"): idx.created_at_utc = now
        if hasattr(idx, "updated_at_utc"): idx.updated_at_utc = now
        db.session.add(idx)

    db.session.commit()
    return SeedResourceResult(entity_ulid=e_ulid, resource_ulid=r_ulid, code=code)

def seed_sponsor_with_policy(
    *,
    code: str = "spon-dev-001",
    name: str = "Sample Dev Sponsor",
    readiness_status: str = "active",
    mou_status: str = "active",
    constraints: Optional[Dict[str, Any]] = None,  # e.g. {"local_only": True}
    caps: Optional[Dict[str, int]] = None,         # e.g. {"total_cents": 40000, "food_cap_cents": 5000}
    pledge_summary: Optional[Iterable[Dict[str, Any]]] = None,
    entity_ulid: Optional[str] = None,
) -> SeedSponsorResult:
    e_ulid = _ensure_org_entity(entity_ulid=entity_ulid, org_name=name)
    now = _iso_now()
    s_ulid = new_ulid()

    s = Sponsor(
        ulid=s_ulid,
        entity_ulid=e_ulid,
        admin_review_required=False,
        readiness_status=readiness_status,
        mou_status=mou_status,
        first_seen_utc=now,
        last_touch_utc=now,
        capability_last_update_utc=now,
        pledge_last_update_utc=now,
    )
    if hasattr(s, "created_at_utc"): s.created_at_utc = now
    if hasattr(s, "updated_at_utc"): s.updated_at_utc = now
    db.session.add(s)
    db.session.flush()

    if constraints:
        hist = SponsorHistory(
            sponsor_ulid=s_ulid,
            section="sponsor:capability:v1",
            version=1,
            data_json=_flatten_caps_json({k: bool(v) for k, v in constraints.items()}),
            created_by_actor=None,
        )
        if hasattr(hist, "created_at_utc"): hist.created_at_utc = now
        if hasattr(hist, "updated_at_utc"): hist.updated_at_utc = now
        db.session.add(hist)

        for key, active in constraints.items():
            idx = SponsorCapabilityIndex(
                sponsor_ulid=s_ulid,
                domain=_infer_domain(key),
                key=key,
                active=bool(active),
            )
            if hasattr(idx, "created_at_utc"): idx.created_at_utc = now
            if hasattr(idx, "updated_at_utc"): idx.updated_at_utc = now
            db.session.add(idx)

    for p in pledge_summary or ():
        pl = SponsorPledgeIndex(
            sponsor_ulid=s_ulid,
            pledge_ulid=p.get("pledge_ulid", new_ulid()),
            type=p.get("type", "cash"),
            status=p.get("status", "active"),
            has_restriction=bool(p.get("has_restriction", False)),
            est_value_number=p.get("est_value_number"),
            currency=p.get("currency"),
        )
        if hasattr(pl, "created_at_utc"): pl.created_at_utc = now
        if hasattr(pl, "updated_at_utc"): pl.updated_at_utc = now
        db.session.add(pl)

    db.session.commit()
    return SeedSponsorResult(entity_ulid=e_ulid, sponsor_ulid=s_ulid, code=code)
