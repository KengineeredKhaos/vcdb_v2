# app/cli_seed.py

"""
Dev-only CLI seed commands for VCDB v2.

These commands hang off the ``seed`` Click group that is wired in
``manage_vcdb.py``. They exist to turn a blank / freshly-migrated dev
database into a predictable playground for development, manual testing,
and demos.

Fresh dev DB recipe:

    rm -f var/app-instance/dev.db
    flask --app manage_vcdb.py db upgrade
    flask --app manage_vcdb.py seed seed-foundation
    # optional extras:
    # flask --app manage_vcdb.py seed seed-smoke
    # flask --app manage_vcdb.py seed seed-logistics-canonical


Typical usage from the project root::

    # Fresh dev DB
    flask --app manage_vcdb.py db upgrade
    flask --app manage_vcdb.py seed seed-foundation

    # Minimal smoke data
    flask --app manage_vcdb.py seed seed-smoke

    # (If present) one-shot kitchen-sink bootstrap
    flask --app manage_vcdb.py seed bootstrap


Commands (core)
===============

seed-role-codes
    - Reads governance policy JSON and seeds:
        * RBAC roles (Auth slice)
        * Domain roles (Governance slice)
    - Idempotent: safe to run multiple times; it will only add missing codes.

seed-foundation
    - One-stop “full playground” seed for a *fresh* dev database.
    - Creates:
        * N Resource orgs: ``"Resource Org 1..N"``
            - Each has a Resource record plus two POC people wired via
              ResourcePOC rows (primary / backup).
        * N Sponsor orgs: ``"Sponsor Org 1..N"``
            - Each has a Sponsor record plus two POC people wired via
              SponsorPOC rows (primary / backup).
        * M test customers: ``"Test User1..M"``.
    - Intended flow after nuking ``dev.db``::

        flask --app manage_vcdb.py db upgrade
        flask --app manage_vcdb.py seed seed-foundation

seed-smoke
    - Minimal “smoke test” dataset for manual UI/API poking.
    - Creates:
        * RBAC + domain role codes from policy (if not already present).
        * One Resource org: ``"Smoke Resource"`` + 2 POCs (ResourcePOC rows).
        * One Sponsor org: ``"Smoke Sponsor"`` + 2 POCs (SponsorPOC rows).
        * One customer: ``"Smoke User"``.


Commands (optional / demo)
==========================

Depending on what is currently wired, additional commands may include:

seed-logistics-canonical
    - Seeds a canonical set of non-kit Logistics SKUs and stock at a
      configured location (e.g. ``LOC-MAIN``).
    - Intended to exercise SKU parsing, policy constraints, and stock
      listing / issuance flows.

seed-demo-customers
    - Creates a small, labeled set of Customer records that exercise
      Governance policy (veteran vs non-veteran, crisis tiers, etc.).
    - Prints ULIDs so devs can copy/paste into other tools or tests.

seed-demo-resources
    - Creates a couple of demo Resource orgs, attaches canonical
      capabilities, and drives them through readiness / MOU lifecycles.

seed-demo-sponsors
    - Creates demo Sponsor orgs, attaches funding capabilities, and
      (optionally) adds a sample pledge to drive Finance / Governance
      flows.

bootstrap
    - (If present) orchestrates a full dev bootstrap in one shot:
        * seed-role-codes
        * seed-foundation
        * seed-logistics-canonical
        * seed-demo-* as appropriate
    - Intended recipe for a brand-new ``dev.db``::

        flask --app manage_vcdb.py db upgrade
        flask --app manage_vcdb.py seed bootstrap


Implementation notes
====================

- All heavy lifting for creating Resources, Sponsors, Customers, etc. lives in
  ``app.seeds.core`` and the slice services. This module just orchestrates
  cross-slice wiring and exposes friendly Click commands.

- POC helpers:
    * ``_ensure_org_poc_pair`` creates two Entity+EntityPerson rows for a given
      org (POC1 / POC2).
    * ``_attach_resource_pocs`` and ``_attach_sponsor_pocs`` turn those into
      ResourcePOC / SponsorPOC linkage rows with correct foreign keys::

        resource_poc.resource_ulid      -> resource_resource.ulid
        resource_poc.person_entity_ulid -> entity_person.ulid
        resource_poc.org_entity_ulid    -> entity_org.ulid

        sponsor_poc.sponsor_ulid        -> sponsor_sponsor.ulid
        sponsor_poc.person_entity_ulid  -> entity_person.ulid
        sponsor_poc.org_entity_ulid     -> entity_org.ulid

- Transaction model:
    * Helper functions assume the caller owns the transaction and do **not**
      commit.
    * Top-level Click commands call ``db.session.commit()`` once at the end.
    * This keeps seeds simple and makes it easy to blow away ``dev.db`` and
      re-run the same commands without surprise side effects.

- Scope:
    * This file is intentionally dev-focused. If we ever need “real”
      production bootstrap data, that should live in a separate, explicitly
      documented path (and almost certainly **not** reuse these dev seeds).
    * When adding new seed commands, prefer:
        - Thin wrappers here that call into slice services / seeds.core.
        - Updating this docstring so the next maintainer can see the
          available entry points at a glance.
"""


