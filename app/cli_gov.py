# cli_gov.py — Governance CLI (drop-in)
# Thin CLI that delegates to Governance services; prints diffs; emits exactly
# one event per real change.

import json
from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext

from app.cli import echo_db_banner

# event bus (services will usually emit; CLI only passes actor/request ids down)
# canon helpers (timestamps)
from app.lib.chrono import (
    now_iso8601_ms,
)  # ensure these exist per your chrono.py

# Governance services (you’ll wire these; names used below)
from app.slices.governance.services import (
    assign_officer,
    assign_pro_tem,
    get_us_states_snapshot,
    publish_state_machine,
    revoke_officer,
    revoke_pro_tem,
    seed_domain_roles,
    seed_office_catalog,
    seed_restriction_policies_v1,
    seed_spending_policy_v1,
)

# ----- Seed content (authoritative v1/v2) ------------------------------------

DOMAIN_ROLES = [
    {
        "code": "Customer",
        "name": "Customer",
        "description": "End beneficiary using services",
    },
    {
        "code": "Resource",
        "name": "Resource",
        "description": "Partner org providing services",
    },
    {
        "code": "Sponsor",
        "name": "Sponsor",
        "description": "Funder providing grants/donations",
    },
    {
        "code": "Governor",
        "name": "Governor",
        "description": "Domain authority for governance decisions",
    },
]

OFFICES = [
    {
        "office_code": "president",
        "name": "President",
        "election_cycle": "even",
        "term_years": 2,
    },
    {
        "office_code": "vp_ops",
        "name": "Vice President for Operations",
        "election_cycle": "odd",
        "term_years": 2,
    },
    {
        "office_code": "vp_log",
        "name": "Vice President for Logistics",
        "election_cycle": "even",
        "term_years": 2,
    },
    {
        "office_code": "secretary",
        "name": "Secretary",
        "election_cycle": "odd",
        "term_years": 2,
    },
    {
        "office_code": "treasurer",
        "name": "Treasurer",
        "election_cycle": "even",
        "term_years": 2,
    },
]

SPENDING_POLICY_V1 = {
    "version": 1,
    "actions": [
        {
            "action": "approve_allocation",
            "role_caps": [
                {"role_code": "Staff", "cap": 200.00},
                {"role_code": "Treasurer", "cap": None},
                {"role_code": "Governor", "cap": None},
            ],
            "countersign": "Treasurer",
            "notify": "Treasurer",
            "notify_sla_hours": 24,
        },
        {
            "action": "approve_reimbursement",
            "role_caps": [
                {"role_code": "Staff", "cap": 200.00},
                {"role_code": "Treasurer", "cap": None},
                {"role_code": "Governor", "cap": None},
            ],
            "countersign": "Treasurer",
            "notify": "Treasurer",
            "notify_sla_hours": 24,
        },
        {
            "action": "commit_over_cap",
            "role_caps": [{"role_code": "Governor", "cap": None}],
            "countersign": None,
            "notify": "Treasurer",
            "notify_sla_hours": 24,
        },
        {
            "action": "post_journal",
            "role_caps": [
                {"role_code": "Treasurer", "cap": None},
                {"role_code": "Governor", "cap": None},
            ],
        },
        {
            "action": "release_restricted",
            "role_caps": [
                {"role_code": "Treasurer", "cap": None},
                {"role_code": "Governor", "cap": None},
            ],
        },
    ],
}

RESTRICTION_POLICIES_V1 = [
    {
        "policy_key": "finance.grants.restrictions",
        "version": 1,
        "payload": {"rules": [], "notes": "Populate as grants are onboarded"},
    },
    {
        "policy_key": "finance.donations.restrictions",
        "version": 1,
        "payload": {
            "local_only": False,
            "veteran_only": False,
            "category_caps": {},
        },
    },
    {
        "policy_key": "logistics.sku.restrictions",
        "version": 1,
        "payload": {"restricted": {}, "veteran_only": {}},
    },
]

# State machines
SM_LOGISTICS_V2 = {
    "policy_key": "logistics.item_lifecycle",
    "entity_kind": "sku_item",
    "version": 2,
    "states": [
        {"code": "received", "initial": True},
        {"code": "inspected"},
        {"code": "available"},
        {"code": "issued"},
        {"code": "returned"},
        {"code": "retired", "terminal": True},
    ],
    "transitions": [
        {"from": "received", "to": "inspected"},
        {"from": "inspected", "to": "available"},
        {"from": "available", "to": "issued"},
        {"from": "issued", "to": "returned"},
        {"from": "returned", "to": "inspected"},  # NEW in v2
        {
            "from": "available",
            "to": "retired",
            "guards": ["sku.damaged_or_expired"],
        },
    ],
}

