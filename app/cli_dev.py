# Dev/ops utilities — helpers for local workflows, policy checks, smoke tests.
# Safe to ship; nothing runs unless invoked.
# Keep prod side-effects behind guards.

from __future__ import annotations

import json
import os
from pathlib import Path

import click

# Optional: read APP_MODE so we can gate dangerous actions
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import select


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
    ...


# -----------------
# Generic Helpers
# for dev_group
# commands
# -----------------


def _print_json_error(e: Exception, fname: str) -> None:
    """
    Pretty-print JSON Schema validation errors with the instance path and schema path.
    """
    import click

    try:
        import jsonschema
    except Exception:  # pragma: no cover
        click.secho(f"ERR  — {fname}: {e!r}", fg="red")
        return

    if isinstance(e, jsonschema.ValidationError):
        # JSON Pointer-ish path to the offending location in the instance
        instance_path = (
            "/" + "/".join(str(p) for p in e.absolute_path)
            if e.absolute_path
            else "$"
        )
        schema_path = (
            "/" + "/".join(str(p) for p in e.absolute_schema_path)
            if e.absolute_schema_path
            else "$"
        )

        click.secho(f"FAIL — {fname}", fg="red")
        click.echo(f"  at     : {instance_path}")
        click.echo(f"  error  : {e.message}")
        click.echo(f"  schema : {schema_path}")
        # Show a tiny bit of context if available
        if e.context:
            click.echo("  details:")
            for sub in e.context[:3]:
                click.echo(f"    - {sub.message}")
    else:
        click.secho(f"ERR  — {fname}: {e!r}", fg="red")


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
    from app.extensions import db
    from app.slices.logistics.models import InventoryItem, Issue
    from app.slices.logistics.sku import parse_sku, validate_sku

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

    from sqlalchemy import select

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
            classification_key="-".join(code.split("-")[:2]),
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


# -----------------
# Issuance Debugger
# -----------------


