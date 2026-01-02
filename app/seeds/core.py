# app/seeds/core.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.extensions import db
from app.extensions.policies import (
    load_policy_entity_roles,
    load_policy_rbac,
)
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid

# Adjust these to your actual model names
from app.slices.auth.models import Role  # table: auth_role
from app.slices.customers.models import Customer
from app.slices.governance.models import RoleCode  # table: gov_domain_role

BASE = Path(__file__).resolve().parents[1]

# -------- Seed Role Codes ---------------


def _load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def seed_rbac_from_policy() -> int:
    """Idempotently seed RBAC role codes from auth policy JSON."""
    policy = load_policy_rbac()
    codes = policy.get("rbac_roles", []) or []
    count = 0
    for code in codes:
        obj = Role.query.filter_by(code=code).one_or_none()
        if not obj:
            db.session.add(Role(code=code))
            count += 1
    db.session.commit()
    return count


def seed_domain_from_policy() -> int:
    """Idempotently seed Domain role codes from governance policy JSON (v2)."""
    policy = load_policy_entity_roles()

    raw = policy.get("domain_roles", []) or []
    codes: list[str] = []
    for r in raw:
        if isinstance(r, str):
            codes.append(r)
        elif isinstance(r, dict) and isinstance(r.get("code"), str):
            codes.append(r["code"])

    count = 0
    for code in codes:
        obj = RoleCode.query.filter_by(code=code).one_or_none()
        if not obj:
            db.session.add(RoleCode(code=code))
            count += 1
    db.session.commit()
    return count


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

    return json.dumps(
        {k: {"has": bool(v)} for k, v in (d or {}).items()},
        ensure_ascii=False,
    )


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


def _apply_org_label(entity_org_obj, label: str) -> None:
    for attr in ("name", "display_name", "legal_name", "org_name"):
        if hasattr(entity_org_obj, attr):
            setattr(entity_org_obj, attr, label)
            return
    raise RuntimeError(
        "EntityOrg has no recognizable name column (tried: name, display_name, legal_name, org_name)."
    )


def _ensure_org_entity(*, entity_ulid: str | None, org_name: str) -> str:
    """
    Ensure an Entity(kind='org') with an EntityOrg row exists.
    Returns the entity ULID.
    """
    ts = now_iso8601_ms()
    ent = None
    if entity_ulid:
        # try to load existing entity
        ent = db.session.get(Entity, entity_ulid)
    if ent is None:
        ent = Entity(kind="org", created_at_utc=ts, updated_at_utc=ts)
        db.session.add(ent)
        db.session.flush()  # ent.ulid available
    # ensure org row is present & labeled
    if ent.org is None:
        ent.org = EntityOrg(created_at_utc=ts, updated_at_utc=ts)
    _apply_org_label(ent.org, org_name)
    db.session.flush()
    return ent.ulid


def seed_minimal_customer(
    *, first: str, last: str, preferred: str | None = None
) -> dict:
    """
    Minimal happy-path customer: create Entity(kind='person') + EntityPerson,
    then Customer referencing that Entity. No commit here.
    """
    ts = now_iso8601_ms()

    # Parent: Entity(kind='person') with person row
    ent = Entity(kind="person", created_at_utc=ts, updated_at_utc=ts)
    # attach related person via relationship (preferred) so FK wiring is automatic
    ent.person = EntityPerson(
        first_name=first,
        last_name=last,
        preferred_name=preferred,
        created_at_utc=ts,
        updated_at_utc=ts,
    )
    db.session.add(ent)
    db.session.flush()  # ent.ulid assigned here

    # Child: Customer referencing real parent ULID
    cust = Customer(
        entity_ulid=ent.ulid,
        status="active",
        created_at_utc=ts,
        updated_at_utc=ts,
    )
    db.session.add(cust)
    db.session.flush()  # cust.ulid assigned here

    # no commit here — caller owns transaction
    return {"entity_ulid": ent.ulid, "customer_ulid": cust.ulid}


def seed_active_resource(
    *,
    code: str = "res-dev-001",
    label: str = "Sample Dev Resource",
    capabilities: Optional[Dict[str, bool]] = None,
    readiness_status: str = "active",  # draft|review|active|suspended
    mou_status: str = "active",  # none|pending|active|expired|terminated
    entity_ulid: Optional[str] = None,
) -> SeedResourceResult:
    caps = capabilities or {
        "housing": True,
        "furniture": True,
        "barber": False,
    }
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
    if hasattr(r, "created_at_utc"):
        r.created_at_utc = now
    if hasattr(r, "updated_at_utc"):
        r.updated_at_utc = now
    db.session.add(r)
    db.session.flush()

    hist = ResourceHistory(
        resource_ulid=r_ulid,
        section="resource:capability:v1",
        version=1,
        data_json=_flatten_caps_json(caps),
        created_by_actor=None,
    )
    if hasattr(hist, "created_at_utc"):
        hist.created_at_utc = now
    if hasattr(hist, "updated_at_utc"):
        hist.updated_at_utc = now
    db.session.add(hist)

    for key, active in caps.items():
        idx = ResourceCapabilityIndex(
            resource_ulid=r_ulid,
            domain=_infer_domain(key),
            key=key,
            active=bool(active),
        )
        if hasattr(idx, "created_at_utc"):
            idx.created_at_utc = now
        if hasattr(idx, "updated_at_utc"):
            idx.updated_at_utc = now
        db.session.add(idx)

    db.session.commit()
    return SeedResourceResult(
        entity_ulid=e_ulid, resource_ulid=r_ulid, code=code
    )


def seed_sponsor_with_policy(
    *,
    code: str = "spon-dev-001",
    name: str = "Sample Dev Sponsor",
    readiness_status: str = "active",
    mou_status: str = "active",
    constraints: Optional[Dict[str, Any]] = None,  # e.g. {"local_only": True}
    caps: Optional[
        Dict[str, int]
    ] = None,  # e.g. {"total_cents": 40000, "food_cap_cents": 5000}
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
    if hasattr(s, "created_at_utc"):
        s.created_at_utc = now
    if hasattr(s, "updated_at_utc"):
        s.updated_at_utc = now
    db.session.add(s)
    db.session.flush()

    if constraints:
        hist = SponsorHistory(
            sponsor_ulid=s_ulid,
            section="sponsor:capability:v1",
            version=1,
            data_json=_flatten_caps_json(
                {k: bool(v) for k, v in constraints.items()}
            ),
            created_by_actor=None,
        )
        if hasattr(hist, "created_at_utc"):
            hist.created_at_utc = now
        if hasattr(hist, "updated_at_utc"):
            hist.updated_at_utc = now
        db.session.add(hist)

        for key, active in constraints.items():
            idx = SponsorCapabilityIndex(
                sponsor_ulid=s_ulid,
                domain=_infer_domain(key),
                key=key,
                active=bool(active),
            )
            if hasattr(idx, "created_at_utc"):
                idx.created_at_utc = now
            if hasattr(idx, "updated_at_utc"):
                idx.updated_at_utc = now
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
        if hasattr(pl, "created_at_utc"):
            pl.created_at_utc = now
        if hasattr(pl, "updated_at_utc"):
            pl.updated_at_utc = now
        db.session.add(pl)

    # DO NOT COMMIT HERE — caller (CLI/tests) owns the transaction boundary
    return SeedSponsorResult(
        entity_ulid=e_ulid, sponsor_ulid=s_ulid, code=code
    )