SM_RESOURCES_V1 = {
    "policy_key": "resources.org_readiness",
    "entity_kind": "resource_org",
    "version": 1,
    "states": [
        {"code": "draft", "initial": True},
        {"code": "review"},
        {"code": "active"},
        {"code": "suspended"},
    ],
    "transitions": [
        {
            "from": "draft",
            "to": "review",
            "guards": ["capability_matrix.present", "poc.primary_set"],
        },
        {
            "from": "review",
            "to": "active",
            "guards": ["capabilities.classified", "mou.active_if_required"],
        },
        {
            "from": "active",
            "to": "suspended",
            "guards": ["admin_or_governor_action.with_reason"],
        },
    ],
}

SM_SPONSORS_V1 = {
    "policy_key": "sponsors.sponsorship",
    "entity_kind": "sponsor_agreement",
    "version": 1,
    "states": [
        {"code": "draft", "initial": True},
        {"code": "active"},
        {"code": "expired", "terminal": True},
        {"code": "terminated", "terminal": True},
    ],
    "transitions": [
        {
            "from": "draft",
            "to": "active",
            "guards": ["agreement.signed", "restrictions.configured"],
        },
        {"from": "active", "to": "expired", "guards": ["term.ended"]},
        {
            "from": "active",
            "to": "terminated",
            "guards": [
                "admin_or_governor_action.with_reason",
                "notice.satisfied",
            ],
        },
    ],
}

# ----- CLI group --------------------------------------------------------------


@click.group("governance")
def governance_group():
    """Governance admin/seeding commands."""
    pass


def _echo_diff(title: str, diff: dict, event_hint: str | None = None):
    click.echo(f"[{title}]")
    if diff.get("added"):
        for a in diff["added"]:
            click.echo(f"  + {a}")
    if diff.get("removed"):
        for r in diff["removed"]:
            click.echo(f"  - {r}")
    if diff.get("unchanged"):
        same = len(diff["unchanged"])
        if same:
            click.echo(f"  = {same} unchanged")
    if event_hint:
        click.echo(f"Would emit: {event_hint}")