@dev_group.command("issuance-debug")
@with_appcontext
@click.option("--sku", "sku_code", required=True)
def dev_issuance_debug(sku_code: str):
    """
    Print gate-by-gate decision for one SKU using default_behavior
    & current policies.
    """
    from types import SimpleNamespace as NS

    from app.extensions.policies import load_policy_issuance
    from app.lib.chrono import now_iso8601_ms
    from app.slices.governance.services import _rule_matches, decide_issue
    from app.slices.logistics.sku import parse_sku

    ctx = NS(
        customer_ulid="DEBUG",
        sku_code=sku_code,
        classification_key="-".join(sku_code.split("-")[:2]),
        sku_parts=parse_sku(sku_code),
        when_iso=now_iso8601_ms(),
        project_ulid=None,
        qualifiers={},  # will be set inside decide_issue for matched rules
        defaults_cadence=None,
    )

    pol = load_policy_issuance()
    print(f"default_behavior = {pol.get('default_behavior','deny')}")
    print("rule matches:")
    for i, r in enumerate(pol.get("rules", []), 1):
        print(f"  #{i:02}  {_rule_matches(r, ctx)}  {r.get('match')}")

    dec = decide_issue(ctx)
    print("decision =", dec)


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
@click.option("--location", default="LOC-MAIN", show_default=True)
@click.option(
    "--per-sku",
    type=int,
    default=2,
    show_default=True,
    help="Units to receive per fabricated SKU.",
)
def dev_issuance_tripwires(
    customer_ulid: str | None, location: str, per_sku: int
):
    """
    For each issuance policy rule:
      - find or fabricate a matching SKU,
      - run: blackout, qualifiers-missing, qualifiers-satisfied, cadence trip,
      - print reasons for each run.

    NOTE/TODO: Later, standardize issuance service signatures across Logistics
    so all callers use the same kwargs surface.
    """
    import json
    from types import SimpleNamespace as NS

    from sqlalchemy import select

    from app.extensions import db
    from app.extensions.policies import (
        load_policy_calendar,
        load_policy_issuance,
    )
    from app.lib.chrono import now_iso8601_ms
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
        issue_inventory,
        receive_inventory,
    )
    from app.slices.logistics.sku import parse_sku, validate_sku

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
            actor_id=None,
        )
        customer_ulid = ensure_customer(
            entity_ulid=ent_ulid,
            request_id=new_ulid(),
            actor_id=None,
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

        sku = f"{parts['cat']}-{parts['sub']}-{parts['src']}-{parts['size']}-{parts['col']}-{parts['issuance_class']}-{parts['seq']}"
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
            actor_id=None,
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
            classification_key="-".join(sku_code.split("-")[:2]),
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
        dec_bl = eval_ctx(sku_code, blackout_when, force_blackout=True)
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

        # 4) cadence trip (only if allowed in step 3)
        if ok_allowed and loc_ulid:
            from app.slices.logistics.services import decide_and_issue_one

            res = issue_inventory(
                customer_ulid=customer_ulid,
                sku_code=sku_code,
                quantity=1,
                when_iso=now_iso8601_ms(),
                project_ulid=None,
                actor_id=None,
                location_ulid=loc_ulid,
                batch_ulid=batch_ulid,
            )
            # immediate second attempt should hit cadence limit
            dec_cad = eval_ctx(sku_code, now_iso8601_ms())
            reason_cad = getattr(dec_cad, "reason", None)
        else:
            reason_cad = "skipped"

        rows_out.append(
            (
                idx,
                json.dumps(selector),
                sku_code,
                reason_bl,
                reason_qmiss,
                "ok" if ok_allowed else "denied",
                reason_cad,
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
    "--customer", "customer_ulid", default="TEST-CUST", show_default=True
)
@click.option(
    "--when", "when_iso", default=None, help="ISO-8601 (default: now UTC)"
)
@click.option("--project-ulid", default=None)
@click.option(
    "--force-blackout", is_flag=True, help="Trip the blackout enforcer"
)
@with_appcontext
def dev_decide_issue(
    sku_code, customer_ulid, when_iso, project_ulid, force_blackout
):
    """
    Evaluate issuance policy for a SKU against a
    (test) customer without writing.
    """
    from types import SimpleNamespace as NS

    from app.lib.chrono import now_iso8601_ms
    from app.slices.governance.services import decide_issue
    from app.slices.logistics.sku import (
        classification_key_for,
        parse_sku,
        validate_sku,
    )

    parts = parse_sku(sku_code)
    ctx = NS(
        customer_ulid=customer_ulid,
        sku_code=sku_code,
        sku_parts=parts,
        classification_key=classification_key_for(parts),
        when_iso=when_iso or now_iso8601_ms(),
        project_ulid=project_ulid,
        force_blackout=bool(force_blackout),
    )

    dec = decide_issue(ctx)
    click.echo(f"allowed={dec.allowed} reason={dec.reason}")
    # pretty JSON dump for debugging
    import json

    payload = {
        "allowed": dec.allowed,
        "reason": dec.reason,
        "approver_required": getattr(dec, "approver_required", None),
        "limit_window_label": getattr(dec, "limit_window_label", None),
        "next_eligible_at_iso": getattr(dec, "next_eligible_at_iso", None),
        "ctx": {
            "customer_ulid": ctx.customer_ulid,
            "sku_code": ctx.sku_code,
            "sku_parts": ctx.sku_parts,
            "classification_key": ctx.classification_key,
            "when_iso": ctx.when_iso,
            "project_ulid": ctx.project_ulid,
            "force_blackout": ctx.force_blackout,
        },
    }
    click.echo(json.dumps(payload, indent=2))


@dev_group.command("whoami")
@with_appcontext
def dev_whoami():
    """Dump minimal context useful during local debugging."""
    cfg = current_app.config
    click.echo(f"APP_MODE={cfg.get('APP_MODE','unknown')}")
    click.echo(f"DB_URI={cfg.get('SQLALCHEMY_DATABASE_URI','?')}")


# -----------------
# dev seeds
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
    from sqlalchemy import select

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
@click.option("--actor-id", default=None)
@click.option("--quantity", type=int, default=1, show_default=True)
def dev_demo_issue(
    customer_ulid: str | None,
    sku_code: str | None,
    loc_code: str,
    actor_id: str | None,
    quantity: int,
):
    """
    Issue one unit from baseline stock:
      - picks first SKU at the location if --sku omitted
      - uses a throwaway ULID for the customer if none provided
    """
    from sqlalchemy import select

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
        actor_id=actor_id,
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


@dev_group.command("lint-skus")
@with_appcontext
@click.option(
    "--data-dir", default="app/slices/logistics/data", show_default=True
)
def dev_lint_skus(data_dir: str):
    """Validate skus.json against sku.schema.json.
    Fails fast with row/field errors. No DB writes.
    """
    import json
    import os

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


@dev_group.command("purge-seed-items")
@with_appcontext
def dev_purge_seed_items():
    """
    Delete legacy Logistics rows for items named 'Seed Item'
    in FK-safe order: issues → movements → stock → batches → items.
    """
    from sqlalchemy import delete, select

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


@dev_group.command("seed-logistics-canonical")
@with_appcontext
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
@click.option("--loc-code", default="LOC-MAIN", show_default=True)
@click.option("--loc-name", default="Main Warehouse", show_default=True)
@click.option(
    "--sources",
    default="DR,LC",
    show_default=True,
    help="Comma list of sources to use (DR, LC). Default: DR,LC",
)
def dev_seed_logistics_canonical(
    count: int = 20,
    per_sku: int = 25,
    loc_code: str = "LOC-MAIN",
    loc_name: str = "Main Warehouse",
    sources: str = "DR,LC",
):
    """
    Seed a clean, predictable canonical set of SKUs (no kits),
    mostly issuance_class=U.
    """
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

        try:
            receive_inventory(
                item_ulid=item_ulid,
                quantity=per_sku,
                unit="each",
                source="donation",
                received_at_utc=now_iso8601_ms(),
                location_ulid=loc_ulid,
                note="seed:canonical",
                actor_id=None,
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