from __future__ import annotations

import click

from app.cli import echo_db_banner
from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid

# Seeds API (you uploaded this)
from app.seeds.core import (
    seed_active_resource,
    seed_domain_from_policy,
    seed_minimal_customer,
    seed_rbac_from_policy,
    seed_sponsor_with_policy,
)

# Models for POCs (entity “person” attached to an org)
from app.slices.entity.models import Entity, EntityOrg, EntityPerson
from app.slices.resources.models import Resource, ResourcePOC
from app.slices.sponsors.models import Sponsor, SponsorPOC


# If you have a formal “POC” link model later, swap this helper accordingly.
def _ensure_org_poc_pair(*, org_entity_ulid: str, label: str) -> list[str]:
    """Create two civilian POCs (Entity(kind='person')) for the given org.
    Returns the created POC entity ULIDs. Later you can add a formal link if/when that model exists.
    """
    ulids: list[str] = []
    ts = now_iso8601_ms()
    for i in range(2):
        e_ulid = new_ulid()
        person = EntityPerson(
            entity_ulid=e_ulid,
            first_name=f"{label} POC{i+1}",
            last_name="CIV",
            preferred_name=None,
        )
        ent = Entity(ulid=e_ulid, kind="person")
        # IsoTimestamps are columns; set explicitly to avoid NULL on NOT NULL columns during tests
        if hasattr(ent, "created_at_utc"):
            ent.created_at_utc = ts
        if hasattr(ent, "updated_at_utc"):
            ent.updated_at_utc = ts
        if hasattr(person, "created_at_utc"):
            person.created_at_utc = ts
        if hasattr(person, "updated_at_utc"):
            person.updated_at_utc = ts

        db.session.add_all([ent, person])
        ulids.append(e_ulid)

        # If/when you add an Org↔POC association table, insert that row here.

    db.session.flush()
    return ulids


def _attach_resource_pocs(*, resource_ulid: str, label: str) -> None:
    """Create 2 POCs for a Resource org and attach them via ResourcePOC.

    - Uses the Resource row to find the org via entity_ulid.
    - Uses _ensure_org_poc_pair to create two Entity+EntityPerson POCs.
    - Inserts ResourcePOC rows that point at:
        * resource_resource.ulid
        * entity_person.ulid
        * entity_org.ulid
    """
    ts = now_iso8601_ms()

    # Load the Resource and its org (via entity_ulid -> EntityOrg.entity_ulid)
    resource = db.session.get(Resource, resource_ulid)
    if resource is None:
        raise RuntimeError(
            f"Resource {resource_ulid} not found when attaching POCs"
        )

    org = (
        db.session.query(EntityOrg)
        .filter_by(entity_ulid=resource.entity_ulid)
        .one()
    )

    # Create two POC people (returns ENTITY ULIDs, not person ULIDs)
    poc_entity_ulids = _ensure_org_poc_pair(
        org_entity_ulid=resource.entity_ulid,
        label=label,
    )

    # Map entity_ulid -> EntityPerson row, so we can get person.ulid
    persons = (
        db.session.query(EntityPerson)
        .filter(EntityPerson.entity_ulid.in_(poc_entity_ulids))
        .all()
    )
    person_by_entity = {p.entity_ulid: p for p in persons}

    for i, e_ulid in enumerate(poc_entity_ulids):
        person = person_by_entity[e_ulid]

        poc = ResourcePOC(
            resource_ulid=resource.ulid,  # FK -> resource_resource.ulid
            person_entity_ulid=person.ulid,  # FK -> entity_person.ulid
            org_entity_ulid=org.ulid,  # FK -> entity_org.ulid
            scope="primary" if i == 0 else "backup",
            org_role="poc",
            valid_from_utc=ts,
            valid_to_utc=None,
        )
        if hasattr(poc, "created_at_utc"):
            poc.created_at_utc = ts
        if hasattr(poc, "updated_at_utc"):
            poc.updated_at_utc = ts
        db.session.add(poc)


