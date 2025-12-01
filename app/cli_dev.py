# app/cli_dev.py

"""
Developer / ops CLI helpers for VCDB v2 (non-seeding).

These commands hang off the ``dev`` Click group that is wired in
``manage_vcdb.py``. They exist to support local workflows, policy
validation, and smoke tests against an already-seeded dev database.

**All data seeding now lives in ``cli_seed.py`` behind the ``seed`` group.**
This module should not introduce *new* records except where explicitly
called out (e.g., tripwire/demo helpers).

Typical usage from the project root::

    # Policy health + issuance coverage
    flask --app manage_vcdb.py dev policy-health

    # Lint policy JSON against schemas
    flask --app manage_vcdb.py dev policy-lint

    # Sanity-check SKUs and issuance logic
    flask --app manage_vcdb.py dev validate-skus
    flask --app manage_vcdb.py dev issuance-debug --sku AC-GL-LC-L-LB-U-00B


Command groups (high level)
===========================

Policy / Governance helpers
---------------------------

dev policy-health
    - Validate governance policy files via ``policy_semantics``:
        * JSON Schema validation (via the semantics module)
        * Cross-policy semantic checks (RBAC↔Domain, invariants, etc.)
        * Issuance coverage report over the current catalog
    - Exit code 1 only on fatal policy errors.

dev policy-lint
    - Validate raw policy JSON files against their JSON Schemas.
    - Options:
        * ``--which`` to target issuance / eligibility / calendar / etc.
        * ``--fix`` to pretty-print + sort keys (stable diffs).
        * ``--base`` / ``--schema-base`` to override search paths.
    - This operates on files only; no DB writes.

Logistics / SKU helpers
-----------------------

dev validate-skus
    - Scan ``InventoryItem`` and ``Issue`` rows for invalid SKUs.
    - Uses the same SKU parser/validator as Logistics slice.
    - Prints the first few errors and exits 1 on problems.

dev lint-skus
    - Validate ``skus.json`` against ``sku.schema.json`` under
      ``app/slices/logistics/data`` (or overrides via ``--data-dir``).
    - Fails fast with row/field errors. No DB writes.

dev list-stock
    - List on-hand stock at a given Location (e.g. ``LOC-MAIN``).
    - Read-only: just SELECTs from stock tables.

dev demo-issue
    - Issue inventory for a single SKU from a given location.
    - Behavior:
        * If ``--sku`` omitted, picks the first SKU with stock at location.
        * If ``--customer-ulid`` omitted, uses a throwaway ULID
          (no FK expected).
    - **Side-effect:** writes an issuance + movements; this is a deliberate
      “manual smoke test” against Logistics.

Issuance / policy-debug helpers
-------------------------------

dev issuance-debug
    - For one SKU:
        * Show which issuance rules match.
        * Show the final decision from Governance (allowed / reason).
    - Uses an in-memory context; no DB writes.

dev issuance-tripwires
    - For each issuance rule:
        * find or fabricate a matching SKU,
        * run blackout / qualifiers-missing / qualifiers-satisfied /
          cadence checks,
        * print per-rule behavior in a compact table.
    - Options:
        * ``--force-blackout`` to deliberately trip blackout enforcer.
        * ``--twice`` to write a “policy-only” Issue once, then re-check
          cadence limits.
        * ``--show-json`` to dump raw decisions for debugging.
    - **Side-effects:**
        * May create a test Customer if one is not provided.
        * May create SKUs, stock, and Issues as part of exercising rules.

dev decide-issue
    - Evaluate issuance policy for a SKU and a customer without writing.
    - Prints allowed / reason and a pretty JSON payload for debugging.
    - Uses a synthetic context; no DB writes by default.

Misc / maintenance helpers
--------------------------

dev whoami
    - Dump minimal context useful during local debugging:
        * APP_MODE
        * SQLALCHEMY_DATABASE_URI

dev purge-seed-items
    - Cleanup helper for old “Seed Item” logistics data.
    - Deletes rows in FK-safe order:
        * Issues → Movements → Stock → Batches → Items.
    - Intended for one-off cleanup of legacy dev artifacts.

dev list-capabilities
    - Print canonical Resource capability keys as exposed by
      ``resources.services.allowed_capabilities()``.

dev list-sponsor-capabilities
    - Print canonical Sponsor capability keys if exposed by
      ``sponsors.services.allowed_capabilities()``.
    - If not available, prints a friendly “no listing available” message.


Implementation notes
====================

- Registration:
    * ``register_cli(app)`` attaches the ``dev`` group to the Flask CLI.
    * All commands here should be safe to ship; nothing runs unless explicitly
      invoked.

- Side-effects:
    * Most commands are read-only (SELECTs and file validation).
    * The few that **do** write (e.g., ``issuance-tripwires`` with cadence
      tests, ``demo-issue``, ``purge-seed-items``) are explicitly documented
      as such above.
    * Keep any new dev commands either:
        - read-only, OR
        - very clearly documented about what they mutate and why.

- Scope and separation from seeding:
    * All **seeding** lives in ``cli_seed.py`` under the ``seed`` group.
    * This module is for diagnostics, linting, and interactive smoke tests.
    * When adding new helpers, update this docstring so future maintainers
      can see available tools and their side-effects at a glance.
"""


from __future__ import annotations

import json
import os
from pathlib import Path

import click

# Optional: read APP_MODE so we can gate dangerous actions
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import select

from app.cli import echo_db_banner
from app.slices.logistics.sku import (
    classification_key_for,
    parse_sku,
    validate_sku,
)


def register_cli(app):
    """Attach the 'dev' command group to Flask CLI."""
    app.cli.add_command(dev_group)


# Semantics/health checks for policies
try:
    from app.extensions.policy_semantics import (
        PolicyError,
        policy_health_report,
    )
except Exception:  # still useful even if semantics module not present yet
    PolicyError = RuntimeError

    def policy_health_report():
        return (["policy_semantics module not available"], [])


@click.group("dev")
def dev_group():
    """Developer / Ops helpers (policy health, wiring checks, seed shims)."""


# -----------------
# SKU Validation
# -----------------


