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

from faker import Faker
from sqlalchemy import select
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
from app.slices.logistics.models import InventoryStock
from app.slices.logistics.sku import parse_sku

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
    customer_entity_ulid: str
    entity_ulid: str


@dataclass(frozen=True)
class SeedLogisticsResult:
    location_count: int
    sku_count: int
    stocked_pairs_count: int


@dataclass(frozen=True)
class SeedFinanceResult:
    account_count: int
    fund_count: int
    open_period_count: int


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
        str(row.get("code") or "").strip().lower()
        for row in (pol.get("rbac_roles") or [])
        if isinstance(row, dict) and str(row.get("code") or "").strip()
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
    role: str | None = None,
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
    preferred: str | None = None,
    faker=None,
    role: str | None = None,
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
        resource_entity_ulid=res.entity_ulid, entity_ulid=org_entity_ulid
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
        sponsor_entity_ulid=sp.entity_ulid, entity_ulid=org_entity_ulid
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
            first=f"{label} POC{i + 1}",
            last="CIV",
            preferred=None,
            faker=faker,
            role="civilian",
        )
        ulids.append(e_ulid)
    return ulids


# -----------------------------------------------------------------------------
# Finance seed
# -----------------------------------------------------------------------------
_FINANCE_BASELINE_FUNDS = (
    (
        "unrestricted",
        "Unrestricted Operating Fund",
        "unrestricted",
    ),
    (
        "temporarily_restricted",
        "Temporarily Restricted Fund",
        "temporarily_restricted",
    ),
    (
        "ops_float",
        "Ops Float / Bridge Support",
        "unrestricted",
    ),
)


def seed_finance_baseline(
    *,
    sess: Session | None = None,
) -> SeedFinanceResult:
    """
    Seed Finance reference data without committing.

    Canon note for Future Dev:
      This creates reference data only. It must not create Journal,
      JournalLine, FinancePostingFact, BalanceMonthly, Reserve,
      Encumbrance, or OpsFloat rows.

      Money facts must enter Finance through the normal posting services
      so request_id, funding_demand_ulid, idempotency_key, Ledger events,
      and later integrity scans all tell the same story.
    """
    sess = sess or db.session

    # Late imports keep the seed package resilient during slice refactors.
    from app.slices.finance.models import Account, Fund, Period
    from app.slices.finance.services_journal import (
        ensure_default_accounts,
        ensure_fund,
    )

    ensure_default_accounts()

    for code, name, restriction in _FINANCE_BASELINE_FUNDS:
        ensure_fund(
            code=code,
            name=name,
            restriction=restriction,
        )

    current_period = now_iso8601_ms()[:7]
    period = sess.execute(
        select(Period).where(Period.period_key == current_period)
    ).scalar_one_or_none()
    if period is None:
        period = Period(period_key=current_period, status="open")
        sess.add(period)
    elif period.status == "closed":
        period.status = "soft_closed"

    sess.flush()
    return SeedFinanceResult(
        account_count=sess.query(Account).count(),
        fund_count=sess.query(Fund).count(),
        open_period_count=sess.query(Period).count(),
    )


# -----------------------------------------------------------------------------
# Logistics seed
# -----------------------------------------------------------------------------
_LOGISTICS_BASELINE_LOCATIONS = (
    ("MAIN", "Main Warehouse"),
    ("MOBILE", "Mobile Outreach Unit"),
    ("SATELLITE_1", "Satellite Closet 1"),
)