def _attach_sponsor_pocs(*, sponsor_ulid: str, label: str) -> None:
    """Create 2 POCs for a Sponsor org and attach them via SponsorPOC."""
    ts = now_iso8601_ms()

    sponsor = db.session.get(Sponsor, sponsor_ulid)
    if sponsor is None:
        raise RuntimeError(
            f"Sponsor {sponsor_ulid} not found when attaching POCs"
        )

    org = (
        db.session.query(EntityOrg)
        .filter_by(entity_ulid=sponsor.entity_ulid)
        .one()
    )

    poc_entity_ulids = _ensure_org_poc_pair(
        org_entity_ulid=sponsor.entity_ulid,
        label=label,
    )

    persons = (
        db.session.query(EntityPerson)
        .filter(EntityPerson.entity_ulid.in_(poc_entity_ulids))
        .all()
    )
    person_by_entity = {p.entity_ulid: p for p in persons}

    for i, e_ulid in enumerate(poc_entity_ulids):
        person = person_by_entity[e_ulid]

        poc = SponsorPOC(
            sponsor_ulid=sponsor.ulid,  # FK -> sponsor_sponsor.ulid
            person_entity_ulid=person.ulid,  # FK -> entity_person.ulid
            org_entity_ulid=org.ulid,  # FK -> entity_org.ulid
            scope="primary" if i == 0 else "backup",
            org_role="poc",
            valid_from_utc=ts,
            valid_to_utc=None,
        )
        if hasattr(poc, "created_at_utc"):
            poc.created_at_utc = ts
        if hasattr(poc, "updated_at_utc"):
            poc.updated_at_utc = ts
        db.session.add(poc)


@click.group("seed")
def seed_cmd() -> None:
    """Developer seeding utilities (idempotent where noted)."""
    pass


@seed_cmd.command("bootstrap")
@click.option("--customers", type=int, default=5, show_default=True)
@click.option("--resources", type=int, default=3, show_default=True)
@click.option("--sponsors", type=int, default=3, show_default=True)
@click.option("--skus", type=int, default=15, show_default=True)
@click.option("--per-sku", type=int, default=10, show_default=True)
def seed_bootstrap(
    customers: int,
    resources: int,
    sponsors: int,
    skus: int,
    per_sku: int,
):
    """
    One-shot dev bootstrap for a *blank* dev.db.

    Rough recipe this assumes:

        flask --app manage_vcdb.py db upgrade
        flask --app manage_vcdb.py seed bootstrap
    """
    echo_db_banner("seed-bootstrap")

    # 1) role codes
    seed_role_codes()

    # 2) core foundation (resources/sponsors/POCs/customers)
    seed_foundation(
        customers=customers,
        resources=resources,
        sponsors=sponsors,
    )

    # 3) canonical Logistics SKUs + stock
    seed_logistics_canonical(
        count=skus,
        per_sku=per_sku,
        loc_code="MAIN",
        loc_name="Main Warehouse",
    )

    # 4) demo customers/resources/sponsors for UI/demo flows
    seed_demo_customers(prefix="Demo")
    seed_demo_resources(prefix="DemoOrg")
    seed_demo_sponsors(prefix="DemoSponsor")

    click.echo("OK — dev bootstrap complete.")


@seed_cmd.command("seed-role-codes")
def seed_role_codes() -> None:
    """Seed RBAC & Domain role codes from policy JSON (idempotent)."""
    n_rbac = seed_rbac_from_policy()
    n_domain = seed_domain_from_policy()
    click.echo(
        f"RBAC: +{n_rbac} (idempotent); Domain: +{n_domain} (idempotent)"
    )