@dev_group.command("validate-skus")
@with_appcontext
@click.option("--limit", type=int, default=500, help="Max rows to scan.")
def dev_validate_skus(limit: int):
    """
    Scan InventoryItem + Issue for invalid SKUs and report the first few problems.
    """
    echo_db_banner("validate-skus")
    from app.extensions import db
    from app.slices.logistics.models import InventoryItem, Issue
    from app.slices.logistics.sku import parse_sku

    bad = []

    def _check(model, field):
        q = db.session.query(model).limit(limit)
        for row in q:
            sku = getattr(row, field, None)
            if not sku:
                continue
            if not validate_sku(sku):
                bad.append(
                    (
                        model.__name__,
                        getattr(row, "ulid", "—"),
                        sku,
                        "invalid",
                    )
                )
                continue
            try:
                parse_sku(sku)
            except Exception as e:
                bad.append(
                    (
                        model.__name__,
                        getattr(row, "ulid", "—"),
                        sku,
                        f"parse_error: {e}",
                    )
                )

    _check(InventoryItem, "sku")
    _check(Issue, "sku_code")

    if not bad:
        click.echo("All scanned SKUs look valid.")
        return

    click.echo("Found bad SKUs:")
    for mdl, ulid, sku, why in bad[:50]:
        click.echo(f"  {mdl} {ulid}: {sku}  ← {why}")
    if len(bad) > 50:
        click.echo(f"...and {len(bad) - 50} more")
    raise SystemExit(1)


# -----------------
# Policy Checks
# -----------------


@dev_group.command("policy-health")
@with_appcontext
@click.option("--json", "as_json", is_flag=True, help="Emit JSON report.")
def dev_policy_health(as_json: bool):
    """
    Validate governance policies:
      - JSON Schema validation
      - Cross-policy semantic checks (e.g., RBAC↔Domain constraints)
      - Coverage hints (e.g., issuance rules cover active classification_keys)

    Exit codes:
      0 = OK (no warnings)
      0 = OK with warnings (we print WARN lines)
      1 = Fatal policy error (invalid/unsatisfied invariants)
    """
    echo_db_banner("policy-health")
    try:
        warns, infos = policy_health_report()
    except PolicyError as e:
        click.echo(f"FATAL: {e}", err=True)
        raise SystemExit(1)

    if as_json:
        click.echo(json.dumps({"infos": infos, "warnings": warns}, indent=2))
    else:
        for i in infos:
            click.echo(f"INFO: {i}")
        for w in warns:
            click.echo(f"WARN: {w}")

    # warnings shouldn’t fail CI by default;
    # change to nonzero if you want strict mode
    # raise SystemExit(0)

    # --- Issuance coverage report -----------------------------------------
    summary, per_rule = _scan_issuance_coverage()

    if as_json:
        import json

        out = {
            "issuance": {
                "default_behavior": summary["default_behavior"],
                "total_items": summary["total_items"],
                "matched_items": summary["matched_items"],
                "unmatched_items": summary["unmatched_items"],
                "per_rule": per_rule,
                "unmatched_samples": summary["unmatched_samples"],
            }
        }
        click.echo(json.dumps(out, indent=2))
        return

    click.echo("")
    click.echo("Issuance policy — coverage over catalog")
    click.echo(f"  default_behavior : {summary['default_behavior']}")
    click.echo(f"  total_items      : {summary['total_items']}")
    click.echo(f"  matched_items    : {summary['matched_items']}")
    click.echo(f"  unmatched_items  : {summary['unmatched_items']}")
    if summary["unmatched_items"]:
        click.echo(
            "  unmatched samples: " + ", ".join(summary["unmatched_samples"])
        )

    if per_rule:
        click.echo("  per-rule match counts (first-match wins):")
        for r in per_rule:
            selector = r["selector"]
            click.echo(
                f"    #{r['index']:02}  {selector}  → {r['match_count']}"
            )
    else:
        click.echo("  (no rules loaded)")
        # --- Additional summaries (text mode only) ----------------------------
    # Give Dev/Ops a quick view of how SKU/unit and Location policy are
    # being used in the Logistics slice. Skip when --json is requested.
    if not as_json:
        click.echo("")
        _print_sku_policy_summary()
        click.echo("")
        _print_location_policy_summary()


def _print_location_policy_summary() -> None:
    """
    Print a compact summary of Location policy vs DB usage.

    - Shows explicit location specs from policy_locations.json
    - Shows the rack/bin regex pattern
    - Flags any Location.code in DB that is not covered by policy/pattern
    """
    import re

    from app.extensions import db
    from app.extensions.policies import load_policy_locations
    from app.slices.logistics.models import Location

    pol = load_policy_locations()
    kinds = pol.get("kinds") or []
    loc_specs = pol.get("locations") or []
    patterns = pol.get("patterns") or {}
    rackbin_pattern = re.compile(
        patterns.get("rackbin", r"$^")
    )  # match nothing if missing

    allowed_codes = {spec["code"] for spec in loc_specs}

    click.echo("Location policy — codes vs DB")
    click.echo("-----------------------------")
    click.echo(f"kinds          : {', '.join(kinds) or '(none)'}")
    click.echo("locations:")
    for spec in loc_specs:
        click.echo(
            f"  - code={spec['code']!r:10s}  "
            f"kind={spec.get('kind', '?'):10s}  "
            f"name={spec.get('name', '')}"
        )
    click.echo(f"rackbin pattern: {patterns.get('rackbin', '(none)')}")
    click.echo("")

    rows = (
        db.session.execute(select(Location.code).order_by(Location.code))
        .scalars()
        .all()
    )

    if not rows:
        click.echo("Location codes in DB: (no rows)")
        return

    click.echo("Location codes in DB:")
    bad_codes: list[str] = []
    for code in rows:
        in_policy = code in allowed_codes
        matches_pattern = bool(rackbin_pattern.match(code))
        flag = ""
        if not (in_policy or matches_pattern):
            flag = "  (! not in policy)"
            bad_codes.append(code)
        click.echo(f"  {code!r}{flag}")

    if bad_codes:
        click.echo("")
        click.echo(
            "WARN: Location codes not covered by policy or rackbin pattern:"
        )
        for c in sorted(set(bad_codes)):
            click.echo(f"  - {c!r}")


# -----------------
# Policy Linting
# check for
# Fat Finger errors
# -----------------


