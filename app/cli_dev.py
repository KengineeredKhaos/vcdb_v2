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
import re
from datetime import UTC
from pathlib import Path

import click

# Optional: read APP_MODE so we can gate dangerous actions
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import select

from app.cli import echo_db_banner
from app.extensions.errors import ContractError
from app.extensions.policy_health import PolicyError, policy_health_report
from app.slices.logistics.sku import (
    classification_key_for,
    parse_sku,
    validate_sku,
)


def register_cli(app):
    """Attach the 'dev' command group to Flask CLI."""
    app.cli.add_command(dev_group)


# # Semantics/health checks for policies
# try:
#     from app.extensions.policy_semantics import (
#         PolicyError,
#         policy_health_report,
#     )
# except Exception:  # still useful even if semantics module not present yet
#     PolicyError = RuntimeError

# def policy_health_report():
#     return (["policy_semantics module not available"], [])


@click.group("dev")
def dev_group():
    """Developer / Ops helpers (policy health, wiring checks, seed shims)."""


# -----------------
# CSRF Audit
# template POST
# -----------------


@dev_group.command("template-csrf-audit")
@with_appcontext
@click.option(
    "--strict",
    is_flag=True,
    help="Strict mode: require a csrf_field(...) call inside each POST form.",
)
@click.option(
    "--limit",
    type=int,
    default=200,
    show_default=True,
    help="Max offenders to print.",
)
def dev_template_csrf_audit(strict: bool, limit: int) -> None:
    """
    Scan templates for <form method="post"> blocks that appear to be missing CSRF.

    Heuristics:
      - Finds each <form ... method='post' ...> ... </form> block.
      - Flags it if the block lacks:
          * a csrf_field(...) call, OR
          * a hidden input named csrf_token, OR
          * a direct csrf_token() call, OR
          * form.hidden_tag() (FlaskForm)

    Exit codes:
      0 = OK
      1 = Missing CSRF detected

    flask --app manage_vcdb.py dev template-csrf-audit
    # optional:
    flask --app manage_vcdb.py dev template-csrf-audit --strict
    """
    echo_db_banner("template-csrf-audit")

    app_root = Path(current_app.root_path)  # .../app
    roots = [
        app_root / "templates",
        app_root / "slices",
    ]

    form_open = re.compile(
        r"<form\b[^>]*\bmethod\s*=\s*['\"]?post['\"]?[^>]*>",
        re.IGNORECASE,
    )
    form_close = re.compile(r"</form\s*>", re.IGNORECASE)

    if strict:
        # Enforce macro usage (macros.csrf_field(), forms.csrf_field(), etc.)
        csrf_ok = re.compile(r"\bcsrf_field\s*\(", re.IGNORECASE)
    else:
        # Accept either macro call or explicit token patterns.
        csrf_ok = re.compile(
            r"""
            \bcsrf_field\s*\(          |  # macros.csrf_field()
            name\s*=\s*["']csrf_token["'] |  # <input name="csrf_token" ...>
            \bcsrf_token\s*\(          |  # csrf_token()
            \bhidden_tag\s*\(             # form.hidden_tag()
            """,
            re.IGNORECASE | re.VERBOSE,
        )

    offenders: list[tuple[str, int]] = []
    scanned_files = 0
    scanned_forms = 0

    for root in roots:
        if not root.exists():
            continue

        for path in root.rglob("*.html"):
            scanned_files += 1
            text = path.read_text(encoding="utf-8", errors="ignore")

            for m in form_open.finditer(text):
                scanned_forms += 1
                close = form_close.search(text, m.end())
                if not close:
                    # malformed template; skip
                    continue

                block = text[m.start() : close.end()]
                if not csrf_ok.search(block):
                    # record 1-based line number for human-friendly grepping
                    line_no = text.count("\n", 0, m.start()) + 1
                    offenders.append((str(path), line_no))

    click.echo(f"Scanned templates: {scanned_files}")
    click.echo(f"Scanned POST forms: {scanned_forms}")

    if not offenders:
        click.secho("OK — no missing CSRF markers detected.", fg="green")
        return

    click.secho("FAIL — POST forms missing CSRF markers:", fg="red")
    for f, ln in offenders[:limit]:
        click.echo(f"  - {f}:{ln}")
    if len(offenders) > limit:
        click.echo(f"  ... and {len(offenders) - limit} more")

    raise SystemExit(1)


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
        # Normalize any miscategorized warning strings coming back in infos
        moved = [i for i in infos if i.strip().lower().startswith("warn:")]
        if moved:
            infos = [i for i in infos if i not in moved]
            warns.extend([i.split(":", 1)[1].strip() for i in moved])

    except PolicyError as e:
        click.echo(f"FATAL: {e}", err=True)
        raise SystemExit(1) from e

    # warnings shouldn’t fail CI by default;
    # change to nonzero if you want strict mode
    # raise SystemExit(0)

    # --- Issuance coverage report -----------------------------------------
    summary, per_rule = _scan_issuance_coverage()

    if as_json:
        click.echo(
            json.dumps(
                {
                    "infos": infos,
                    "warnings": warns,
                    "issuance": {
                        "default_behavior": summary["default_behavior"],
                        "catalog_total_items": summary["catalog_total_items"],
                        "customer_total_items": summary[
                            "customer_total_items"
                        ],
                        "durable_total_items": summary["durable_total_items"],
                        "matched_items": summary["matched_items"],
                        "unmatched_items": summary["unmatched_items"],
                        "rules_loaded": summary.get("rules_loaded", 0),
                        "per_rule": per_rule,
                        "unmatched_samples": summary["unmatched_samples"],
                        "durable_samples": summary.get("durable_samples", []),
                    },
                },
                indent=2,
            )
        )
        return

    for i in infos:
        click.echo(f"INFO: {i}")
    for w in warns:
        click.echo(f"WARN: {w}")

    click.echo("")
    click.echo(
        "Logistics issuance — sku_constraints.rules coverage over catalog"
    )
    click.echo(f"  default_behavior : {summary['default_behavior']}")
    click.echo(f"  catalog_total    : {summary['catalog_total_items']}")
    click.echo(f"  customer_total   : {summary['customer_total_items']}")
    click.echo(f"  matched_items    : {summary['matched_items']}")
    click.echo(f"  unmatched_items  : {summary['unmatched_items']}")

    if summary["unmatched_items"]:
        click.echo(
            "  unmatched samples: " + ", ".join(summary["unmatched_samples"])
        )
    click.echo("")
    click.echo(f"  catalog_total    : {summary['catalog_total_items']}")
    click.echo(f"  customer_total   : {summary['customer_total_items']}")
    click.echo(f"  rules_loaded    : {summary.get('rules_loaded', 0)}")
    if summary["customer_total_items"] and not summary.get("rules_loaded"):
        click.echo(
            "FATAL: issuance rules loaded == 0 while catalog has items"
        )
        raise SystemExit(1)

    if per_rule:
        click.echo("  per-rule match counts (first-match wins):")
        for r in per_rule:
            selector = r["selector"]
            click.echo(
                f"    #{r['index']:02}  {selector}  → {r['match_count']}"
            )
    else:
        click.echo("  (no rules loaded)")
    click.echo("")
    click.echo(
        "Durable goods (issuance_class D) — excluded from customer issuance coverage"
    )
    click.echo(f"  total_items      : {summary['durable_total_items']}")
    if summary["durable_total_items"]:
        click.echo(
            "  samples          : " + ", ".join(summary["durable_samples"])
        )
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

    Print a compact summary of Logistics locations (slice data) vs DB usage.

    This is intentionally *slice-local* (not Governance):
      - explicit locations live in slices/logistics/data/locations.json
      - rack/bin pattern lives in logistics.taxonomy.RACKBIN_PATTERN
    """
    import json
    import re
    from pathlib import Path

    from app.extensions import db
    from app.slices.logistics import taxonomy as log_tax
    from app.slices.logistics.models import Location

    data_path = (
        Path(current_app.root_path)
        / "slices"
        / "logistics"
        / "data"
        / "locations.json"
    )

    loc_specs: list[dict] = []
    if data_path.exists():
        try:
            raw = json.loads(data_path.read_text(encoding="utf-8"))
            loc_specs = list(raw.get("locations") or [])
        except Exception as exc:
            click.echo(f"WARN: failed to read locations.json: {exc}")

    allowed_codes = {
        str(spec.get("code")) for spec in loc_specs if spec.get("code")
    }

    rackbin_pattern = re.compile(log_tax.RACKBIN_PATTERN)

    click.echo("Locations — slice data vs DB")
    click.echo("----------------------------")
    click.echo(
        f"kinds (allowed): {', '.join(log_tax.LOCATION_KINDS) or '(none)'}"
    )
    click.echo(
        f"locations.json : {data_path if data_path.exists() else '(missing)'}"
    )
    click.echo("explicit locations:")
    if not loc_specs:
        click.echo("  (none)")
    else:
        for spec in loc_specs:
            click.echo(
                f"  - code={spec.get('code', '')!r:10s}  "
                f"kind={spec.get('kind', '?'):10s}  "
                f"name={spec.get('name', '')}"
            )
    click.echo(f"rackbin pattern: {log_tax.RACKBIN_PATTERN}")
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
            flag = "  (! not in locations.json)"
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
    default="all",
    show_default=True,
    help="all | policy_key (from governance_index) | alias: issuance, eligibility",
)
@click.option(
    "--fix",
    is_flag=True,
    help="Rewrite policy JSON with canonical formatting (sorted keys, 2-space indent)",
)
@click.option(
    "--base",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    help="Override the policies base directory (folder that contains policy_governance_index.json)",
)
@click.option(
    "--schema-base",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    help="Override the schema base directory (root used to resolve schema_filename paths)",
)
@click.option("--print-paths", is_flag=True, help="Print resolved file paths")
def dev_policy_lint(
    which, fix, base: Path | None, schema_base: Path | None, print_paths: bool
):
    """
    Validate governance policy JSON files against their schemas (Policy Catalog v2).
    On --fix, pretty-print and sort keys so diffs stay clean.
    """
    echo_db_banner("policy-lint")
    import json

    from flask import current_app
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError

    from app.extensions.validate import load_json, load_json_schema

    # -------- resolve base --------
    app_root = Path(current_app.root_path)
    resolved_base = base or (app_root / "slices" / "governance" / "data")
    if not resolved_base.exists():
        click.secho(
            f"ERROR: policies base directory not found: {resolved_base}",
            fg="red",
        )
        raise SystemExit(1)

    manifest_path = resolved_base / "policy_governance_index.json"
    if not manifest_path.exists():
        click.secho("ERROR: policy manifest not found:", fg="red")
        click.echo(f"  expected: {manifest_path}")
        raise SystemExit(1)

    # schema_base is a *root* for resolving schema_filename. Default to resolved_base,
    # because schema_filename already includes "schemas/..." in the manifest.
    schema_root = schema_base or resolved_base

    click.secho(f"[policy-lint] base={resolved_base}", fg="cyan")
    click.secho(f"[policy-lint] schema_root={schema_root}", fg="cyan")

    # -------- load manifest --------
    manifest = load_json(manifest_path)
    entries = manifest.get("policies") or []
    by_key = {e.get("policy_key"): e for e in entries if e.get("policy_key")}

    if not by_key:
        click.secho("ERROR: manifest has no policies[] entries.", fg="red")
        raise SystemExit(1)

    # -------- selection / aliases --------
    alias_map = {
        # legacy CLI groups
        "issuance": ["logistics_issuance"],
        "eligibility": ["entity_roles"],
        "all": list(by_key.keys()),
    }

    if which in alias_map:
        selected_keys = alias_map[which]
    else:
        # treat as explicit policy_key
        selected_keys = [which]

    missing_keys = [k for k in selected_keys if k not in by_key]
    if missing_keys:
        click.secho("ERROR: unknown policy_key(s):", fg="red")
        for k in missing_keys:
            click.echo(f"  - {k}")
        click.echo("Available policy_key values (from manifest):")
        for k in sorted(by_key.keys()):
            click.echo(f"  - {k}")
        raise SystemExit(1)

    # -------- helper: resolve schema path robustly --------
    def _resolve_schema(schema_filename: str) -> Path:
        rel = Path(schema_filename)

        # 1) schema_root / rel  (works when schema_root is the policy base)
        p1 = schema_root / rel
        if p1.exists():
            return p1

        # 2) schema_root / basename  (works when schema_root points directly at ./schemas)
        p2 = schema_root / rel.name
        if p2.exists():
            return p2

        # 3) resolved_base / rel  (backup)
        p3 = resolved_base / rel
        if p3.exists():
            return p3

        # 4) resolved_base / "schemas" / basename (backup)
        p4 = resolved_base / "schemas" / rel.name
        if p4.exists():
            return p4

        return p1  # return best guess for printing

    # -------- validate --------
    had_error = False

    for key in selected_keys:
        entry = by_key[key]
        fname = entry["filename"]
        sname = entry["schema_filename"]

        fpath = resolved_base / fname
        spath = _resolve_schema(sname)

        if print_paths:
            click.echo(f"{key:18s} json   : {fpath}")
            click.echo(f"{'':18s} schema : {spath}")
            click.echo("")

        missing = []
        if not fpath.exists():
            missing.append(f"policy:  {fpath}")
        if not spath.exists():
            missing.append(f"schema:  {spath}")

        if missing:
            had_error = True
            click.secho(f"FAIL — {key} missing files:", fg="red")
            for m in missing:
                click.echo(f"  - {m}")
            continue

        try:
            payload = load_json(fpath)

            # extra drift check: policy meta.policy_key must match manifest policy_key
            meta_key = (payload.get("meta") or {}).get("policy_key")
            if meta_key and meta_key != key:
                had_error = True
                click.secho(
                    f"FAIL — {key} meta.policy_key mismatch:", fg="red"
                )
                click.echo(f"  manifest key: {key}")
                click.echo(f"  file meta.policy_key: {meta_key}")
                continue

            schema = load_json_schema(spath)
            Draft202012Validator(schema).validate(payload)

            click.secho(f"OK — {key} valid: {fname}", fg="green")

            if fix:
                text = json.dumps(
                    payload, indent=2, sort_keys=True, ensure_ascii=False
                )
                fpath.write_text(text + "\n", encoding="utf-8")

        except ValidationError as e:
            had_error = True
            click.secho(f"FAIL — {key} schema validation error:", fg="red")
            click.echo(f"  message: {e.message}")
            if e.absolute_path:
                click.echo(
                    "  path:    /" + "/".join(str(p) for p in e.absolute_path)
                )
        except Exception as e:
            had_error = True
            click.secho(f"FAIL — {key} error:", fg="red")
            click.echo(f"  {type(e).__name__}: {e}")

    if had_error:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Issuance CLI spine (Policy Catalog v2)
# One place to:
#   - load issuance policy (v2 shape)
#   - derive SKU facts
#   - build a rule-match ctx that _rule_matches can actually use
# ---------------------------------------------------------------------------


def _issuance_policy_v2():
    """
    Return (default_behavior, issuance_defaults, sku_constraint_rules) for logistics_issuance.

    IMPORTANT: Logistics’ matcher `_rule_matches()` operates on `sku_constraints.rules`
    entries shaped like {"match": {...}, ...}. The `issuance.rules` list is a different
    family (if/then constraints) and is validated elsewhere.
    """
    from app.extensions.policies import load_policy_logistics_issuance

    doc = load_policy_logistics_issuance() or {}
    issuance = doc.get("issuance") or {}
    sku_constraints = doc.get("sku_constraints") or {}

    defaults = issuance.get("defaults") or {}
    rules = list(sku_constraints.get("rules") or [])

    default_behavior = (
        doc.get("default_behavior")
        or issuance.get("default_behavior")
        or defaults.get("behavior")
        or "deny"
    )
    return str(default_behavior).lower(), defaults, rules


def _sku_facts_from_code(sku_code: str) -> dict:
    """
    Extract facts from SKU code using the canonical segment format:
      CAT-SUB-SRC-SIZE-COLOR-CLASS-SEQ
    """
    segs = sku_code.split("-")
    cat = segs[0] if len(segs) > 0 else None
    sub = segs[1] if len(segs) > 1 else None
    src = segs[2] if len(segs) > 2 else None
    size = segs[3] if len(segs) > 3 else None
    color = segs[4] if len(segs) > 4 else None
    issuance_class = segs[5] if len(segs) > 5 else None
    seq = segs[6] if len(segs) > 6 else None

    classification = f"{cat}/{sub}" if cat and sub else None

    return {
        "category": cat,
        "subcategory": sub,
        "source": src,
        "size": size,
        "color": color,
        "issuance_class": issuance_class,
        "seq": seq,
        "classification": classification,
    }


def _issuance_match_ctx(
    sku_code: str,
    *,
    when_iso: str | None = None,
    project_ulid: str | None = None,
    customer_ulid: str | None = None,
):
    """
    Build the Logistics IssueContext required by `_rule_matches()`.
    """
    from app.slices.logistics.issuance_services import IssueContext
    from app.slices.logistics.sku import classification_key_for, parse_sku

    return IssueContext(
        customer_ulid=customer_ulid,
        sku_code=sku_code,
        when_iso=when_iso,
        project_ulid=project_ulid,
        sku_parts=parse_sku(sku_code),
        classification_key=classification_key_for(sku_code),
    )


# -----------------
# issuance coverage
# helpers
# -----------------


def _scan_issuance_coverage():
    """
    Scan InventoryItem SKUs and count first-match rule hits.
    Items with no rule match are 'denied by default' (default_behavior).
    """
    from sqlalchemy import select

    from app.extensions import db
    from app.slices.logistics.issuance_services import _rule_matches
    from app.slices.logistics.models import InventoryItem
    from app.slices.logistics.sku import parse_sku

    default_behavior, defaults, rules = _issuance_policy_v2()
    rules_loaded = len(rules)
    durable_total = 0
    durable_samples: list[str] = []

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
    unmatched_samples: list[str] = []

    for sku_code in rows:
        parts = parse_sku(sku_code)
        if parts.get("issuance_class") == "D":
            durable_total += 1
            if len(durable_samples) < 10:
                durable_samples.append(sku_code)
            continue

        ctx = _issuance_match_ctx(sku_code)

        hit = False
        for i, rule in enumerate(rules):
            if _rule_matches(rule, ctx):
                per_rule[i]["match_count"] += 1
                hit = True
                break

        if hit:
            matched_any += 1
        elif len(unmatched_samples) < 10:
            unmatched_samples.append(sku_code)

    catalog_total = len(rows)
    customer_total = catalog_total - durable_total
    customer_unmatched = customer_total - matched_any

    summary = {
        # totals (explicitly separated)
        "catalog_total_items": catalog_total,  # all InventoryItem rows
        "customer_total_items": customer_total,  # catalog minus durables
        "durable_total_items": durable_total,
        # customer-issuance coverage only (durables excluded)
        "matched_items": matched_any,
        "unmatched_items": customer_unmatched,
        "default_behavior": default_behavior,
        "rules_loaded": rules_loaded,
        "defaults": defaults,
        "unmatched_samples": unmatched_samples,
        # durable samples (for reporting)
        "durable_samples": durable_samples,
    }
    return summary, per_rule


# -----------------
# Print SKU coverage
# -----------------


def _print_sku_policy_summary() -> None:
    """
    Print a compact summary of Logistics SKU taxonomy vs DB usage.

    This is intentionally *slice-local* (not Governance):
      - allowed_units / allowed_sources live in logistics.taxonomy
      - we compare those to InventoryItem.unit and SKU source usage
    """
    from collections import Counter

    from sqlalchemy import func, select

    from app.extensions import db
    from app.slices.logistics import taxonomy as log_tax
    from app.slices.logistics.models import InventoryItem
    from app.slices.logistics.sku import parse_sku

    allowed_units = set(log_tax.ALLOWED_UNITS)
    allowed_sources = set(log_tax.ALLOWED_SOURCES)

    click.echo("SKU constraints — taxonomy vs catalog")
    click.echo("-----------------------------------")
    click.echo(
        f"allowed_units   : {', '.join(sorted(allowed_units)) or '(none)'}"
    )
    click.echo(
        f"allowed_sources : {', '.join(sorted(allowed_sources)) or '(none)'}"
    )
    click.echo("")

    unit_rows = db.session.execute(
        select(InventoryItem.unit, func.count())
        .group_by(InventoryItem.unit)
        .order_by(InventoryItem.unit)
    ).all()

    if not unit_rows:
        click.echo("InventoryItem units (DB) : (no items)")
        return

    click.echo("InventoryItem units (DB usage):")
    bad_units: list[str] = []
    for unit, count in unit_rows:
        flag = ""
        if unit not in allowed_units:
            flag = "  (! not allowed)"
            bad_units.append(unit)
        click.echo(f"  {unit!r:10s}  {count:5d}{flag}")

    if bad_units:
        click.echo("")
        click.echo("WARN: units present in DB but not allowed by taxonomy:")
        for u in sorted(set(bad_units)):
            click.echo(f"  - {u!r}")

    # Also show SKU 'source' usage (best-effort, first 10 unknowns).
    sku_rows = db.session.execute(select(InventoryItem.sku)).scalars().all()
    src_counts: Counter[str] = Counter()
    bad_skus: list[str] = []

    for sku_code in sku_rows:
        try:
            parts = parse_sku(sku_code)
        except Exception:
            if len(bad_skus) < 10:
                bad_skus.append(sku_code)
            continue
        src = parts.get("source")
        if src:
            src_counts[str(src)] += 1

    click.echo("")
    click.echo("SKU sources (DB usage):")
    if not src_counts and not bad_skus:
        click.echo("  (no items)")
        return

    bad_sources: list[str] = []
    for src in sorted(src_counts.keys()):
        count = src_counts[src]
        flag = ""
        if src not in allowed_sources:
            flag = "  (! not allowed)"
            bad_sources.append(src)
        click.echo(f"  {src!r:6s}  {count:5d}{flag}")

    if bad_skus:
        click.echo("")
        click.echo("WARN: InventoryItem.sku values that failed parse_sku():")
        for sku in bad_skus:
            click.echo(f"  - {sku!r}")

    if bad_sources:
        click.echo("")
        click.echo("WARN: sources present in DB but not allowed by taxonomy:")
        for s in sorted(set(bad_sources)):
            click.echo(f"  - {s!r}")


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
@with_appcontext
@click.option("--sku", "sku_code", required=True, help="SKU code")
@click.option(
    "--customer-ulid",
    default=None,
    help="Optional customer ULID for qualifier checks",
)
@click.option("--when-iso", default=None, help="ISO time (defaults to now)")
@click.option("--project-ulid", default=None, help="Optional project ULID")
def dev_issuance_debug(
    sku_code: str,
    customer_ulid: str | None,
    when_iso: str | None,
    project_ulid: str | None,
):
    """Debug SKU constraint matching (sku_constraints.rules) and (optionally) a full policy decision."""
    from app.lib.chrono import now_iso8601_ms
    from app.slices.logistics.issuance_services import (
        _rule_matches,
        decide_issue,
    )

    echo_db_banner("issuance-debug")

    if when_iso is None:
        when_iso = now_iso8601_ms()

    default_behavior, defaults, rules = _issuance_policy_v2()

    ctx = _issuance_match_ctx(
        sku_code,
        when_iso=when_iso,
        project_ulid=project_ulid,
        customer_ulid=customer_ulid,
    )

    click.echo(f"SKU: {sku_code}")
    click.echo(f"default_behavior: {default_behavior}")
    click.echo("")

    # --- sku_constraints.rules matching ---
    click.echo("sku_constraints.rules matches (first-match wins):")
    hit_any = False
    for i, rule in enumerate(rules, start=1):
        if _rule_matches(rule, ctx):
            hit_any = True
            click.echo(f"  HIT #{i:02}: {rule.get('match')}")
            if rule.get("qualifiers"):
                click.echo(f"       qualifiers: {rule['qualifiers']}")
            if rule.get("cadence"):
                click.echo(f"       cadence: {rule['cadence']}")
            break
    if not hit_any:
        click.echo("  (no rule matched)")

    # --- optional full decision ---
    click.echo("")
    click.echo(
        "decide_issue(...) (may require a real customer_ulid depending on qualifier logic):"
    )
    try:
        # decide_issue in your codebase expects extra fields beyond IssueContext;
        # keep this conservative by passing a lightweight namespace-shaped object.
        from types import SimpleNamespace

        ctx2 = SimpleNamespace(
            customer_ulid=customer_ulid,
            sku_code=ctx.sku_code,
            classification_key=ctx.classification_key,
            sku_parts=ctx.sku_parts,
            when_iso=when_iso,
            project_ulid=project_ulid,
            force_blackout=False,
            qualifiers={},
            defaults_cadence=(defaults or {}).get("cadence"),
        )
        d = decide_issue(ctx2)
        click.echo(
            f"  allowed={getattr(d, 'allowed', None)} reason={getattr(d, 'reason', None)}"
        )
    except Exception as e:
        click.echo(f"  (decision skipped/failed) {type(e).__name__}: {e}")


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
    from datetime import datetime, timedelta
    from types import SimpleNamespace as NS

    import click

    from app.extensions.policies import load_governance_policy
    from app.lib.ids import new_ulid
    from app.slices.logistics.issuance_services import (
        decide_issue,
    )
    from app.slices.logistics.services import (
        ensure_location,
    )
    from app.slices.logistics.sku import (
        classification_key_for,
        parse_sku,
    )

    # ---- load v2 issuance policy (canonical) ----
    doc = load_governance_policy("logistics_issuance")
    issuance = doc.get("issuance") or {}
    defaults = issuance.get("defaults") or {}
    rules = list(issuance.get("rules") or [])
    defaults_cadence = defaults.get("cadence")

    if not rules:
        click.echo("No issuance rules loaded.")
        return

    # Ensure location exists (and capture ulid once)
    loc_ulid = ensure_location(code=location, name=location)

    # ---- ensure a test customer (minimal person entity -> customer) ----
    if not customer_ulid:
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

    # ---- helper: mutate eligibility flags on the customer ----
    def set_flags(
        veteran: bool | None = None, homeless: bool | None = None
    ) -> None:
        from app.slices.customers.services import set_verification_flags

        set_verification_flags(
            customer_ulid=customer_ulid,
            veteran=veteran,
            homeless=homeless,
        )

    # ---- helper: call decide_issue with a constructed ctx (no DB writes) ----
    def eval_ctx(
        sku_code: str, when_iso: str, force_blackout_flag: bool = False
    ):
        ctx = NS(
            customer_ulid=customer_ulid,
            sku_code=sku_code,
            classification_key=classification_key_for(sku_code),
            sku_parts=parse_sku(sku_code),
            when_iso=when_iso,
            project_ulid=None,
            force_blackout=force_blackout_flag,
            qualifiers={},
            defaults_cadence=defaults_cadence,
        )
        return decide_issue(ctx)

    # ---- blackout helpers (best effort; safe fallbacks) ----
    def _iso(d: datetime) -> str:
        return (
            d.replace(tzinfo=UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )

    def _next_weekday_noon_utc(target_wd: int) -> str:
        now = datetime.now(UTC)
        days_ahead = (target_wd - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        dt = (now + timedelta(days=days_ahead)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        return _iso(dt)

    def _blackout_when_from_calendar() -> str | None:
        """
        Best-effort: pull blackout rules from slice-local Calendar data.

        Governance no longer owns operations/calendar taxonomy.
        If calendar data isn't present yet, return None and the caller
        will fall back to a deterministic "next Saturday" timestamp.
        """
        try:
            from pathlib import Path

            app_root = Path(current_app.root_path)
            cal_path = (
                app_root / "slices" / "calendar" / "data" / "projects.json"
            )
            if not cal_path.exists():
                return None

            raw = json.loads(cal_path.read_text(encoding="utf-8"))
            projects = raw.get("projects") or {}

            wd_map = {
                "MON": 0,
                "TUE": 1,
                "WED": 2,
                "THU": 3,
                "FRI": 4,
                "SAT": 5,
                "SUN": 6,
            }

            for _pid, pdata in projects.items():
                for rule in pdata.get("blackout_rules", []):
                    t = (rule.get("type") or "").lower()
                    if t == "date_range" and rule.get("start"):
                        try:
                            start = datetime.fromisoformat(rule["start"])
                        except Exception:
                            continue
                        dt = datetime(
                            start.year,
                            start.month,
                            start.day,
                            12,
                            0,
                            0,
                            tzinfo=UTC,
                        )
                        return _iso(dt)
                    if t == "weekday" and rule.get("days"):
                        for day in rule["days"]:
                            wd = wd_map.get(str(day).upper())
                            if wd is not None:
                                return _next_weekday_noon_utc(wd)
            return None
        except Exception:
            return None

    blackout_when = _blackout_when_from_calendar() or _next_weekday_noon_utc(
        5
    )  # next Saturday noon UTC

    #


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
    from app.slices.logistics.issuance_services import decide_issue

    try:
        parts = parse_sku(sku_code)
    except ValueError as e:
        click.echo(f"Invalid SKU '{sku_code}': {e}")
        raise SystemExit(1) from e

    if when_iso is None:
        when_iso = now_iso8601_ms()

    ckey = classification_key_for(sku_code)

    default_behavior, defaults, _rules = _issuance_policy_v2()

    ctx = SimpleNamespace(
        customer_ulid=customer_ulid,
        sku_code=sku_code,
        classification_key=ckey,
        sku_parts=parts,
        when_iso=when_iso,
        project_ulid=project_ulid,
        force_blackout=force_blackout,
        qualifiers={},
        defaults_cadence=(defaults or {}).get("cadence"),
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
    click.echo(f"APP_MODE={cfg.get('APP_MODE', 'unknown')}")
    click.echo(f"DB_URI={cfg.get('SQLALCHEMY_DATABASE_URI', '?')}")


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
# Issuance Policy Check (demo)
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
    help="If omitted, picks the first available SKU at the location.",
)
@click.option(
    "--location",
    "loc_code",
    default="MAIN",
    show_default=True,
    help="Location.code to issue from (e.g. MAIN, MAIN-A1-2).",
)
@click.option(
    "--actor-ulid",
    default=None,
    help="Actor ULID (if omitted, generates one for dev tracing).",
)
@click.option("--quantity", type=int, default=1, show_default=True)
@click.option(
    "--request-id",
    default=None,
    help="Optional correlation id (if omitted, generates one).",
)
def dev_demo_issue(
    customer_ulid: str | None,
    sku_code: str | None,
    loc_code: str,
    actor_ulid: str | None,
    quantity: int,
    request_id: str | None,
):
    """
    Issue one unit from baseline stock:
      - picks first SKU at the location if --sku omitted
      - uses a throwaway ULID for the customer if none provided
      - always uses a request_id so you can trace ledger events
    """
    echo_db_banner("demo-issue")

    if quantity <= 0:
        raise SystemExit("--quantity must be >= 1")

    from sqlalchemy import select

    from app.extensions import db
    from app.lib.chrono import now_iso8601_ms
    from app.lib.ids import new_ulid
    from app.slices.logistics.issuance_services import decide_and_issue_one
    from app.slices.logistics.models import (
        InventoryBatch,
        InventoryItem,
        InventoryStock,
        Location,
    )

    # ---- resolve location ----
    loc = db.session.execute(
        select(Location).where(Location.code == loc_code)
    ).scalar_one_or_none()
    if not loc:
        raise SystemExit(f"Unknown location code: {loc_code}")

    # ---- pick a SKU if not provided ----
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
                    InventoryStock.quantity >= quantity,
                )
                .order_by(InventoryItem.sku)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if not pick:
            raise SystemExit(
                f"No stock to issue at location {loc_code} (need qty={quantity})."
            )
        sku_code = pick

    # ---- resolve item ulid ----
    it_ulid = db.session.execute(
        select(InventoryItem.ulid).where(InventoryItem.sku == sku_code)
    ).scalar_one_or_none()
    if not it_ulid:
        raise SystemExit(f"Unknown SKU: {sku_code}")

    # ---- pick/resolve batch at that location with enough qty ----
    batch_ulid = (
        db.session.execute(
            select(InventoryBatch.ulid)
            .where(
                InventoryBatch.item_ulid == it_ulid,
                InventoryBatch.location_ulid == loc.ulid,
                InventoryBatch.qty_each >= quantity,
            )
            .order_by(InventoryBatch.ulid.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if not batch_ulid:
        raise SystemExit(
            f"No batch with qty_each >= {quantity} for SKU={sku_code} at location={loc_code}."
        )

    cust = customer_ulid or new_ulid()
    actor = actor_ulid or new_ulid()
    req_id = request_id or new_ulid()

    res = decide_and_issue_one(
        customer_ulid=cust,
        sku_code=sku_code,
        quantity=quantity,
        when_iso=now_iso8601_ms(),
        project_ulid=None,
        actor_ulid=actor,
        location_ulid=loc.ulid,
        batch_ulid=batch_ulid,
        request_id=req_id,
        reason="dev_demo_issue",
        note=None,
    )

    click.echo("")
    click.echo(f"request_id={req_id}")
    click.echo(f"customer_ulid={cust}")
    click.echo(f"actor_ulid={actor}")
    click.echo(f"location={loc.code} ({loc.ulid})")
    click.echo(f"sku={sku_code} qty={quantity}")

    if not res.get("ok"):
        click.secho(f"DENIED: {res.get('reason')}", fg="red")
        if "decision" in res:
            click.echo(f"decision={res['decision']}")
        return

    click.secho("OK", fg="green")
    click.echo(f"movement_ulid={res.get('movement_ulid')}")
    click.echo(f"decision={res.get('decision')}")


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
@click.option(
    "--actor-ulid",
    default=None,
    help="Actor ULID (if omitted, generates one for dev tracing).",
)
def dev_ledger_issuance_trace(
    customer_ulid: str,
    sku_code: str,
    location_code: str,
    actor_ulid: str | None,
) -> None:
    """
    Issue a single item and show all *Ledger slice* events generated for it,
    correlated by request_id.
    """
    echo_db_banner("ledger-issuance-trace")

    from sqlalchemy import select

    from app.extensions import db
    from app.lib.chrono import now_iso8601_ms
    from app.lib.ids import new_ulid
    from app.slices.logistics.issuance_services import decide_and_issue_one
    from app.slices.logistics.models import InventoryBatch, InventoryItem
    from app.slices.logistics.services import ensure_location

    # Ledger slice model import (adjust if your model name differs)
    try:
        from app.slices.ledger.models import LedgerEvent  # type: ignore
    except ImportError as e:
        click.echo(
            f"FATAL: could not import LedgerEvent from ledger slice: {e}",
            err=True,
        )
        raise SystemExit(1) from e

    # Resolve (or create) location ULID
    loc_ulid = ensure_location(code=location_code, name=location_code)

    # Resolve item_ulid
    it_ulid = db.session.execute(
        select(InventoryItem.ulid).where(InventoryItem.sku == sku_code)
    ).scalar_one_or_none()
    if not it_ulid:
        raise SystemExit(f"Unknown SKU: {sku_code}")

    # Pick a batch at the location with stock
    batch_ulid = (
        db.session.execute(
            select(InventoryBatch.ulid)
            .where(
                InventoryBatch.item_ulid == it_ulid,
                InventoryBatch.location_ulid == loc_ulid,
                InventoryBatch.qty_each >= 1,
            )
            .order_by(InventoryBatch.ulid.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if not batch_ulid:
        raise SystemExit(
            f"No batch with qty_each >= 1 for SKU={sku_code} at location={location_code}."
        )

    req_id = new_ulid()
    actor = actor_ulid or new_ulid()

    click.echo(f"Using request_id={req_id}")
    click.echo(f"actor_ulid={actor}")

    res = decide_and_issue_one(
        customer_ulid=customer_ulid,
        sku_code=sku_code,
        quantity=1,
        when_iso=now_iso8601_ms(),
        project_ulid=None,
        actor_ulid=actor,
        location_ulid=loc_ulid,
        batch_ulid=batch_ulid,
        request_id=req_id,
        reason="dev_ledger_issuance_trace",
        note=None,
    )

    click.echo(
        f"Result: ok={res.get('ok')} reason={res.get('reason')} movement_ulid={res.get('movement_ulid')}"
    )
    if res.get("decision") is not None:
        click.echo(f"decision={res.get('decision')}")

    # Fetch all ledger events for this request_id
    order_col = getattr(LedgerEvent, "happened_at_utc", None) or getattr(
        LedgerEvent, "happened_at", None
    )

    q = select(LedgerEvent).where(LedgerEvent.request_id == req_id)
    if order_col is not None:
        q = q.order_by(order_col)

    events = db.session.execute(q).scalars().all()

    click.echo("")
    click.echo(f"Ledger events for request_id={req_id}: {len(events)}")
    if not events:
        click.echo("  (no events found)")
        return

    for ev in events:
        click.echo(
            f"  - {getattr(ev, 'domain', None)}.{getattr(ev, 'operation', None)} "
            f"target={getattr(ev, 'target_ulid', None)} "
            f"ts={getattr(ev, 'happened_at_utc', None) or getattr(ev, 'happened_at', None)}"
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

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    with open(skus_path, encoding="utf-8") as f:
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


# -----------------
# Sponsor/Calendar/Finance
# flow test
# -----------------


@dev_group.command("sponsor-allocation-spend")
@with_appcontext
@click.option("--allocation-ulid", required=True, help="Allocation ULID")
@click.option(
    "--amount-cents",
    type=int,
    default=None,
    help="Amount in cents (default: full allocation)",
)
@click.option(
    "--occurred-on",
    default=None,
    help="ISO timestamp; default is now in UTC if omitted",
)
@click.option(
    "--category",
    default="allocation_spend",
    help="Expense category (default: allocation_spend)",
)
@click.option(
    "--vendor",
    default=None,
    help="Override vendor/payee (default: sponsor name)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Simulate only; do not write Journal rows",
)
@with_appcontext
def sponsor_allocation_spend_cmd(
    allocation_ulid: str,
    amount_cents: int | None,
    occurred_on: str | None,
    category: str,
    vendor: str | None,
    dry_run: bool,
) -> None:
    """Dev helper to exercise Sponsors → Finance allocation spending."""
    echo_db_banner("sponsor-allocation-spend")
    from app.extensions.contracts import sponsors_v2

    try:
        result = sponsors_v2.allocation_spend(
            allocation_ulid=allocation_ulid,
            amount_cents=amount_cents,
            occurred_on=occurred_on,
            category=category,
            vendor=vendor,
            actor_ulid=None,
            dry_run=dry_run,
        )
    except ContractError as exc:
        import click

        click.echo(f"ERROR: {exc.code}: {exc.message}")
        raise SystemExit(1) from exc

    import click

    click.echo(f"Dry run:        {result['dry_run']}")
    click.echo(f"Allocation ULID: {result['allocation_ulid']}")
    click.echo(f"Journal ULID:    {result['journal_id']}")
    click.echo(f"Amount cents:    {result['amount_cents']}")