@seed_cmd.command("seed-foundation")
@click.option("--customers", type=int, default=5)
@click.option("--resources", type=int, default=3)
@click.option("--sponsors", type=int, default=3)
def seed_foundation(customers: int, resources: int, sponsors: int):
    """Seed a baseline set of Resources, Sponsors, POCs, and Customers.

    This is a dev-only seed: we keep it simple—
    one session, one explicit commit at the end.
    """
    echo_db_banner("seed-foundation")

    # Resources + POCs
    for i in range(resources):
        label = f"Resource Org {i+1}"
        res = seed_active_resource(label=label)
        _attach_resource_pocs(
            resource_ulid=res.resource_ulid,
            label=label,
        )

    # Sponsors + POCs
    for i in range(sponsors):
        label = f"Sponsor Org {i+1}"
        sres = seed_sponsor_with_policy(name=label)
        _attach_sponsor_pocs(
            sponsor_ulid=sres.sponsor_ulid,
            label=label,
        )

    # Customers
    for i in range(customers):
        seed_minimal_customer(first="Test", last=f"User{i+1}")

    # Single commit for everything
    db.session.commit()
    click.echo("OK — foundation seeded.")


@seed_cmd.command("seed-smoke")
def seed_smoke() -> None:
    echo_db_banner("seed-smoke")
    seed_rbac_from_policy()
    seed_domain_from_policy()

    # Resource + POCs
    r = seed_active_resource(label="Smoke Resource")
    _attach_resource_pocs(
        resource_ulid=r.resource_ulid,
        label="Smoke Resource",
    )

    # Sponsor + POCs
    s = seed_sponsor_with_policy(name="Smoke Sponsor")
    _attach_sponsor_pocs(
        sponsor_ulid=s.sponsor_ulid,
        label="Smoke Sponsor",
    )

    seed_minimal_customer(first="Smoke", last="User")
    db.session.commit()
    click.echo("Smoke seed OK")


@seed_cmd.command("seed-demo")
def seed_demo() -> None:
    """Seed the legacy demo dataset (if still present in app.seeds.demo)."""
    echo_db_banner("seed-demo")
    from app.seeds.demo import seed_demo_dataset

    seed_demo_dataset()
    click.echo("✓ demo data seeded")