@dev_group.command("policy-lint")
@with_appcontext
@click.option(
    "--which",
    type=click.Choice(["issuance", "eligibility", "calendar", "all"]),
    default="all",
    show_default=True,
)
@click.option(
    "--fix",
    is_flag=True,
    help="Rewrite file with canonical formatting (sorted keys, 2-space indent)",
)
@click.option(
    "--base",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    help="Override the policies base directory (folder that contains the *.json policy files)",
)
@click.option(
    "--schema-base",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    help="Override the schema base directory (folder that contains the *.schema.json files)",
)
@click.option("--print-paths", is_flag=True, help="Print resolved file paths")
def dev_policy_lint(
    which, fix, base: Path | None, schema_base: Path | None, print_paths: bool
):
    """
    Validate governance policy JSON files against their schemas.
    On --fix, pretty-print and sort keys so diffs stay clean.
    """
    echo_db_banner("policy-lint")
    import json

    from flask import current_app
    from jsonschema import Draft202012Validator

    from app.extensions.validate import load_json, load_json_schema

    # -------- resolve bases --------
    app_root = Path(current_app.root_path)
    policy_bases = (
        [base]
        if base
        else [
            app_root / "slices" / "governance" / "data",
            app_root / "slices" / "governance",  # fallback
            app_root / "slices" / "governance" / "policies",  # fallback
        ]
    )
    resolved_base = next((p for p in policy_bases if p and p.exists()), None)
    if not resolved_base:
        click.secho(
            "ERROR: could not find a policies base directory.", fg="red"
        )
        for p in policy_bases:
            click.echo(f"  tried: {p}")
        raise SystemExit(1)

    if not schema_base:
        # prefer <base>/schema, else try <base>, else <governance>/data/schema
        candidates = [
            resolved_base / "schema",
            resolved_base,
            app_root / "slices" / "governance" / "data" / "schema",
        ]
        schema_base = next(
            (p for p in candidates if p.exists()), resolved_base
        )

    click.secho(f"[policy-lint] base={resolved_base}", fg="cyan")
    click.secho(f"[policy-lint] schema_base={schema_base}", fg="cyan")

    targets = {
        "issuance": (
            "policy_issuance.json",
            "policy_issuance.schema.json",
        ),
        "eligibility": (
            "policy_eligibility.json",
            "policy_eligibility.schema.json",
        ),
        "calendar": (
            "policy_calendar.json",
            "policy_calendar.schema.json",
        ),
        "classification": (
            "policy_classification.json",
            "policy_classification.schema.json",
        ),
        "funding": (
            "policy_funding.json",
            "policy_funding.schema.json",
        ),
        "spending": (
            "policy_spending.json",
            "policy_spending.schema.json",
        ),
        "state_machine": (
            "policy_state_machine.json",
            "policy_state_machine.schema.json",
        ),
    }

    todo = targets.items() if which == "all" else [(which, targets[which])]

    def _find_schema(sname: str) -> Path | None:
        # Try schema_base/sname, then resolved_base/sname, then recursive glob
        direct = schema_base / sname
        if direct.exists():
            return direct
        alt = resolved_base / sname
        if alt.exists():
            return alt
        # final fallback: glob anywhere under schema_base or resolved_base
        for root in [schema_base, resolved_base]:
            hits = list(root.rglob(sname))
            if hits:
                return hits[0]
        return None

    had_error = False
    for name, (fname, sname) in todo:
        fpath = resolved_base / fname
        spath = _find_schema(sname)

        if print_paths:
            click.echo(f"{name:11s} json   : {fpath}")
            click.echo(
                f"{'':11s} schema : {spath if spath else '(not found)'}"
            )

        missing = []
        if not fpath.exists():
            missing.append(str(fpath))
        if not spath or not spath.exists():
            missing.append(str(schema_base / sname))

        if missing:
            had_error = True
            click.secho(f"FAIL — {name} files not found:", fg="red")
            for m in missing:
                click.echo(f"  - {m}")
            continue

        try:
            payload = load_json(fpath)
            schema = load_json_schema(spath)
            Draft202012Validator(schema).validate(payload)
            click.secho(f"OK — {name} valid: {fname}", fg="green")
            if fix:
                text = json.dumps(
                    payload, indent=2, sort_keys=True, ensure_ascii=False
                )
                fpath.write_text(text + "\n", encoding="utf-8")
        except Exception as e:
            had_error = True
            _print_json_error(e, fname)

    if had_error:
        raise SystemExit(1)


# -----------------
# issuance coverage
# helpers
# -----------------


def _scan_issuance_coverage():
    from types import SimpleNamespace as NS

    from app.extensions import db
    from app.extensions.policies import load_policy_issuance
    from app.slices.governance.services import _rule_matches
    from app.slices.logistics.models import InventoryItem
    from app.slices.logistics.sku import parse_sku

    pol = load_policy_issuance()
    rules = list(pol.get("rules") or [])
    default_behavior = (pol.get("default_behavior") or "deny").lower()

    rows = (
        db.session.execute(
            select(InventoryItem.sku).order_by(InventoryItem.sku)
        )
        .scalars()
        .all()
    )

    per_rule = [
        {"index": i + 1, "selector": (r.get("match") or {}), "match_count": 0}
        for i, r in enumerate(rules)
    ]

    matched_any = 0
    unmatched_samples = []
    for code in rows:
        ctx = NS(
            customer_ulid=None,
            sku_code=code,
            classification=classification_key_for(code),
            sku_parts=parse_sku(code),
            when_iso=None,
            project_ulid=None,
        )
        hit = False
        for i, r in enumerate(rules):
            if _rule_matches(r, ctx):
                per_rule[i]["match_count"] += 1
                hit = True
                break

        if hit:
            matched_any += 1
        elif len(unmatched_samples) < 10:
            unmatched_samples.append(code)

    summary = {
        "total_items": len(rows),
        "matched_items": matched_any,
        "unmatched_items": len(rows) - matched_any,
        "default_behavior": default_behavior,
        "unmatched_samples": unmatched_samples,
    }
    return summary, per_rule


def _print_sku_policy_summary() -> None:
    """
    Print a compact summary of SKU constraints policy vs DB usage.

    - Shows allowed_units / allowed_sources from policy_sku_constraints.json
    - Shows InventoryItem.unit usage and flags any units not allowed by policy
    """
    from sqlalchemy import func
    from app.extensions import db
    from app.extensions.policies import load_policy_sku_constraints
    from app.slices.logistics.models import InventoryItem

    pol = load_policy_sku_constraints()
    allowed_units = set(pol.get("allowed_units") or [])
    allowed_sources = set(pol.get("allowed_sources") or [])

    click.echo("SKU constraints — policy vs catalog")
    click.echo("----------------------------------")
    click.echo(
        f"allowed_units   : {', '.join(sorted(allowed_units)) or '(none)'}"
    )
    click.echo(
        f"allowed_sources : {', '.join(sorted(allowed_sources)) or '(none)'}"
    )
    click.echo("")

    rows = db.session.execute(
        select(InventoryItem.unit, func.count())
        .group_by(InventoryItem.unit)
        .order_by(InventoryItem.unit)
    ).all()

    if not rows:
        click.echo("InventoryItem units (DB) : (no items)")
        return

    click.echo("InventoryItem units (DB usage):")
    bad_units: list[str] = []
    for unit, count in rows:
        flag = ""
        if unit not in allowed_units:
            flag = "  (! not in policy)"
            bad_units.append(unit)
        click.echo(f"  {unit!r:10s}  {count:5d}{flag}")

    if bad_units:
        click.echo("")
        click.echo("WARN: units present in DB but not allowed by policy:")
        for u in sorted(set(bad_units)):
            click.echo(f"  - {u!r}")