@governance_group.command("seed")
@with_appcontext
@click.option(
    "--dry-run", is_flag=True, help="Preview changes without writing."
)
@click.option(
    "--only",
    type=click.Choice(
        [
            "domain_roles",
            "offices",
            "spending",
            "restrictions",
            "sm_logistics",
            "sm_resources",
            "sm_sponsors",
            "states",
        ],
        case_sensitive=False,
    ),
    multiple=True,
    help="Seed only specific sections.",
)
@click.option(
    "--actor",
    "actor_ulid",
    default=None,
    help="Actor ULID for ledger events; falls back to a system actor.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Also print a JSON summary of planned/applied diffs.",
)
def seed_cmd(
    dry_run: bool,
    only: tuple[str, ...],
    actor_ulid: str | None,
    as_json: bool,
):
    """
    Seed Governance catalogs, policies, and state machines.
    Idempotent: writes only when there is a real diff; emits exactly one event per changed section.
    """
    echo_db_banner("seed-governance-policy")
    # default to all sections if --only not given
    sections = (
        set(only)
        if only
        else {
            "domain_roles",
            "offices",
            "spending",
            "restrictions",
            "sm_logistics",
            "sm_resources",
            "sm_sponsors",
            "states",
        }
    )

    actor = actor_ulid or current_app.config.get(
        "SYSTEM_ACTOR_ULID", "00000000000000000000000000"
    )
    happened_at = now_iso8601_ms()

    results = []

    if "domain_roles" in sections:
        diff = seed_domain_roles(
            DOMAIN_ROLES,
            dry_run=dry_run,
            actor_ulid=actor,
            happened_at=happened_at,
        )
        _echo_diff(
            "domain_roles",
            diff,
            "governance.role.catalog.updated"
            if dry_run and diff.get("changed")
            else None,
        )
        results.append({"section": "domain_roles", "diff": diff})

    if "offices" in sections:
        diff = seed_office_catalog(
            OFFICES,
            dry_run=dry_run,
            actor_ulid=actor,
            happened_at=happened_at,
        )
        _echo_diff(
            "offices",
            diff,
            "governance.officer.catalog.updated"
            if dry_run and diff.get("changed")
            else None,
        )
        results.append({"section": "offices", "diff": diff})

    if "spending" in sections:
        diff = seed_spending_policy_v1(
            SPENDING_POLICY_V1,
            dry_run=dry_run,
            actor_ulid=actor,
            happened_at=happened_at,
        )
        _echo_diff(
            "spending_policy v1",
            diff,
            "governance.spending.policy.updated"
            if dry_run and diff.get("changed")
            else None,
        )
        results.append({"section": "spending_policy_v1", "diff": diff})

    if "restrictions" in sections:
        per_key = []
        for pol in RESTRICTION_POLICIES_V1:
            diff = seed_restriction_policies_v1(
                pol,
                dry_run=dry_run,
                actor_ulid=actor,
                happened_at=happened_at,
            )
            hint = (
                f"governance.restriction.policy.updated ({pol['policy_key']})"
                if dry_run and diff.get("changed")
                else None
            )
            _echo_diff(
                f"restriction:{pol['policy_key']}@{pol['version']}",
                diff,
                hint,
            )
            per_key.append({"policy_key": pol["policy_key"], "diff": diff})
        results.append({"section": "restrictions_v1", "diffs": per_key})

    if "sm_logistics" in sections:
        diff = publish_state_machine(
            SM_LOGISTICS_V2,
            dry_run=dry_run,
            actor_ulid=actor,
            happened_at=happened_at,
        )
        hint = (
            "governance.state_machine.updated (logistics.item_lifecycle@v2)"
            if dry_run and diff.get("changed")
            else None
        )
        _echo_diff(
            "state_machine logistics.item_lifecycle sku_item v2", diff, hint
        )
        results.append({"section": "sm_logistics_v2", "diff": diff})

    if "sm_resources" in sections:
        diff = publish_state_machine(
            SM_RESOURCES_V1,
            dry_run=dry_run,
            actor_ulid=actor,
            happened_at=happened_at,
        )
        hint = (
            "governance.state_machine.updated (resources.org_readiness@v1)"
            if dry_run and diff.get("changed")
            else None
        )
        _echo_diff(
            "state_machine resources.org_readiness resource_org v1",
            diff,
            hint,
        )
        results.append({"section": "sm_resources_v1", "diff": diff})

    if "sm_sponsors" in sections:
        diff = publish_state_machine(
            SM_SPONSORS_V1,
            dry_run=dry_run,
            actor_ulid=actor,
            happened_at=happened_at,
        )
        hint = (
            "governance.state_machine.updated (sponsors.sponsorship@v1)"
            if dry_run and diff.get("changed")
            else None
        )
        _echo_diff(
            "state_machine sponsors.sponsorship sponsor_agreement v1",
            diff,
            hint,
        )
        results.append({"section": "sm_sponsors_v1", "diff": diff})

    if "states" in sections:
        snap = get_us_states_snapshot()
        click.echo(
            f"[us_states]\n  source: geo.py\n  count: {len(snap)} (no changes)"
        )
        results.append({"section": "us_states", "count": len(snap)})

    if as_json:
        click.echo(
            json.dumps({"dry_run": dry_run, "results": results}, indent=2)
        )


# ---------------------------
# Officers CLI
# ---------------------------
@governance_group.group("officers")
def officers_group():
    """Manage officer assignments (assign/revoke)."""
    pass


@officers_group.command("assign")
@with_appcontext
@click.option(
    "--office",
    "office_code",
    required=True,
    help="Office code (e.g., president, vp_ops, vp_log, secretary, treasurer).",
)
@click.option(
    "--subject",
    "subject_ulid",
    required=True,
    help="ULID of the officer (entity/user).",
)
@click.option(
    "--elected-on", required=True, help="ISO-8601 like 2025-11-12T00:00:00Z"
)
@click.option("--term-years", type=int, default=2, show_default=True)
@click.option(
    "--actor",
    "actor_ulid",
    default=None,
    help="Actor ULID; defaults to SYSTEM_ACTOR_ULID.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview without writing or emitting events.",
)
def officers_assign_cmd(
    office_code, subject_ulid, elected_on, term_years, actor_ulid, dry_run
):
    echo_db_banner("seed-officer-assignment")
    actor = actor_ulid or current_app.config.get(
        "SYSTEM_ACTOR_ULID", "00000000000000000000000000"
    )
    result = assign_officer(
        subject_ulid=subject_ulid,
        office_code=office_code,
        elected_on=elected_on,
        term_years=term_years,
        actor_ulid=actor,
        dry_run=dry_run,
    )
    click.echo(result)


