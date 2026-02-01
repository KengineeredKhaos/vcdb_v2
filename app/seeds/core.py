# app/seeds/core.py

"""
Dev seeding core helpers (NO commits here).

Design rules:
- Seed functions accept sess: Session | None = None and default to db.session.
- Core seed functions never commit; the CLI command owns the transaction boundary.
- Seed outputs are small DTOs so callsites don’t guess model attributes.
- Entity “surface” (primary contact + address) is seeded once per entity and is Faker-driven.
- This module is dev-only glue. It may import slice models for seeding, but it should NOT
  become business-logic canon.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from faker import Faker
from sqlalchemy.orm import Session

from app.extensions import db
from app.extensions.policies import load_policy_entity_roles, load_policy_rbac
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid

# Auth slice
from app.slices.auth.models import Role

# Entity slice
from app.slices.entity.models import (
    Entity,
    EntityAddress,
    EntityContact,
    EntityOrg,
    EntityPerson,
    EntityRole,
)

# Optional governance code table (some builds remove it)
try:
    from app.slices.governance.models import DomainRoleCode  # type: ignore
except Exception:  # pragma: no cover
    DomainRoleCode = None  # type: ignore

# Slice models
from app.slices.customers.models import Customer, CustomerEligibility
from app.slices.resources.models import Resource
from app.slices.sponsors.models import Sponsor

# -----------------
# Faker Setup
# -----------------


def make_faker(seed: int = 1337) -> Faker:
    """Create a deterministic Faker instance for seed routines."""
    f = Faker("en_US")
    Faker.seed(seed)
    f.seed_instance(seed)
    return f


# -----------------
# DTOs returned by seed helpers
# -----------------


@dataclass(frozen=True)
class SeedResourceResult:
    resource_entity_ulid: str
    entity_ulid: str


@dataclass(frozen=True)
class SeedSponsorResult:
    sponsor_entity_ulid: str
    entity_ulid: str


@dataclass(frozen=True)
class SeedCustomerResult:
    customer_ulid: str
    entity_ulid: str


# -----------------------------------------------------------------------------
# Code-table seeding from policy (NO commit)
# -----------------------------------------------------------------------------
def seed_policy_codes_no_commit(
    sess: Session | None = None,
) -> tuple[int, int]:
    """
    Seed policy-derived code tables (RBAC + domain role codes) without committing.
    Returns: (n_rbac_inserted, n_domain_inserted)
    """
    sess = sess or db.session
    n_rbac = seed_rbac_from_policy(sess)
    n_domain = seed_domain_from_policy(sess)
    return n_rbac, n_domain


def _model_code_attr(Model, *, preferred: str = "code") -> str:
    """Return the attribute name used for 'code' on a code-table model."""
    if hasattr(Model, preferred):
        return preferred
    if hasattr(Model, "name"):
        return "name"
    # last resort; will fail loudly on insert/query if wrong
    return preferred


def seed_rbac_from_policy(sess: Session) -> int:
    """Seed Auth Role rows from policy_rbac.json (idempotent)."""
    pol = load_policy_rbac() or {}
    codes = [
        str(x).strip()
        for x in (pol.get("rbac_roles") or [])
        if str(x).strip()
    ]

    key = _model_code_attr(Role, preferred="code")
    existing = {getattr(r, key) for r in sess.query(Role).all()}

    created = 0
    for code in codes:
        if code in existing:
            continue

        r = Role(**{key: code})
        # Optional columns across refactors
        if hasattr(r, "description"):
            r.description = None
        if hasattr(r, "is_active"):
            r.is_active = True

        sess.add(r)
        created += 1

    sess.flush()
    return created


def seed_domain_from_policy(sess: Session) -> int:
    """
    Seed domain role codes from policy_entity_roles.json.

    If you have a DomainRoleCode table, we seed it idempotently.
    If you do NOT, we return 0 (domain roles remain policy-only).
    """
    pol = load_policy_entity_roles() or {}
    domain_roles = [
        str(x).strip()
        for x in (pol.get("domain_roles") or [])
        if str(x).strip()
    ]

    if DomainRoleCode is None:
        return 0

    key = _model_code_attr(DomainRoleCode, preferred="code")
    existing = {getattr(r, key) for r in sess.query(DomainRoleCode).all()}

    created = 0
    for code in domain_roles:
        if code in existing:
            continue

        row = DomainRoleCode(**{key: code})
        if hasattr(row, "label"):
            row.label = code
        if hasattr(row, "is_active"):
            row.is_active = True

        sess.add(row)
        created += 1

    sess.flush()
    return created


# -----------------------------------------------------------------------------
# Entity helpers
# -----------------------------------------------------------------------------
def _ensure_entity_role(
    sess: Session, *, entity_ulid: str, role: str
) -> None:
    role = (role or "").strip().lower()
    if not role:
        return

    exists = (
        sess.query(EntityRole)
        .filter(
            EntityRole.entity_ulid == entity_ulid, EntityRole.role == role
        )
        .one_or_none()
    )
    if exists:
        return

    ts = now_iso8601_ms()
    sess.add(
        EntityRole(
            entity_ulid=entity_ulid,
            role=role,
            created_at_utc=ts,
            updated_at_utc=ts,
        )
    )


def seed_entity_surface_fake(
    sess: Session, *, entity_ulid: str, faker=None
) -> None:
    """
    Ensure the entity has:
      - exactly one primary EntityContact (email + phone if faker provided)
      - at least one EntityAddress (physical)
    Creates rows only if missing.
    """
    # Critical: make sure Entity row is persistent before we sess.get()
    sess.flush()

    ts = now_iso8601_ms()
    ent = sess.get(Entity, entity_ulid)
    if ent is None:
        raise RuntimeError(f"Entity {entity_ulid} not found for surface seed")

    # Contacts (ensure one primary)
    has_primary = (
        sess.query(EntityContact)
        .filter(
            EntityContact.entity_ulid == entity_ulid,
            EntityContact.is_primary.is_(True),
        )
        .count()
        > 0
    )
    if not has_primary:
        if faker:
            email = faker.email()
            phone = faker.phone_number()
        else:
            email = f"seed-{entity_ulid[:8]}@example.test"
            phone = "555-0100"

        sess.add(
            EntityContact(
                entity_ulid=entity_ulid,
                email=email,
                phone=phone,
                is_primary=True,
                created_at_utc=ts,
                updated_at_utc=ts,
            )
        )

    # Address (ensure at least one)
    has_address = (
        sess.query(EntityAddress)
        .filter(EntityAddress.entity_ulid == entity_ulid)
        .count()
        > 0
    )
    if not has_address:
        if faker:
            address1 = faker.street_address()
            city = faker.city()
            state = (
                faker.state_abbr() if hasattr(faker, "state_abbr") else "CA"
            )
            state = (state or "CA").strip().upper()[:2]
            postal = str(faker.postcode())[:10]
        else:
            address1 = "123 Seed St"
            city = "Seedville"
            state = "CA"
            postal = "99999"

        sess.add(
            EntityAddress(
                entity_ulid=entity_ulid,
                is_physical=True,
                is_postal=False,
                address1=address1,
                address2=None,
                city=city,
                state=state,
                postal_code=postal,
                created_at_utc=ts,
                updated_at_utc=ts,
            )
        )


def _ensure_org_entity(
    sess: Session,
    *,
    org_name: str,
    faker=None,
    role: Optional[str] = None,
) -> str:
    """
    Idempotent-ish by legal_name for dev convenience.
    Returns entity_ulid.
    """
    org_name = (org_name or "").strip()
    if not org_name:
        raise RuntimeError("org_name is required")

    existing = (
        sess.query(EntityOrg)
        .filter(EntityOrg.legal_name == org_name)
        .one_or_none()
    )
    if existing:
        if role:
            _ensure_entity_role(
                sess, entity_ulid=existing.entity_ulid, role=role
            )
        seed_entity_surface_fake(
            sess, entity_ulid=existing.entity_ulid, faker=faker
        )
        sess.flush()
        return existing.entity_ulid

    ts = now_iso8601_ms()
    e_ulid = new_ulid()

    sess.add(
        Entity(ulid=e_ulid, kind="org", created_at_utc=ts, updated_at_utc=ts)
    )
    sess.add(
        EntityOrg(
            entity_ulid=e_ulid,
            legal_name=org_name,
            dba_name=None,
            ein=None,
            created_at_utc=ts,
            updated_at_utc=ts,
        )
    )

    if role:
        _ensure_entity_role(sess, entity_ulid=e_ulid, role=role)

    sess.flush()
    seed_entity_surface_fake(sess, entity_ulid=e_ulid, faker=faker)
    sess.flush()
    return e_ulid


def _create_person_entity(
    sess: Session,
    *,
    first: str,
    last: str,
    preferred: Optional[str] = None,
    faker=None,
    role: Optional[str] = None,
) -> str:
    ts = now_iso8601_ms()
    e_ulid = new_ulid()

    sess.add(
        Entity(
            ulid=e_ulid, kind="person", created_at_utc=ts, updated_at_utc=ts
        )
    )
    sess.add(
        EntityPerson(
            entity_ulid=e_ulid,
            first_name=first,
            last_name=last,
            preferred_name=preferred,
            created_at_utc=ts,
            updated_at_utc=ts,
        )
    )

    if role:
        _ensure_entity_role(sess, entity_ulid=e_ulid, role=role)

    sess.flush()
    seed_entity_surface_fake(sess, entity_ulid=e_ulid, faker=faker)
    sess.flush()
    return e_ulid


# -----------------------------------------------------------------------------
# Resource / Sponsor / POC seeds
# -----------------------------------------------------------------------------
def seed_active_resource(
    *,
    label: str,
    faker=None,
    sess: Session | None = None,
    readiness_status: str = "active",
    mou_status: str = "none",
) -> SeedResourceResult:
    """
    Create: Entity(org) + Resource row anchored by entity_ulid.
    Returns SeedResourceResult(resource_ulid, entity_ulid).
    """
    sess = sess or db.session
    ts = now_iso8601_ms()

    org_entity_ulid = _ensure_org_entity(
        sess, org_name=label, faker=faker, role="resource"
    )

    res = (
        sess.query(Resource)
        .filter(Resource.entity_ulid == org_entity_ulid)
        .one_or_none()
    )
    if res is None:
        res = Resource(entity_ulid=org_entity_ulid)
        # set common fields if they exist (survives model refactors)
        if hasattr(res, "readiness_status"):
            res.readiness_status = readiness_status
        if hasattr(res, "mou_status"):
            res.mou_status = mou_status
        if hasattr(res, "admin_review_required"):
            res.admin_review_required = False
        if hasattr(res, "first_seen_utc"):
            res.first_seen_utc = ts
        if hasattr(res, "last_touch_utc"):
            res.last_touch_utc = ts
        sess.add(res)
    else:
        if hasattr(res, "readiness_status"):
            res.readiness_status = readiness_status
        if hasattr(res, "last_touch_utc"):
            res.last_touch_utc = ts

    sess.flush()
    return SeedResourceResult(
        resource_entity_ulid=res.entity_ulid,
        entity_ulid=org_entity_ulid,
    )


def seed_sponsor_with_policy(
    *,
    label: str,
    faker=None,
    sess: Session | None = None,
    readiness_status: str = "active",
    mou_status: str = "none",
) -> SeedSponsorResult:
    """
    Create: Entity(org) + Sponsor row anchored by entity_ulid.
    Returns SeedSponsorResult(sponsor_ulid, entity_ulid).
    """
    sess = sess or db.session
    ts = now_iso8601_ms()

    org_entity_ulid = _ensure_org_entity(
        sess, org_name=label, faker=faker, role="sponsor"
    )

    sp = (
        sess.query(Sponsor)
        .filter(Sponsor.entity_ulid == org_entity_ulid)
        .one_or_none()
    )
    if sp is None:
        sp = Sponsor(entity_ulid=org_entity_ulid)
        if hasattr(sp, "readiness_status"):
            sp.readiness_status = readiness_status
        if hasattr(sp, "mou_status"):
            sp.mou_status = mou_status
        if hasattr(sp, "admin_review_required"):
            sp.admin_review_required = False
        if hasattr(sp, "first_seen_utc"):
            sp.first_seen_utc = ts
        if hasattr(sp, "last_touch_utc"):
            sp.last_touch_utc = ts
        sess.add(sp)
    else:
        if hasattr(sp, "readiness_status"):
            sp.readiness_status = readiness_status
        if hasattr(sp, "last_touch_utc"):
            sp.last_touch_utc = ts

    sess.flush()
    return SeedSponsorResult(
        sponsor_entity_ulid=sp.entity_ulid,
        entity_ulid=org_entity_ulid,
    )


def seed_org_poc_pair(
    sess: Session,
    *,
    org_entity_ulid: str,  # intentionally unused for now; keeps callsites obvious
    label: str,
    faker=None,
) -> list[str]:
    """
    Create two POC person entities (role='civilian').

    There is no direct Org<->Person table yet; linking is done by ResourcePOC/SponsorPOC.
    """
    _ = org_entity_ulid  # future-proofing

    ulids: list[str] = []
    for i in range(2):
        e_ulid = _create_person_entity(
            sess,
            first=f"{label} POC{i+1}",
            last="CIV",
            preferred=None,
            faker=faker,
            role="civilian",
        )
        ulids.append(e_ulid)
    return ulids


# -----------------------------------------------------------------------------
# Customer seed
# -----------------------------------------------------------------------------
def seed_minimal_customer(
    *,
    first: str,
    last: str,
    faker=None,
    sess: Session | None = None,
) -> SeedCustomerResult:
    """
    Create:
      Entity(person) + EntityPerson + role='customer'
      Customer(status='active')
      CustomerEligibility with simple randomized fields
    """
    sess = sess or db.session
    ts = now_iso8601_ms()

    e_ulid = _create_person_entity(
        sess,
        first=first,
        last=last,
        preferred=None,
        faker=faker,
        role="customer",
    )

    c = (
        sess.query(Customer)
        .filter(Customer.entity_ulid == e_ulid)
        .one_or_none()
    )
    if c is None:
        c = Customer(entity_ulid=e_ulid)
        if hasattr(c, "status"):
            c.status = "active"
        if hasattr(c, "created_at_utc"):
            c.created_at_utc = ts
        if hasattr(c, "updated_at_utc"):
            c.updated_at_utc = ts
        sess.add(c)
    else:
        if hasattr(c, "status"):
            c.status = "active"
        if hasattr(c, "updated_at_utc"):
            c.updated_at_utc = ts

    sess.flush()

    elig = (
        sess.query(CustomerEligibility)
        .filter(CustomerEligibility.customer_ulid == c.ulid)
        .one_or_none()
    )
    if elig is None:
        elig = CustomerEligibility(customer_ulid=c.ulid)
        # --- Veteran verification (must satisfy CHECKs) ---
        verified = bool(random.getrandbits(1))
        if hasattr(elig, "is_veteran_verified"):
            elig.is_veteran_verified = verified

        if verified:
            # ck_ce_verified_requires_method
            if hasattr(elig, "veteran_method"):
                method = random.choice(
                    ["dd214", "va_id", "state_dl_veteran", "other"]
                )
                elig.veteran_method = method

                # ck_ce_other_requires_approval + ck_ce_approval_requires_timestamp
                if method == "other":
                    if hasattr(elig, "approved_by_ulid"):
                        elig.approved_by_ulid = new_ulid()
                    if hasattr(elig, "approved_at_utc"):
                        elig.approved_at_utc = ts
        else:
            # ck_ce_unverified_requires_nulls
            if hasattr(elig, "veteran_method"):
                elig.veteran_method = None
            if hasattr(elig, "approved_by_ulid"):
                elig.approved_by_ulid = None
            if hasattr(elig, "approved_at_utc"):
                elig.approved_at_utc = None

        # --- Needs tiers (fine as-is) ---
        if hasattr(elig, "tier1_min"):
            elig.tier1_min = int(random.choice([1, 2, 3]))
        if hasattr(elig, "tier2_min"):
            elig.tier2_min = int(random.choice([1, 2, 3]))
        if hasattr(elig, "tier3_min"):
            elig.tier3_min = int(random.choice([1, 2, 3]))

        if hasattr(elig, "created_at_utc"):
            elig.created_at_utc = ts
        if hasattr(elig, "updated_at_utc"):
            elig.updated_at_utc = ts

        sess.add(elig)

    sess.flush()
    return SeedCustomerResult(customer_ulid=c.ulid, entity_ulid=e_ulid)