# -----------------
# Assign Default Behavior
# so issuance-debug has a
# viable "default-behavior"
# -----------------


def show_default(default_behavior) -> None:
    """Human-friendly print of issuance default behavior."""
    # Handle either a simple string or a dict
    if isinstance(default_behavior, str):
        click.echo(f"  behavior: {default_behavior}")
        return

    behavior = (default_behavior.get("behavior") or "deny").lower()
    cadence = default_behavior.get("cadence")
    click.echo(f"  behavior: {behavior}")
    if cadence:
        click.echo(f"  cadence : {cadence}")


# -----------------
# Issuance Debugger
# check to see if
# Inventory item restrictions
# Customer qualifications
# work across SKU's
# -----------------


@dev_group.command("issuance-debug")
@click.argument("sku_code")
@click.option(
    "--when-iso",
    help="ISO8601 timestamp; defaults to now",
)
@click.option(
    "--project-ulid",
    help="Optional project ULID; if set, project-only rules may apply",
)
def dev_issuance_debug(
    sku_code: str, when_iso: str | None, project_ulid: str | None
) -> None:
    """Debug issuance policy for a single SKU.

    - Shows which rules match the SKU/classification.
    - Shows the final decision from governance (allowed / reason).
    - Does not write to the DB.
    """
    from types import SimpleNamespace

    from app.extensions.policies import load_policy_issuance
    from app.lib.chrono import now_iso8601_ms
    from app.slices.governance.services import _rule_matches, decide_issue

    try:
        parts = parse_sku(sku_code)
    except ValueError as e:
        click.echo(f"Invalid SKU '{sku_code}': {e}")
        raise SystemExit(1)  # noqa: B904

    if when_iso is None:
        when_iso = now_iso8601_ms()

    # Canonical classification key (e.g. 'CG/SL')
    ckey = classification_key_for(sku_code)

    policy = load_policy_issuance()
    default_behavior = policy.get("default", {})
    rules = policy.get("rules", [])

    click.echo(f"=== Issuance debug for SKU {sku_code} ===")
    click.echo(f"classification_key = {ckey}")
    click.echo(f"when_iso          = {when_iso}")
    click.echo(f"project_ulid      = {project_ulid or '-'}")
    click.echo("")

    # Show default behavior
    click.echo("Default behavior:")
    show_default(default_behavior)
    click.echo("")

    # Build a context object for rule matching (as expected by _rule_matches)
    ctx_match = SimpleNamespace(
        customer_ulid="DEBUG-CUSTOMER",
        sku_code=sku_code,
        classification=ckey,  # _rule_matches uses 'classification'
        sku_parts=parts,
        when_iso=when_iso,
        project_ulid=project_ulid,
    )

    # Show matching rules
    click.echo("Matching rules:")
    any_match = False
    for rule in rules:
        if _rule_matches(rule, ctx_match):
            any_match = True
            click.echo(
                f"- {rule.get('key', '<no key>')}: scope={rule.get('scope')!r}"
            )
    if not any_match:
        click.echo("  (no rules matched this classification)")
    click.echo("")

    # Evaluate decision via canonical governance path
    ctx_decide = SimpleNamespace(
        customer_ulid="DEBUG-CUSTOMER",
        sku_code=sku_code,
        classification_key=ckey,  # decide_issue uses 'classification_key'
        sku_parts=parts,
        when_iso=when_iso,
        project_ulid=project_ulid,
        force_blackout=False,
        qualifiers={},
        defaults_cadence=None,
    )

    decision = decide_issue(ctx_decide)
    if decision.allowed:
        click.echo(f"ALLOWED ({decision.reason})")
    else:
        click.echo(f"DENIED ({decision.reason})")

    # Pretty JSON payload for deeper debugging — only fields that exist today
    payload = {
        "allowed": getattr(decision, "allowed", None),
        "reason": getattr(decision, "reason", None),
        "approver_required": getattr(decision, "approver_required", None),
        "next_eligible_at_iso": getattr(
            decision, "next_eligible_at_iso", None
        ),
        "limit_window_label": getattr(decision, "limit_window_label", None),
    }
    click.echo("")
    click.echo(json.dumps(payload, indent=2, sort_keys=True))


# -----------------
# hit all the
# policy tripwires
# -----------------