@officers_group.command("revoke")
@with_appcontext
@click.option(
    "--grant", "grant_ulid", required=True, help="Grant ULID to revoke."
)
@click.option("--reason", required=True, help="Reason for revocation.")
@click.option(
    "--actor",
    "actor_ulid",
    default=None,
    help="Actor ULID; defaults to SYSTEM_ACTOR_ULID.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview without writing or emitting events.",
)
def officers_revoke_cmd(grant_ulid, reason, actor_ulid, dry_run):
    echo_db_banner("seed-officer-revoke")
    actor = actor_ulid or current_app.config.get(
        "SYSTEM_ACTOR_ULID", "00000000000000000000000000"
    )
    result = revoke_officer(
        grant_ulid=grant_ulid,
        reason=reason,
        actor_ulid=actor,
        dry_run=dry_run,
    )
    click.echo(result)


# ---------------------------
# Pro-Tem CLI
# ---------------------------
@governance_group.group("pro-tem")
def protem_group():
    """Manage pro-tem assignments (assign/revoke)."""
    pass


@protem_group.command("assign")
@with_appcontext
@click.option(
    "--office",
    "office_code",
    required=True,
    help="Office code to cover as pro-tem.",
)
@click.option(
    "--subject",
    "subject_ulid",
    required=True,
    help="ULID of the pro-tem assignee.",
)
@click.option(
    "--start-on", default=None, help="ISO-8601 start; default is now."
)
@click.option(
    "--end-on",
    default=None,
    help="ISO-8601 end; clamped to officer term end if omitted/after.",
)
@click.option(
    "--actor",
    "actor_ulid",
    default=None,
    help="Actor ULID; defaults to SYSTEM_ACTOR_ULID.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview without writing or emitting events.",
)
def protem_assign_cmd(
    office_code, subject_ulid, start_on, end_on, actor_ulid, dry_run
):
    echo_db_banner("seed-protem-assignment")
    actor = actor_ulid or current_app.config.get(
        "SYSTEM_ACTOR_ULID", "00000000000000000000000000"
    )
    result = assign_pro_tem(
        subject_ulid=subject_ulid,
        office_code=office_code,
        start_on=start_on,
        end_on=end_on,
        actor_ulid=actor,
        dry_run=dry_run,
    )
    click.echo(result)


@protem_group.command("revoke")
@with_appcontext
@click.option(
    "--grant", "grant_ulid", required=True, help="Grant ULID to revoke."
)
@click.option("--reason", required=True, help="Reason for revocation.")
@click.option(
    "--actor",
    "actor_ulid",
    default=None,
    help="Actor ULID; defaults to SYSTEM_ACTOR_ULID.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview without writing or emitting events.",
)
def protem_revoke_cmd(grant_ulid, reason, actor_ulid, dry_run):
    echo_db_banner("seed-protem-revoke")
    actor = actor_ulid or current_app.config.get(
        "SYSTEM_ACTOR_ULID", "00000000000000000000000000"
    )
    result = revoke_pro_tem(
        grant_ulid=grant_ulid,
        reason=reason,
        actor_ulid=actor,
        dry_run=dry_run,
    )
    click.echo(result)


# -----------------
# Policy Linting
# -----------------


@governance_group.command("lint")
@click.option(
    "--strict/--no-strict",
    default=False,
    help="Exit non-zero if any schema fails.",
)
def governance_lint(strict):
    """Validate governance policies against their schemas."""
    from app import create_app

    app = create_app()  # or respect env vars/flags as you already do
    with app.app_context():
        data_dir = (
            Path(current_app.root_path) / "slices" / "governance" / "data"
        )
        from jsonschema import (
            Draft202012Validator,  # assume installed for CLI
        )

        errors = 0
        for p in sorted(data_dir.glob("*.json")):
            if p.name.endswith(".schema.json") or p.parent.name == "schemas":
                continue
            schema = data_dir / "schemas" / f"{p.stem}.schema.json"
            obj = json.loads(p.read_text("utf-8"))
            if not schema.exists():
                click.echo(f"[NO-SCHEMA] {p.name}")
                continue
            sch = json.loads(schema.read_text("utf-8"))
            Draft202012Validator.check_schema(sch)
            v = Draft202012Validator(sch)
            errs = list(v.iter_errors(obj))
            if errs:
                errors += 1
                click.echo(f"[INVALID]  {p.name}")
                for e in errs[:5]:
                    loc = ".".join(map(str, e.path)) or "(root)"
                    click.echo(f"  - {loc}: {e.message}")
                if len(errs) > 5:
                    click.echo(f"  … and {len(errs)-5} more")
            else:
                click.echo(f"[OK]       {p.name}")
        if strict and errors:
            raise SystemExit(2)


# Register with Flask CLI (import in your manage_vcdb.py or
# app factory CLI init)
def register_cli(app):
    app.cli.add_command(governance_group)