@seed_cmd.command("seed-logistics-canonical")
@click.option(
    "--count",
    type=int,
    default=20,
    show_default=True,
    help="How many SKUs to generate.",
)
@click.option(
    "--per-sku",
    type=int,
    default=25,
    show_default=True,
    help="Units to receive per SKU.",
)
@click.option("--loc-code", default="MAIN", show_default=True)
@click.option("--loc-name", default="Main Warehouse", show_default=True)
@click.option(
    "--sources",
    default="DR,LC",
    show_default=True,
    help="Comma list of sources to use (DR, LC). Default: DR,LC",
)
def seed_logistics_canonical(
    count: int = 20,
    per_sku: int = 25,
    loc_code: str = "MAIN",
    loc_name: str = "Main Warehouse",
    sources: str = "DR,LC",
):
    """
    Seed a clean, predictable canonical set of SKUs (no kits),
    mostly issuance_class=U.
    """
    echo_db_banner("seed-logistics-canonical")
    import random

    from app.extensions import db
    from app.lib.chrono import now_iso8601_ms
    from app.slices.logistics.services import (
        ensure_item,
        ensure_location,
        receive_inventory,
    )
    from app.slices.logistics.sku import int_to_b36, parse_sku, validate_sku

    # canonical enums (non-kit)
    CATS = ["UW", "OW", "CW", "FW", "CG", "AC", "FD", "DG"]
    SUBS = ["TP", "BT", "SK", "GL", "HT", "BG", "SL", "SH"]  # exclude KT
    SRCS = [s.strip().upper() for s in sources.split(",") if s.strip()]
    SIZES = ["XS", "S", "M", "L", "XL", "2X", "3X", "NA"]
    COLORS = [
        "BK",
        "BL",
        "LB",
        "BR",
        "TN",
        "GN",
        "RD",
        "OR",
        "YL",
        "WT",
        "OD",
        "CY",
        "FG",
        "MC",
        "MX",
    ]
    # For LC we bias toward U; DR is forced to V by rule below
    CLASSES_LC = ["U", "U", "U", "V", "H", "D"]

    loc_ulid = ensure_location(code=loc_code, name=loc_name)

    # Also create a handful of rack/bin locations under MAIN that match
    # the Governance pattern ^MAIN-[A-F][1-3]-[1-3]$.
    rackbin_ulids: list[str] = []
    if loc_code == "MAIN":
        sections = ["A", "B", "C", "D", "E", "F"]
        for _ in range(5):
            sec = random.choice(sections)
            shelf = random.randint(1, 3)
            bin_no = random.randint(1, 3)
            code = f"MAIN-{sec}{shelf}-{bin_no}"
            rb_ulid = ensure_location(
                code=code, name=f"Rack {sec}{shelf} Bin {bin_no}"
            )
            rackbin_ulids.append(rb_ulid)

    made = 0
    attempts = 0
    max_attempts = count * 10  # safety to avoid infinite loop
    while made < count and attempts < max_attempts:
        attempts += 1
        cat = random.choice(CATS)
        sub = random.choice(SUBS)
        src = random.choice(SRCS) or "LC"
        size = random.choice(SIZES)
        col = random.choice(COLORS)
        # DRMO constraint: All DR items must be Veteran-only
        clazz = "V" if src == "DR" else random.choice(CLASSES_LC)
        seq = int_to_b36(made + 1, 3)

        sku = f"{cat}-{sub}-{src}-{size}-{col}-{clazz}-{seq}"
        if not validate_sku(sku):
            continue

        parts = parse_sku(sku)
        name = f"{cat}/{sub} {size} {col} ({clazz})"
        # Generate only items that satisfy SKU policy constraints
        try:
            item_ulid = ensure_item(
                category=f"{cat}/{sub}",
                name=name,
                unit="each",
                condition="new",
                sku=sku,
            )
        except ValueError:
            # e.g., assert_sku_constraints_ok rejected it; try another
            continue

        # Choose a target location: primary MAIN plus any rack/bin
        target_loc_ulid = loc_ulid
        if rackbin_ulids:
            target_loc_ulid = random.choice([loc_ulid] + rackbin_ulids)

        try:
            receive_inventory(
                item_ulid=item_ulid,
                quantity=per_sku,
                unit="each",
                source="donation",
                received_at_utc=now_iso8601_ms(),
                location_ulid=target_loc_ulid,
                note="seed:canonical",
                actor_ulid=None,
                source_entity_ulid=None,
            )

        except ValueError:
            # Extremely rare if unit/source constraints fire here
            continue
        made += 1

    db.session.commit()
    click.echo(
        f"OK — seeded {made} canonical SKUs at {loc_code} "
        f"(attempts={attempts}). Try: flask dev list-stock --location {loc_code}"
    )