@dev_group.command("issuance-tripwires")
@with_appcontext
@click.option(
    "--customer-ulid",
    default=None,
    help="Existing test customer ULID; if absent we'll create one.",
)
@click.option("--location", default="MAIN", show_default=True)
@click.option(
    "--per-sku",
    type=int,
    default=2,
    show_default=True,
    help="Units to receive per fabricated SKU.",
)
@click.option(
    "--force-blackout/--no-force-blackout",
    default=False,
    show_default=True,
    help="Trip the blackout enforcer",
)
@click.option(
    "--show-json",
    is_flag=True,
    help="Dump per-gate decision payloads for debugging",
)
@click.option(
    "--twice/--once",
    default=False,
    show_default=True,
    help="In cadence step, create one policy-only Issue first, then re-check (often triggers cadence_limit).",
)
def dev_issuance_tripwires(
    customer_ulid: str | None,
    location: str,
    per_sku: int,
    force_blackout: bool,
    show_json: bool,
    twice: bool,
):
    """
    For each issuance policy rule:
      - find or fabricate a matching SKU,
      - run: blackout, qualifiers-missing, qualifiers-satisfied, cadence trip,
      - print reasons for each run.

    NOTE/TODO: Later, standardize issuance service signatures across Logistics
    so all callers use the same kwargs surface.
    """
    echo_db_banner("issuance-tripwires")
    import json
    from types import SimpleNamespace as NS

    from app.extensions import db
    from app.extensions.policies import (
        load_policy_issuance,
    )
    from app.lib.chrono import now_iso8601_ms
    from app.lib.ids import new_ulid
    from app.slices.governance.services import _rule_matches, decide_issue
    from app.slices.logistics.models import InventoryItem

    # InventoryBatch might not exist in some branches; tolerate absence
    try:
        from app.slices.logistics.models import InventoryBatch  # type: ignore
    except Exception:  # pragma: no cover
        InventoryBatch = None  # type: ignore[assignment]

    from app.slices.logistics.services import (
        ensure_item,
        ensure_location,
        receive_inventory,
    )
    from app.slices.logistics.sku import parse_sku

    pol = load_policy_issuance()
    rules = list(pol.get("rules") or [])
    if not rules:
        click.echo("No issuance rules loaded.")
        return

    # Ensure a test customer (create a minimal person-entity, then Customer)
    if not customer_ulid:
        from app.lib.ids import new_ulid
        from app.slices.customers.services import ensure_customer
        from app.slices.entity.services import ensure_person

        reqid = new_ulid()
        ent_ulid = ensure_person(
            first_name="Tripwire",
            last_name="Tester",
            email=None,
            phone=None,
            request_id=reqid,
            actor_ulid=None,
        )
        customer_ulid = ensure_customer(
            entity_ulid=ent_ulid,
            request_id=new_ulid(),
            actor_ulid=None,
        )
        click.echo(
            f"Created test person entity {ent_ulid} → customer {customer_ulid}"
        )

    # Helper: pick/create a SKU that matches a rule (and return loc+batch)
    def pick_or_fabricate_sku(rule):
        # 1) scan existing catalog
        rows = db.session.execute(select(InventoryItem.sku)).scalars().all()
        for code in rows:
            ctx = NS(
                customer_ulid=customer_ulid,
                sku_code=code,
                classification_key="-".join(code.split("-")[:2]),
                sku_parts=parse_sku(code),
                when_iso=now_iso8601_ms(),
                project_ulid=None,
            )
            if _rule_matches(rule, ctx):
                # also resolve location + recent batch for cadence step
                it_ulid = db.session.execute(
                    select(InventoryItem.ulid).where(
                        InventoryItem.sku == code
                    )
                ).scalar_one_or_none()
                loc_ulid = ensure_location(code=location, name=location)
                batch_ulid = None
                if InventoryBatch is not None:
                    batch_ulid = (
                        db.session.execute(
                            select(InventoryBatch.ulid)
                            .where(
                                InventoryBatch.item_ulid == it_ulid,
                                InventoryBatch.location_ulid == loc_ulid,
                            )
                            .order_by(InventoryBatch.ulid.desc())
                        )
                        .scalars()
                        .first()
                    )
                return code, False, loc_ulid, batch_ulid  # found existing

        # 2) fabricate a minimal matching SKU
        m = rule.get("match") or {}
        parts = {
            "cat": "FW",
            "sub": "HT",
            "src": "LC",
            "size": "NA",
            "col": "BK",
            "issuance_class": "U",
            "seq": "Z9Z",
        }
        # apply any sku_parts constraints from the rule
        for human_k, v in (m.get("sku_parts") or {}).items():
            key = {
                "category": "cat",
                "subcategory": "sub",
                "source": "src",
                "size": "size",
                "color": "col",
                "issuance_class": "issuance_class",
                "seq": "seq",
            }.get(human_k, human_k)
            parts[key] = v

        # enforce qualifiers-derived constraints (e.g., homeless/veteran)
        q = rule.get("qualifiers") or {}
        if q.get("homeless_required"):
            parts["issuance_class"] = "H"
        elif q.get("veteran_required"):
            parts["issuance_class"] = "V"

        # DRMO constraint: any DR item must be V
        if parts.get("src") == "DR":
            parts["issuance_class"] = "V"

        sku = (
            f"{parts['cat']}-{parts['sub']}-{parts['src']}-"
            f"{parts['size']}-{parts['col']}-{parts['issuance_class']}-{parts['seq']}"
        )
        if not validate_sku(sku):
            return None, False, None, None

        loc_ulid = ensure_location(code=location, name=location)
        try:
            item_ulid = ensure_item(
                category=f"{parts['cat']}/{parts['sub']}",
                name=f"tripwire {sku}",
                unit="each",
                condition="new",
                sku=sku,
            )
        except ValueError:
            # policy constraints rejected this SKU; give up on this rule
            return None, False, None, None

        recv = receive_inventory(
            item_ulid=item_ulid,
            quantity=per_sku,
            unit="each",
            source="donation",
            received_at_utc=now_iso8601_ms(),
            location_ulid=loc_ulid,
            note="seed:tripwire",
            actor_ulid=None,
            source_entity_ulid=None,
        )
        db.session.commit()
        return sku, True, loc_ulid, recv.get("batch_ulid")

    # Helper: mutate eligibility flags on the customer
    def set_flags(veteran: bool | None = None, homeless: bool | None = None):
        from app.slices.customers.services import set_verification_flags

        set_verification_flags(
            customer_ulid=customer_ulid, veteran=veteran, homeless=homeless
        )

    # Helper: call decide_issue with a constructed ctx (no DB writes)
    def eval_ctx(sku_code: str, when_iso: str, force_blackout: bool = False):
        ctx = NS(
            customer_ulid=customer_ulid,
            sku_code=sku_code,
            classification=classification_key_for(sku_code),
            sku_parts=parse_sku(sku_code),
            when_iso=when_iso,
            project_ulid=None,
            force_blackout=force_blackout,  # enforcer may ignore if unsupported
        )
        return decide_issue(ctx)

    # Pick a blackout instant if your calendar defines explicit blackout dates
    from datetime import datetime, timedelta, timezone

    def _iso(d: datetime) -> str:
        # ISO8601 with microseconds + Z, matching your app’s style
        return (
            d.replace(tzinfo=timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    def _next_weekday_noon_utc(target_wd: int) -> str:
        # Monday=0 … Sunday=6
        now = datetime.now(timezone.utc)
        days_ahead = (target_wd - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        dt = (now + timedelta(days=days_ahead)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        return _iso(dt)

    def _blackout_when_from_calendar() -> str | None:
        try:
            from app.extensions.policies import load_policy_calendar

            cal = load_policy_calendar()
        except Exception:
            return None

        # Try explicit date ranges first
        projects = cal.get("projects") or {}
        for _pid, pdata in projects.items():
            for rule in pdata.get("blackout_rules", []):
                t = (rule.get("type") or "").lower()
                if t == "date_range" and rule.get("start"):
                    # pick the start date at noon UTC
                    try:
                        start = datetime.fromisoformat(
                            rule["start"]
                        )  # 'YYYY-MM-DD'
                    except Exception:
                        continue
                    dt = datetime(
                        start.year,
                        start.month,
                        start.day,
                        12,
                        0,
                        0,
                        tzinfo=timezone.utc,
                    )
                    return _iso(dt)
                if t == "weekday" and rule.get("days"):
                    # pick the first weekday specified (SAT/SUN/etc.)
                    wd_map = {
                        "MON": 0,
                        "TUE": 1,
                        "WED": 2,
                        "THU": 3,
                        "FRI": 4,
                        "SAT": 5,
                        "SUN": 6,
                    }
                    for day in rule["days"]:
                        wd = wd_map.get(day.upper())
                        if wd is not None:
                            return _next_weekday_noon_utc(wd)
        return None

    # --- choose blackout instant
    blackout_when = _blackout_when_from_calendar()
    if not blackout_when:
        # fallback: next Saturday at noon UTC
        blackout_when = _next_weekday_noon_utc(5)

    rows_out = []
    for idx, rule in enumerate(rules, 1):
        sku_code, created, loc_ulid, batch_ulid = pick_or_fabricate_sku(rule)
        selector = rule.get("match") or {}
        if not sku_code:
            rows_out.append(
                (
                    idx,
                    json.dumps(selector),
                    "n/a",
                    "n/a",
                    "n/a",
                    "n/a",
                    "no_matching_sku",
                )
            )
            continue

        # 1) blackout
        set_flags(False, False)

        # blackout column
        dec_bl = eval_ctx(
            sku_code, blackout_when, force_blackout=force_blackout
        )
        if show_json:
            click.echo(f"    blackout_decision={dec_bl!r}")

        if force_blackout:
            # when forcing, expect a calendar block; if allowed, show reason (usually "ok")
            blackout = (
                "calendar_blackout"
                if (
                    not dec_bl.allowed
                    and dec_bl.reason == "calendar_blackout"
                )
                else (dec_bl.reason or "ok")
            )
        else:
            # when not forcing, "ok" is the expected happy path
            blackout = (
                "ok"
                if dec_bl.allowed
                else (dec_bl.reason or "calendar_blackout")
            )

        reason_bl = getattr(dec_bl, "reason", None)
        if getattr(dec_bl, "allowed", False):
            reason_bl = "unexpected_ok"

        # 2) qualifiers missing
        set_flags(False, False)
        dec_qmiss = eval_ctx(sku_code, now_iso8601_ms())
        reason_qmiss = getattr(dec_qmiss, "reason", None)

        # 3) qualifiers satisfied (set both; engine will only require what it needs)
        set_flags(True, True)
        dec_ok = eval_ctx(sku_code, now_iso8601_ms())
        reason_ok = getattr(dec_ok, "reason", None)
        ok_allowed = getattr(dec_ok, "allowed", False)

        # --- 4) cadence check (optionally force by writing one policy-only Issue)
        dec_cad = eval_ctx(
            sku_code, when_iso=now_iso8601_ms(), force_blackout=False
        )

        if twice and ok_allowed:
            try:
                from app.slices.logistics.services import (
                    issue_inventory_policy,
                )

                # write a policy-only Issue, then re-check cadence
                _ = issue_inventory_policy(
                    customer_ulid=customer_ulid,
                    sku_code=sku_code,
                    when_iso=None,
                    project_ulid=None,
                    actor_ulid=None,
                    quantity=1,
                )
                dec_cad = eval_ctx(
                    sku_code, when_iso=now_iso8601_ms(), force_blackout=False
                )
            except Exception:
                # keep original dec_cad if anything fails
                pass

        if show_json:
            click.echo(f"    cadence_decision={dec_cad!r}")

        # unify cadence label
        cadence = dec_cad.reason or (
            "ok" if getattr(dec_cad, "allowed", False) else "cadence_limit"
        )

        # --- build output row using the computed labels
        rows_out.append(
            (
                idx,
                json.dumps(selector),
                sku_code,
                blackout,  # computed above
                (reason_qmiss or "ok"),  # qualifiers-missing column
                ("ok" if ok_allowed else "denied"),  # allowed column
                cadence,  # final cadence label
            )
        )

    # Print a compact table
    click.echo(
        "rule  selector                              sku                        blackout           q-missing        allowed  cadence"
    )
    for r in rows_out:
        click.echo(
            f"{r[0]:>4}  {r[1]:<36}  {r[2]:<24}  {r[3]:<16}  {r[4]:<16}  {r[5]:<7}  {r[6]}"
        )


# -----------------
# decide-issue test
# decision logic
# tripwire triggers
# USAGE:
# flask dev decide-issue AC-GL-LC-L-LB-U-00B
# flask dev decide-issue AC-GL-LC-L-LB-U-00B --force-blackout
# -----------------


@dev_group.command("decide-issue")
@click.argument("sku_code")
@click.option(
    "--customer-ulid",
    help="Customer ULID; if omitted, uses a synthetic 'DEBUG-CUSTOMER'.",
)
@click.option(
    "--when-iso",
    help="ISO8601 timestamp; defaults to now.",
)
@click.option(
    "--project-ulid",
    help="Optional project ULID for project-only rules.",
)
@click.option(
    "--force-blackout",
    is_flag=True,
    help="Force blackout enforcer to deny, for debugging blackout behavior.",
)
def dev_decide_issue(
    sku_code: str,
    customer_ulid: str | None,
    when_iso: str | None,
    project_ulid: str | None,
    force_blackout: bool,
) -> None:
    """Evaluate issuance policy for a SKU and a customer without writing.

    Prints ALLOWED/DENIED and a pretty JSON payload of the IssueDecision.
    """
    from types import SimpleNamespace

    from app.lib.chrono import now_iso8601_ms
    from app.slices.governance.services import decide_issue

    try:
        parts = parse_sku(sku_code)
    except ValueError as e:
        click.echo(f"Invalid SKU '{sku_code}': {e}")
        raise SystemExit(1)

    if when_iso is None:
        when_iso = now_iso8601_ms()

    ckey = classification_key_for(parts)

    ctx = SimpleNamespace(
        customer_ulid=customer_ulid or "DEBUG-CUSTOMER",
        sku_code=sku_code,
        classification_key=ckey,
        sku_parts=parts,
        when_iso=when_iso,
        project_ulid=project_ulid,
        force_blackout=force_blackout,
        qualifiers={},
        defaults_cadence=None,
    )

    decision = decide_issue(ctx)

    # Human summary
    status = "ALLOWED" if decision.allowed else "DENIED"
    click.echo(f"{status} ({decision.reason})")

    # Structured payload
    payload = {
        "allowed": getattr(decision, "allowed", None),
        "reason": getattr(decision, "reason", None),
        "approver_required": getattr(decision, "approver_required", None),
        "next_eligible_at_iso": getattr(
            decision, "next_eligible_at_iso", None
        ),
        "limit_window_label": getattr(decision, "limit_window_label", None),
    }
    click.echo("")
    click.echo(json.dumps(payload, indent=2, sort_keys=True))


# -----------------
# Env/DB location Check
# -----------------


@dev_group.command("whoami")
@with_appcontext
def dev_whoami():
    """Dump minimal context useful during local debugging."""
    cfg = current_app.config
    click.echo(f"APP_MODE={cfg.get('APP_MODE','unknown')}")
    click.echo(f"DB_URI={cfg.get('SQLALCHEMY_DATABASE_URI','?')}")


# -----------------
# List Inventory
# In-Stock/On-Hand
# -----------------


@dev_group.command("list-stock")
@with_appcontext
@click.option(
    "--location",
    "loc_code",
    required=True,
    help="Location code (e.g., LOC-MAIN)",
)
@click.option("--limit", type=int, default=50, show_default=True)
def dev_list_stock(loc_code: str, limit: int):
    """List on-hand quantities at a location."""
    echo_db_banner("list-stock")

    from app.extensions import db
    from app.slices.logistics.models import (
        InventoryItem,
        InventoryStock,
        Location,
    )

    loc = db.session.execute(
        select(Location).where(Location.code == loc_code)
    ).scalar_one_or_none()
    if not loc:
        raise SystemExit(f"Unknown location code: {loc_code}")

    rows = db.session.execute(
        select(
            InventoryItem.sku,
            InventoryItem.name,
            InventoryStock.quantity,
            InventoryStock.unit,
        )
        .join(InventoryStock, InventoryStock.item_ulid == InventoryItem.ulid)
        .where(InventoryStock.location_ulid == loc.ulid)
        .order_by(InventoryItem.sku)
        .limit(limit)
    ).all()

    if not rows:
        click.echo("(no stock)")
        return

    click.echo(f"Stock at {loc.code} ({loc.ulid}):")
    for sku, name, qty, unit in rows:
        click.echo(f"  {sku:20s}  {qty:4d} {unit:6s}  {name}")


# -----------------
# Issuance Policy Check
# -----------------


@dev_group.command("demo-issue")
@with_appcontext
@click.option(
    "--customer-ulid",
    required=False,
    help="If omitted, uses a throwaway ULID (no FK expected).",
)
@click.option(
    "--sku",
    "sku_code",
    required=False,
    help="If omitted, picks the first available at location.",
)
@click.option("--location", "loc_code", default="LOC-MAIN", show_default=True)
@click.option("--actor-ulid", default=None)
@click.option("--quantity", type=int, default=1, show_default=True)
def dev_demo_issue(
    customer_ulid: str | None,
    sku_code: str | None,
    loc_code: str,
    actor_ulid: str | None,
    quantity: int,
):
    """
    Issue one unit from baseline stock:
      - picks first SKU at the location if --sku omitted
      - uses a throwaway ULID for the customer if none provided
    """
    echo_db_banner("demo-issue")

    from app.extensions import db
    from app.lib.chrono import now_iso8601_ms
    from app.lib.ids import new_ulid
    from app.slices.logistics.models import (
        InventoryBatch,
        InventoryItem,
        InventoryStock,
        Location,
    )
    from app.slices.logistics.services import issue_inventory

    loc = db.session.execute(
        select(Location).where(Location.code == loc_code)
    ).scalar_one_or_none()
    if not loc:
        raise SystemExit(f"Unknown location code: {loc_code}")

    # pick a SKU if not provided
    if not sku_code:
        pick = (
            db.session.execute(
                select(InventoryItem.sku)
                .distinct()
                .join(
                    InventoryStock,
                    InventoryStock.item_ulid == InventoryItem.ulid,
                )
                .where(
                    InventoryStock.location_ulid == loc.ulid,
                    InventoryStock.quantity > 0,
                )
                .order_by(InventoryItem.sku)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if not pick:
            raise SystemExit("No stock to issue at this location.")
        sku_code = pick

    # ensure there is a batch for that item at location (seed created one)
    it_ulid = db.session.execute(
        select(InventoryItem.ulid).where(InventoryItem.sku == sku_code)
    ).scalar_one_or_none()
    if not it_ulid:
        raise SystemExit(f"Unknown SKU: {sku_code}")

    batch_ulid = (
        db.session.execute(
            select(InventoryBatch.ulid)
            .where(
                InventoryBatch.item_ulid == it_ulid,
                InventoryBatch.location_ulid == loc.ulid,
            )
            .order_by(InventoryBatch.ulid.desc())
        )
        .scalars()
        .first()
    )
    if not batch_ulid:
        raise SystemExit(
            "No batch found for that SKU at the location (seed first)."
        )

    cust = customer_ulid or new_ulid()

    res = issue_inventory(
        customer_ulid=cust,
        sku_code=sku_code,
        quantity=quantity,
        when_iso=now_iso8601_ms(),
        project_ulid=None,
        actor_ulid=actor_ulid,
        location_ulid=loc.ulid,
        batch_ulid=batch_ulid,
    )

    if not res["ok"]:
        click.echo(f"DENIED: {res['reason']}")
        if "decision" in res:
            click.echo(f"decision={res['decision']}")
        return

    click.echo(f"OK movement={res['movement_ulid']}")
    click.echo(f"decision={res['decision']}")


# -----------------
# Issuance Ledger Trace
# -----------------


@dev_group.command("ledger-issuance-trace")
@with_appcontext
@click.option(
    "--customer-ulid", required=True, help="Customer ULID to issue to."
)
@click.option(
    "--sku-code", required=True, help="SKU code to issue (must have stock)."
)
@click.option(
    "--location-code",
    required=True,
    help="Location.code to issue from (e.g. MAIN, MAIN-A1-2).",
)
def dev_ledger_issuance_trace(
    customer_ulid: str,
    sku_code: str,
    location_code: str,
) -> None:
    """
    Issue a single item and show all ledger events generated for it.

    This is a dev-only trace tool:
      - resolves a Location by code (using Logistics ensure_location),
      - generates a correlation request_id,
      - calls Logistics decide_and_issue_one(...),
      - then queries the Ledger by that request_id and prints the events.

    Use this to understand “how many ledger events does one issuance create?”
    and which domains/operations are involved.
    """
    echo_db_banner("ledger-issuance-trace")

    from sqlalchemy import select

    from app.extensions import db
    from app.lib.ids import new_ulid
    from app.slices.logistics.issuance_services import decide_and_issue_one
    from app.slices.logistics.services import ensure_location

    # TODO: adjust this import to match your actual Ledger model path/name.
    # Common patterns in this project would be something like:
    #   from app.slices.ledger.models import LedgerEvent
    #
    # For now, assume LedgerEvent with fields:
    #   request_id, domain, operation, target_ulid, chain_key, happened_at_utc.
    try:
        from app.slices.ledger.models import LedgerEvent  # type: ignore
    except ImportError as e:  # pragma: no cover - dev helper
        click.echo(f"FATAL: could not import LedgerEvent: {e}", err=True)
        raise SystemExit(1)

    # Resolve location ULID by code (No-Garbage-In enforced via policy)
    loc_ulid = ensure_location(code=location_code, name=location_code)

    # Correlation id for this issuance
    req_id = new_ulid()
    click.echo(f"Using request_id={req_id}")

    # Do the issuance
    result = decide_and_issue_one(
        customer_ulid=customer_ulid,
        sku_code=sku_code,
        quantity=1,
        when_iso=None,
        project_ulid=None,
        actor_ulid=None,
        location_ulid=loc_ulid,
        batch_ulid=None,
        request_id=req_id,
    )

    click.echo(
        f"Decision: ok={result.get('ok')} reason={result.get('reason')} "
        f"movement_ulid={result.get('movement_ulid')}"
    )
    if not result.get("ok"):
        # If issuance failed, there may still be some ledger events (e.g. policy checks),
        # but usually far fewer.
        click.echo(
            "Issuance denied or failed; continuing to trace ledger events.\n"
        )

    # Fetch all ledger events for this request_id
    events = (
        db.session.execute(
            select(LedgerEvent)
            .where(LedgerEvent.request_id == req_id)
            .order_by(LedgerEvent.happened_at_utc)
        )
        .scalars()
        .all()
    )

    click.echo("")
    click.echo(f"Ledger events for request_id={req_id}: {len(events)}")
    if not events:
        click.echo("  (no events found)")
        return

    for ev in events:
        # Adjust attribute names if your LedgerEvent model uses different ones.
        click.echo(
            f"  - {ev.domain}.{ev.operation} "
            f"target={getattr(ev, 'target_ulid', None)} "
            f"chain={getattr(ev, 'chain_key', None)} "
            f"ts={getattr(ev, 'happened_at_utc', None)}"
        )


# -----------------
# Lint SKU's
# -----------------


@dev_group.command("lint-skus")
@with_appcontext
@click.option(
    "--data-dir", default="app/slices/logistics/data", show_default=True
)
def dev_lint_skus(data_dir: str):
    """Validate skus.json against sku.schema.json.
    Fails fast with row/field errors. No DB writes.
    """
    echo_db_banner("lint-skus")
    import json

    from app.lib.schema import try_validate_json

    schema_path = os.path.join(data_dir, "schemas/sku.schema.json")
    if not os.path.exists(schema_path):
        schema_path = os.path.join(data_dir, "sku.schema.json")
    skus_path = os.path.join(data_dir, "skus.json")

    if not os.path.exists(schema_path):
        raise SystemExit(f"Missing schema: {schema_path}")
    if not os.path.exists(skus_path):
        raise SystemExit(f"Missing data: {skus_path}")

    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    with open(skus_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    if not isinstance(rows, list):
        raise SystemExit("skus.json must be a JSON array.")

    errors = []
    for i, row in enumerate(rows, 1):
        ok, errs = try_validate_json(schema, row)
        if not ok:
            errors.append((i, row.get("sku"), errs))

    if errors:
        click.echo("FAIL — invalid SKUs found:")
        for i, sku, errs in errors:
            click.echo(f"  row #{i} sku={sku!s}: {errs}")
        raise SystemExit(1)

    click.echo(f"OK — {len(rows)} SKUs validated.")


# -----------------
# Purge Seeds
# -----------------


@dev_group.command("purge-seed-items")
@with_appcontext
def dev_purge_seed_items():
    """
    Delete legacy Logistics rows for items named 'Seed Item'
    in FK-safe order: issues → movements → stock → batches → items.
    """
    echo_db_banner("purge-seed-items")
    from sqlalchemy import delete

    from app.extensions import db
    from app.slices.logistics.models import (
        InventoryBatch,
        InventoryItem,
        InventoryMovement,
        InventoryStock,
        Issue,
    )

    seed_item_ulids = [
        ulid
        for (ulid,) in db.session.execute(
            select(InventoryItem.ulid).where(
                InventoryItem.name == "Seed Item"
            )
        ).all()
    ]
    if not seed_item_ulids:
        click.echo("No items named 'Seed Item' found. Nothing to do.")
        return

    # Find movements for those items
    mv_ulids = [
        ulid
        for (ulid,) in db.session.execute(
            select(InventoryMovement.ulid).where(
                InventoryMovement.item_ulid.in_(seed_item_ulids)
            )
        ).all()
    ]

    # 1) Issues referencing those movements
    if mv_ulids:
        db.session.execute(
            delete(Issue).where(Issue.movement_ulid.in_(mv_ulids))
        )

    # 2) Movements for those items
    db.session.execute(
        delete(InventoryMovement).where(
            InventoryMovement.item_ulid.in_(seed_item_ulids)
        )
    )

    # 3) Stock rows for those items
    db.session.execute(
        delete(InventoryStock).where(
            InventoryStock.item_ulid.in_(seed_item_ulids)
        )
    )

    # 4) Batches for those items
    db.session.execute(
        delete(InventoryBatch).where(
            InventoryBatch.item_ulid.in_(seed_item_ulids)
        )
    )

    # 5) Finally, the items
    db.session.execute(
        delete(InventoryItem).where(InventoryItem.ulid.in_(seed_item_ulids))
    )

    db.session.commit()
    click.echo(
        f"Purged {len(seed_item_ulids)} legacy item(s) named 'Seed Item' and their related rows."
    )


# -----------------
# Resource Capabilities
# -----------------


# (Optional) Handy viewer
@dev_group.command("list-capabilities")
@with_appcontext
def dev_list_capabilities():
    """Print canonical resource capability keys."""
    echo_db_banner("list-capabilities")
    from app.slices.resources import services as res_svc

    for k in res_svc.allowed_capabilities():
        click.echo(k)


# -----------------
# Sponsor Capabilities
# -----------------


@dev_group.command("list-sponsor-capabilities")
@with_appcontext
def dev_list_sponsor_capabilities():
    """Print canonical Sponsor capability keys if exposed by the services layer."""
    echo_db_banner("list-sponsor-capabilities")
    import click

    try:
        from app.slices.sponsors import services as ssvc  # type: ignore

        if hasattr(ssvc, "allowed_capabilities"):
            for k in ssvc.allowed_capabilities():
                click.echo(k)
            return
    except Exception:
        pass
    click.echo("No capability listing available for Sponsors.")