_LOGISTICS_BASELINE_ITEMS = (
    {
        "category": "undergarments",
        "name": "Socks — Small (White)",
        "unit": "each",
        "condition": "new",
        "sku": "UW-SK-LC-S-WT-U-001",
    },
    {
        "category": "undergarments",
        "name": "Socks — Medium (White)",
        "unit": "each",
        "condition": "new",
        "sku": "UW-SK-LC-M-WT-U-002",
    },
    {
        "category": "undergarments",
        "name": "Socks — Large (White)",
        "unit": "each",
        "condition": "new",
        "sku": "UW-SK-LC-L-WT-U-003",
    },
    {
        "category": "clothing",
        "name": "Uniform Top — Medium (Black, Veteran)",
        "unit": "each",
        "condition": "new",
        "sku": "UW-TP-LC-M-BK-V-001",
    },
    {
        "category": "clothing",
        "name": "Uniform Top — Large (Black, Veteran)",
        "unit": "each",
        "condition": "new",
        "sku": "UW-TP-LC-L-BK-V-002",
    },
    {
        "category": "clothing",
        "name": "Uniform Bottom — Medium (Blue)",
        "unit": "each",
        "condition": "new",
        "sku": "UW-BT-LC-M-BL-U-001",
    },
    {
        "category": "clothing",
        "name": "Uniform Bottom — Large (Blue)",
        "unit": "each",
        "condition": "new",
        "sku": "UW-BT-LC-L-BL-U-002",
    },
    {
        "category": "cold-weather",
        "name": "Gloves — Medium (Black)",
        "unit": "each",
        "condition": "new",
        "sku": "CW-GL-LC-M-BK-U-001",
    },
    {
        "category": "cold-weather",
        "name": "Winter Hat (Black)",
        "unit": "each",
        "condition": "new",
        "sku": "CW-HT-LC-NA-BK-U-001",
    },
    {
        "category": "camping",
        "name": "Sleeping Bag (Green, Unhoused)",
        "unit": "each",
        "condition": "new",
        "sku": "CG-SL-LC-NA-GN-H-001",
    },
    {
        "category": "accouterments",
        "name": "Hygiene Kit",
        "unit": "kit",
        "condition": "new",
        "sku": "AC-KT-LC-NA-MX-U-001",
    },
    {
        "category": "foodstuffs",
        "name": "Meal Kit",
        "unit": "kit",
        "condition": "new",
        "sku": "FD-KT-LC-NA-MX-U-001",
    },
)


def _baseline_location_targets(
    *,
    rng: random.Random,
    sku_codes: list[str],
) -> dict[str, set[str]]:
    placements = {sku: {"MAIN"} for sku in sku_codes}
    mobile_codes: tuple[str, ...] = ("MOBILE", "SATELLITE_1")

    for sku in sku_codes:
        for code in mobile_codes:
            if rng.random() < 0.55:
                placements[sku].add(code)
        if placements[sku] == {"MAIN"} and rng.random() < 0.60:
            placements[sku].add(rng.choice(mobile_codes))

    for code in mobile_codes:
        while sum(code in rows for rows in placements.values()) < 5:
            placements[rng.choice(sku_codes)].add(code)

    return placements


def _baseline_target_qty(
    *,
    rng: random.Random,
    location_code: str,
    unit: str,
) -> int:
    if unit == "kit":
        ranges = {
            "MAIN": (4, 10),
            "MOBILE": (2, 6),
            "SATELLITE_1": (1, 4),
        }
    else:
        ranges = {
            "MAIN": (8, 20),
            "MOBILE": (3, 9),
            "SATELLITE_1": (2, 8),
        }
    low, high = ranges[location_code]
    return rng.randint(low, high)