@seed_cmd.command("seed-demo-customers")
@click.option(
    "--prefix",
    default="Demo",
    show_default=True,
    help="First/last name prefix for seed people.",
)
def seed_demo_customers(prefix: str):
    """
    Create a small, predictable set of Customer records for demos/tests
    (and exercise ledger emits). Prints the ULIDs so you can copy/paste.
    """
    echo_db_banner("seed-demo-customers")
    from app.extensions import db
    from app.extensions.contracts import customers_v2 as custx
    from app.extensions.contracts import governance_v2 as govx
    from app.lib.ids import new_ulid
    from app.slices.customers import services as cust_svc
    from app.slices.entity import services as ent_svc

    def _mk_person(label: str) -> str:
        rid = new_ulid()
        return ent_svc.ensure_person(
            first_name=f"{prefix}-{label}",
            last_name=f"{prefix}-{label}",
            email=None,
            phone=None,
            request_id=rid,
            actor_ulid=None,
        )

    def _mk_customer(label: str) -> str:
        ent_ulid = _mk_person(label)
        return cust_svc.ensure_customer(
            entity_ulid=ent_ulid,
            request_id=new_ulid(),
            actor_ulid=None,
        )

    out = {}

    # A) Veteran + Homeless (Tier1.housing=1)
    a = _mk_customer("A-VetHomeless")
    custx.verify_veteran(
        customer_ulid=a,
        method="va_id",
        verified=True,
        actor_ulid=None,
        actor_has_governor=True,
        request_id=new_ulid(),
    )
    custx.update_tier1(
        customer_ulid=a,
        payload={
            "food": 2,
            "hygiene": 2,
            "health": 2,
            "housing": 1,
            "clothing": 3,
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )
    govx.evaluate_customer(a, request_id=new_ulid(), actor_ulid=None)
    out["A_vet_homeless"] = a

    # B) Veteran only (no crisis)
    b = _mk_customer("B-VetOnly")
    custx.verify_veteran(
        customer_ulid=b,
        method="va_id",
        verified=True,
        actor_ulid=None,
        actor_has_governor=True,
        request_id=new_ulid(),
    )
    custx.update_tier1(
        customer_ulid=b,
        payload={
            "food": 2,
            "hygiene": 2,
            "health": 2,
            "housing": 2,
            "clothing": 3,
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )
    govx.evaluate_customer(b, request_id=new_ulid(), actor_ulid=None)
    out["B_vet_only"] = b

    # C) Non-veteran (baseline)
    c = _mk_customer("C-NonVet")
    custx.update_tier1(
        customer_ulid=c,
        payload={
            "food": 3,
            "hygiene": 3,
            "health": 2,
            "housing": 2,
            "clothing": 3,
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )
    govx.evaluate_customer(c, request_id=new_ulid(), actor_ulid=None)
    out["C_non_vet"] = c

    # D) Tier2 income crisis (watchlist)
    d = _mk_customer("D-IncomeCrisis")
    custx.update_tier1(
        customer_ulid=d,
        payload={
            "food": 2,
            "hygiene": 2,
            "health": 2,
            "housing": 2,
            "clothing": 3,
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )
    custx.update_tier2(
        customer_ulid=d,
        payload={
            "income": 1,
            "employment": 2,
            "transportation": 3,
            "education": 3,
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )
    govx.evaluate_customer(d, request_id=new_ulid(), actor_ulid=None)
    out["D_tier2_income_watchlist"] = d

    db.session.commit()

    click.echo("OK — seeded demo customers:")
    for k, v in out.items():
        click.echo(f"  {k:28s} → {v}")
    click.echo(
        "Tip: `flask dev tail-ledger --domain customers --n 20` to inspect events."
    )


@seed_cmd.command("seed-demo-resources")
@click.option("--prefix", default="DemoOrg", show_default=True)
def seed_demo_resources(prefix: str):
    """Seed a couple of resources with valid capabilities/readiness/MOU + ledger emits."""
    echo_db_banner("seed-demo-resources")
    import click

    from app.lib.ids import new_ulid
    from app.slices.entity import services as ent_svc
    from app.slices.resources import services as res_svc

    # Pull the canonical capability list and index it by domain prefix
    allowed = sorted(res_svc.allowed_capabilities())
    allowed_set = set(allowed)

    def pick(prefix: str, default: str | None = None) -> str | None:
        """Pick the first canonical key that starts with '<prefix>.' or return default."""
        pfx = prefix + "."
        for k in allowed:
            if k.startswith(pfx):
                return k
        return default

    def mk_org(label: str) -> str:
        rid = new_ulid()
        return ent_svc.ensure_org(
            legal_name=f"{prefix}-{label}",
            ein=None,
            request_id=rid,
            actor_ulid=None,
        )

    # Choose safe defaults that we know exist (if they do)
    food_key = (
        "basic_needs.food_pantry"
        if "basic_needs.food_pantry" in allowed_set
        else pick("basic_needs")
    )
    housing_key = (
        "housing.public_housing_coordination"
        if "housing.public_housing_coordination" in allowed_set
        else pick("housing")
    )
    counseling_key = pick("counseling_services")

    # A: Active, has two valid capabilities
    org_a = mk_org("A")
    res_a = res_svc.ensure_resource(
        entity_ulid=org_a,
        request_id=new_ulid(),
        actor_ulid=None,
    )
    payload_a = {}
    if food_key:
        payload_a[food_key] = {"has": True, "note": "walk-in ok"}
    if housing_key:
        payload_a[housing_key] = {"has": True, "note": "call ahead"}
    if payload_a:
        res_svc.upsert_capabilities(
            resource_ulid=res_a,
            payload=payload_a,
            request_id=new_ulid(),
            actor_ulid=None,
        )
    res_svc.set_readiness_status(
        resource_ulid=res_a,
        status="review",
        request_id=new_ulid(),
        actor_ulid=None,
    )
    res_svc.set_mou_status(
        resource_ulid=res_a,
        status="active",
        request_id=new_ulid(),
        actor_ulid=None,
    )
    res_svc.promote_readiness_if_clean(
        resource_ulid=res_a,
        request_id=new_ulid(),
        actor_ulid=None,
    )

    # B: Draft/Pending MOU, counseling if available (else food fallback)
    org_b = mk_org("B")
    res_b = res_svc.ensure_resource(
        entity_ulid=org_b,
        request_id=new_ulid(),
        actor_ulid=None,
    )
    payload_b = {}
    if counseling_key:
        payload_b[counseling_key] = {"has": True, "note": "Mon–Thu"}
    elif food_key:
        payload_b[food_key] = {"has": True, "note": "Mon–Thu"}

    if payload_b:
        res_svc.upsert_capabilities(
            resource_ulid=res_b,
            payload=payload_b,
            request_id=new_ulid(),
            actor_ulid=None,
        )
    res_svc.set_readiness_status(
        resource_ulid=res_b,
        status="draft",
        request_id=new_ulid(),
        actor_ulid=None,
    )
    res_svc.set_mou_status(
        resource_ulid=res_b,
        status="pending",
        request_id=new_ulid(),
        actor_ulid=None,
    )

    click.echo("OK — seeded resources:")
    click.echo(f"  A → {res_a}")
    click.echo(f"  B → {res_b}")
    click.echo(
        "Tip: `flask dev list-capabilities` to see the canonical keys."
    )


@seed_cmd.command("seed-demo-sponsors")
@click.option("--prefix", default="DemoSponsor", show_default=True)
def seed_demo_sponsors(prefix: str):
    """
    Create a couple of Sponsor orgs, attach canonical capabilities,
    and add a sample cash pledge to one of them. Uses sponsors_v2.
    """
    echo_db_banner("seed-demo-sponsors")
    import click

    from app.extensions.contracts import sponsors_v2 as spx
    from app.lib.ids import new_ulid
    from app.slices.entity import services as ent_svc

    # Helper: pick first allowed "funding.*" key if service exposes a list; fallback to a safe default.
    funding_key = "funding.cash_grant"
    try:
        # If your sponsors.services defines allowed_capabilities(), prefer it.
        from app.slices.sponsors import services as ssvc  # type: ignore

        if hasattr(ssvc, "allowed_capabilities"):
            allowed = set(ssvc.allowed_capabilities() or [])
            # Strong preference for cash_grant; otherwise take first funding.* key
            if "funding.cash_grant" in allowed:
                funding_key = "funding.cash_grant"
            else:
                funding_key = next(
                    (k for k in sorted(allowed) if k.startswith("funding.")),
                    funding_key,
                )
    except Exception:
        pass

    def mk_org(label: str) -> str:
        rid = new_ulid()
        return ent_svc.ensure_org(
            legal_name=f"{prefix}-{label}",
            ein=None,
            request_id=rid,
            actor_ulid=None,
        )

    # S1: Reimbursement-style sponsor with a pledge
    org1 = mk_org("Elks")
    s1 = spx.create_sponsor(
        entity_ulid=org1, request_id=new_ulid(), actor_ulid=None
    )["data"]["sponsor_ulid"]

    # Capabilities (e.g., funding modes they support)
    spx.upsert_capabilities(
        sponsor_ulid=s1,
        capabilities={
            funding_key: {"has": True, "note": "core funding"},
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )

    # Add a sample cash pledge and mark it active
    pledge_ulid = new_ulid()
    spx.pledge_upsert(
        sponsor_ulid=s1,
        pledge={
            "pledge_ulid": pledge_ulid,
            "type": "cash",  # keep in sync with your services' accepted values
            "status": "proposed",
            "currency": "USD",
            "stated_amount": 40000,  # $400.00
            "notes": "Welcome Home Kit budget",
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )
    spx.pledge_set_status(
        pledge_ulid=pledge_ulid,
        status="active",
        request_id=new_ulid(),
        actor_ulid=None,
    )

    # S2: Direct-support sponsor without a pledge (just capabilities)
    org2 = mk_org("Rotary")
    s2 = spx.create_sponsor(
        entity_ulid=org2, request_id=new_ulid(), actor_ulid=None
    )["data"]["sponsor_ulid"]
    spx.upsert_capabilities(
        sponsor_ulid=s2,
        capabilities={
            funding_key: {"has": True, "note": "microgrants"},
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )

    click.echo("OK — seeded sponsors:")
    click.echo(f"  S1 → {s1} (pledge {pledge_ulid})")
    click.echo(f"  S2 → {s2}")