def seed_logistics_baseline(
    *,
    sess: Session | None = None,
    random_seed: int = 1337,
) -> SeedLogisticsResult:
    """
    Seed a small, customer-facing Logistics baseline.

    The catalog is fixed for repeatability. Location placement and stock
    targets are deterministic from random_seed so fresh rebuilds feel real
    without drifting into a giant catalog.
    """
    sess = sess or db.session

    # Late import keeps app boot resilient during slice refactors.
    from app.slices.logistics import services as logi_svc

    rng = random.Random(random_seed)
    received_at_utc = now_iso8601_ms()

    location_ulids: dict[str, str] = {}
    for code, name in _LOGISTICS_BASELINE_LOCATIONS:
        location_ulids[code] = logi_svc.ensure_location(
            code=code,
            name=name,
        )

    item_ulids: dict[str, str] = {}
    for row in _LOGISTICS_BASELINE_ITEMS:
        item_ulids[row["sku"]] = logi_svc.ensure_item(
            category=row["category"],
            name=row["name"],
            unit=row["unit"],
            condition=row["condition"],
            sku=row["sku"],
        )

    sku_codes = [row["sku"] for row in _LOGISTICS_BASELINE_ITEMS]
    placements = _baseline_location_targets(rng=rng, sku_codes=sku_codes)

    stocked_pairs = 0
    for row in _LOGISTICS_BASELINE_ITEMS:
        sku = row["sku"]
        parts = parse_sku(sku)
        item_ulid = item_ulids[sku]

        for location_code in sorted(placements[sku]):
            location_ulid = location_ulids[location_code]
            target_qty = _baseline_target_qty(
                rng=rng,
                location_code=location_code,
                unit=row["unit"],
            )
            stock_row = sess.execute(
                select(InventoryStock).where(
                    InventoryStock.item_ulid == item_ulid,
                    InventoryStock.location_ulid == location_ulid,
                )
            ).scalar_one_or_none()
            current_qty = int(stock_row.quantity) if stock_row else 0
            delta = target_qty - current_qty
            if delta > 0:
                logi_svc.receive_inventory(
                    item_ulid=item_ulid,
                    quantity=delta,
                    unit=row["unit"],
                    source=parts["src"],
                    received_at_utc=received_at_utc,
                    location_ulid=location_ulid,
                    note="seed bootstrap baseline",
                    actor_ulid=None,
                    source_entity_ulid=None,
                )
            stocked_pairs += 1

    sess.flush()
    return SeedLogisticsResult(
        location_count=len(_LOGISTICS_BASELINE_LOCATIONS),
        sku_count=len(_LOGISTICS_BASELINE_ITEMS),
        stocked_pairs_count=stocked_pairs,
    )


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
        .filter(CustomerEligibility.entity_ulid == c.entity_ulid)
        .one_or_none()
    )
    if elig is None:
        elig = CustomerEligibility(entity_ulid=c.entity_ulid)
        # --- Veteran verification (must satisfy CHECKs) ---
        verified = bool(random.getrandbits(1))

        # Model uses veteran_status string (default='unknown'),
        # not is_veteran_verified
        if hasattr(elig, "veteran_status"):
            elig.veteran_status = "verified" if verified else "unverified"

        if verified:
            if hasattr(elig, "veteran_method"):
                method = random.choice(
                    ["dd214", "va_id", "state_dl_veteran", "other"]
                )
                elig.veteran_method = method

                # Optional: branch/era only when verified
                # (keeps data semantically tidy)
                if hasattr(elig, "branch"):
                    elig.branch = random.choice(
                        ["USA", "USMC", "USN", "USAF", "USSF", "USCG"]
                    )
                if hasattr(elig, "era"):
                    elig.era = random.choice(
                        [
                            "WWI",
                            "WWII",
                            "Korea",
                            "Vietnam",
                            "ColdWar",
                            "GW-IF-EF",
                            "PsyWar",
                        ]
                    )

                if method == "other":
                    if hasattr(elig, "approved_by_ulid"):
                        elig.approved_by_ulid = new_ulid()
                    if hasattr(
                        elig, "approved_at_iso"
                    ):  # <-- correct column name
                        elig.approved_at_iso = ts
        else:
            # ck_cel_unverified_requires_nulls
            if hasattr(elig, "veteran_method"):
                elig.veteran_method = None
            if hasattr(elig, "approved_by_ulid"):
                elig.approved_by_ulid = None
            if hasattr(elig, "approved_at_iso"):
                elig.approved_at_iso = None
            if hasattr(elig, "branch"):
                elig.branch = None
            if hasattr(elig, "era"):
                elig.era = None

        # Homeless status is its own enum; safe default is "unknown" or randomize
        if hasattr(elig, "homeless_status"):
            elig.homeless_status = random.choice(
                ["unknown", "unverified", "verified"]
            )

    sess.flush()
    return SeedCustomerResult(
        customer_entity_ulid=c.entity_ulid, entity_ulid=e_ulid
    )
