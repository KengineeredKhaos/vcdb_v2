# Dev/ops utilities — helpers for local workflows, policy checks, smoke tests.
# Safe to ship; nothing runs unless invoked.
# Keep prod side-effects behind guards.

from __future__ import annotations

import json
import os

import click

# Optional: read APP_MODE so we can gate dangerous actions
from flask import current_app
from flask.cli import with_appcontext


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


@dev_group.command("eligible")
@with_appcontext
@click.argument("customer_ulid")
@click.option(
    "--when",
    "when_iso",
    default=None,
    help="ISO-8601 time (UTC). Defaults to now.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit a JSON object instead of text.",
)
@click.option(
    "--limit", type=int, default=0, help="Limit number of SKUs shown."
)
def dev_eligible(
    customer_ulid: str, when_iso: str | None, as_json: bool, limit: int
):
    """
    Show the SKU codes currently eligible for a customer at a moment in time.
    Uses Logistics → available_skus_for_customer(...) under the hood.
    """
    from app.lib.chrono import now_iso8601_ms
    from app.slices.logistics.services import available_skus_for_customer

    when = when_iso or now_iso8601_ms()

    try:
        skus = available_skus_for_customer(customer_ulid, when)
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        raise SystemExit(1)

    total = len(skus)
    if limit and total > limit:
        skus = skus[:limit]

    if as_json:
        payload = {
            "customer_ulid": customer_ulid,
            "as_of": when,
            "count": total if not limit else len(skus),
            "skus": skus,
            "truncated": bool(limit and total > limit),
        }
        click.echo(json.dumps(payload, indent=2))
        return

    # human-friendly text
    header = f"Eligible as of {when} (UTC) — {total} SKU(s)"
    if limit and total > limit:
        header += f" (showing first {limit})"
    click.echo(header)
    if not skus:
        click.echo("(none)")
        return
    for code in skus:
        click.echo(f" - {code}")


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

            res = decide_and_issue_one(
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


@dev_group.command("eligible-explain")
@with_appcontext
@click.argument("customer_ulid")
@click.option(
    "--when", "when_iso", default=None, help="ISO-8601 UTC (defaults to now)."
)
@click.option(
    "--match-class",
    "match_class",
    default=None,
    help="Only test items where InventoryItem.category == this.",
)
@click.option(
    "--limit",
    type=int,
    default=0,
    help="Cap number of SKUs shown (after filtering).",
)
@click.option(
    "--json", "as_json", is_flag=True, help="Emit JSON instead of text."
)
def dev_eligible_explain(
    customer_ulid: str,
    when_iso: str | None,
    match_class: str | None,
    limit: int,
    as_json: bool,
):
    """Explain WHY each SKU is allowed or denied for a customer at a moment in time."""
    import json as _json

    from sqlalchemy import select

    from app.extensions import db
    from app.extensions.contracts import governance_v2 as govc
    from app.lib.chrono import now_iso8601_ms
    from app.slices.governance.services import decide_issue
    from app.slices.logistics.models import InventoryItem

    when = when_iso or now_iso8601_ms()

    q = select(InventoryItem.sku, InventoryItem.category)
    if match_class:
        q = q.where(InventoryItem.category == match_class)
    rows = db.session.execute(q).all()

    results = []
    for sku, category in rows:
        ctx = govc.RestrictionContext(
            customer_ulid=customer_ulid,
            sku_code=sku,
            classification_key=category,
            as_of_iso=when,
            project_ulid=None,
            cost_cents=None,
        )
        d = decide_issue(ctx)
        results.append(
            {
                "sku": sku,
                "classification": category,
                "ok": bool(getattr(d, "ok", False)),
                "reason": getattr(d, "reason", None),
                "approver": getattr(d, "approver_required", None),
                "window": getattr(d, "limit_window_label", None),
                "next_eligible_at": getattr(d, "next_eligible_at_iso", None),
            }
        )

    shown = results[:limit] if (limit and len(results) > limit) else results

    if as_json:
        out = {
            "customer_ulid": customer_ulid,
            "as_of": when,
            "count": len(results),
            "shown": len(shown),
            "items": shown,
        }
        click.echo(_json.dumps(out, indent=2))
        return

    click.echo(
        f"Eligibility explain — as of {when} (UTC)  |  tested={len(results)}"
        + (
            f"  showing={len(shown)} (limit {limit})"
            if (limit and len(results) > limit)
            else ""
        )
    )

    if not shown:
        click.echo("(no items found to evaluate)")
        return

    w_sku = max(3, *(len(r["sku"]) for r in shown))
    w_cls = max(5, *(len(r["classification"] or "") for r in shown))
    w_rs = max(
        6,
        *(
            len(
                r["reason"]
                if r["reason"]
                else ("allow" if r["ok"] else "denied")
            )
            for r in shown
        ),
    )

    w_win = max(6, *(len(r["window"] or "") for r in shown))

    hdr = f"{'SKU':{w_sku}}  {'CLASS':{w_cls}}  {'ALLOW':5}  {'REASON':{w_rs}}  {'WINDOW':{w_win}}  APPROVER  NEXT"
    sep = "-" * len(hdr)
    click.echo(hdr)
    click.echo(sep)
    for r in shown:
        allow = "yes" if r["ok"] else "no"
        reason = (
            r["reason"] if r["reason"] else ("allow" if r["ok"] else "denied")
        )
        window = r["window"] or ""
        appr = r["approver"] or ""
        nxt = r["next_eligible_at"] or ""
        click.echo(
            f"{r['sku']:{w_sku}}  {r['classification']:{w_cls}}  {allow:5}  {reason:{w_rs}}  {window:{w_win}}  {appr:8}  {nxt}"
        )

    total_allow = sum(1 for r in results if r["ok"])
    total_deny = len(results) - total_allow
    by_reason: dict[str, int] = {}
    for r in results:
        key = (
            r["reason"] if r["reason"] else ("allow" if r["ok"] else "denied")
        )
        by_reason[key] = by_reason.get(key, 0) + 1
    click.echo(sep)
    click.echo(
        f"Totals: allow={total_allow}  deny={total_deny}  (tested={len(results)})"
    )
    click.echo(
        "By reason: "
        + ", ".join(f"{k}={v}" for k, v in sorted(by_reason.items()))
    )


@dev_group.command("whoami")
@with_appcontext
def dev_whoami():
    """Dump minimal context useful during local debugging."""
    cfg = current_app.config
    click.echo(f"APP_MODE={cfg.get('APP_MODE','unknown')}")
    click.echo(f"DB_URI={cfg.get('SQLALCHEMY_DATABASE_URI','?')}")


@dev_group.command("backfill-issues")
@with_appcontext
@click.option("--limit", default=10000, help="Max movements to process")
def dev_backfill_issues(limit: int):
    """Create Issue rows from logi_movement(kind='issue') where target_ref_ulid is a Customer ULID."""
    from sqlalchemy import select

    from app.extensions import db
    from app.slices.logistics.models import (
        InventoryItem,
        InventoryMovement,
        Issue,
    )

    mvts = (
        db.session.query(InventoryMovement)
        .filter(InventoryMovement.kind == "issue")
        .filter(InventoryMovement.target_ref_ulid.isnot(None))
        .order_by(InventoryMovement.happened_at_utc.asc())
        .limit(limit)
        .all()
    )

    seen = 0
    for m in mvts:
        # Skip if an Issue already points to this movement
        exists = db.session.execute(
            select(Issue.ulid).where(Issue.movement_ulid == m.ulid)
        ).scalar_one_or_none()
        if exists:
            continue

        item = db.session.get(InventoryItem, m.item_ulid)
        issue = Issue(
            customer_ulid=m.target_ref_ulid,
            classification_key=item.category if item else None,
            sku_code=item.sku if item else None,
            quantity=m.quantity,
            issued_at=m.happened_at_utc,
            project_ulid=None,
            movement_ulid=m.ulid,
            created_by_actor=m.created_by_actor,
        )
        db.session.add(issue)
        seen += 1

    db.session.commit()
    click.echo(f"Backfilled {seen} Issue rows.")


@dev_group.command("seed-logistics-min")
@with_appcontext
@click.option("--customer", required=True)
@click.option("--class-key", "class_key", default="welcome_home.kit")
@click.option("--qty", default=1, type=int)
@click.option("--sku", default=None)
@click.option("--sku-cat", "sku_cat", default=None)
@click.option("--sku-sub", "sku_sub", default=None)
@click.option("--sku-src", "sku_src", default=None)
@click.option("--sku-size", "sku_size", default=None)
@click.option("--sku-col", "sku_col", default=None)
@click.option("--sku-qual", "sku_qual", default=None)
def seed_logistics_min(
    customer,
    class_key,
    qty,
    sku,
    sku_cat,
    sku_sub,
    sku_src,
    sku_size,
    sku_col,
    sku_qual,
):
    from app.lib.chrono import now_iso8601_ms
    from app.slices.logistics import services as logi

    sku_parts = None
    if not sku and all(
        [sku_cat, sku_sub, sku_src, sku_size, sku_col, sku_qual]
    ):
        sku_parts = dict(
            cat=sku_cat.upper(),
            sub=sku_sub.upper(),
            src=sku_src.upper(),
            size=sku_size.upper(),
            col=sku_col.upper(),
            issuance_class=sku_qual.upper(),
        )
    item_ulid = logi.ensure_item(
        category=class_key,
        name="Seed Item",
        unit="each",
        condition="mixed",
        sku=sku,
        sku_parts=sku_parts,
    )
    loc_ulid = logi.ensure_location(code="MAIN", name="Main Warehouse")
    now = now_iso8601_ms()
    recv = logi.receive_inventory(
        item_ulid=item_ulid,
        quantity=max(5, qty),
        unit="each",
        source="donation",
        received_at_utc=now,
        location_ulid=loc_ulid,
        note="seed",
        actor_id=None,
        source_entity_ulid=None,
    )
    logi.issue_inventory(
        batch_ulid=recv["batch_ulid"],
        item_ulid=item_ulid,
        quantity=qty,
        unit="each",
        location_ulid=loc_ulid,
        happened_at_utc=now_iso8601_ms(),
        target_ref_ulid=customer,
        note="seed-issue",
        actor_id=None,
    )
    click.echo("Seeded and issued.")


@dev_group.command("list-catalog-classes")
@with_appcontext
def dev_list_catalog_classes():
    """Print distinct InventoryItem.category values
    (what Governance rules must cover)."""
    from sqlalchemy import distinct, select

    from app.extensions import db
    from app.slices.logistics.models import InventoryItem

    rows = db.session.execute(select(distinct(InventoryItem.category))).all()
    cats = sorted(c[0] for c in rows if c and c[0])
    click.echo("Catalog classes:")
    if not cats:
        click.echo("  (none)")
        return
    for c in cats:
        click.echo(f"  - {c}")


@dev_group.command("issuance-coverage")
@with_appcontext
def dev_issuance_coverage():
    """
    For each issuance rule, count how many catalog items it would match
    by classification_key.
    Also list any catalog classes with no matching rule.
    """
    import json as _json

    from sqlalchemy import distinct, select

    from app.extensions import db
    from app.extensions.policies import load_policy_issuance
    from app.slices.logistics.models import InventoryItem

    pol = load_policy_issuance()
    rules = pol.get("rules") or []

    cats = [
        c[0]
        for c in db.session.execute(
            select(distinct(InventoryItem.category))
        ).all()
        if c and c[0]
    ]
    cats_set = set(cats)

    def rule_key(r):
        return (r.get("match") or {}).get("classification_key")

    counts = []
    covered = set()
    for idx, r in enumerate(rules, start=1):
        m = rule_key(r)
        if not m:
            counts.append(
                {"rule_index": idx, "classification_key": None, "matches": 0}
            )
            continue
        n = sum(1 for c in cats if c == m)
        if n:
            covered.add(m)
        counts.append(
            {"rule_index": idx, "classification_key": m, "matches": n}
        )

    uncovered = sorted(c for c in cats_set - covered)
    click.echo(
        _json.dumps(
            {"counts": counts, "uncovered_classes": uncovered}, indent=2
        )
    )


@dev_group.command("issuance-template-for-skus")
@with_appcontext
@click.option(
    "--sku-like", required=True, help="fnmatch pattern, e.g. CG-SL-LC-*-*-*-*"
)
@click.option(
    "--preset",
    default="quarterly",
    type=click.Choice(["annual", "semiannual", "quarterly"]),
)
def dev_issuance_template_for_skus(sku_like: str, preset: str):
    import fnmatch
    import json

    from sqlalchemy import select

    from app.extensions import db
    from app.slices.logistics.models import InventoryItem

    rows = db.session.execute(
        select(InventoryItem.sku, InventoryItem.category)
    ).all()
    matches = [
        {"sku": s, "classification": c}
        for s, c in rows
        if fnmatch.fnmatch(s, sku_like)
    ]
    rules = [
        {
            "match": {"sku": m["sku"]},
            "qualifiers": {"veteran_required": False},
            "cadence_preset": preset,
        }
        for m in matches
    ]
    click.echo(json.dumps({"rules": rules}, indent=2))


@dev_group.command("seed-entity-min")
@with_appcontext
@click.option(
    "--ulid", "entity_ulid", default=None, help="ULID to use (optional)."
)
@click.option("--namefirst", default="Test")
@click.option("--namelast", default="User")
def dev_seed_entity_min(
    entity_ulid: str | None, namefirst: str, namelast: str
):
    """Create a minimal Entity row (core identity). Prints the entity ULID."""
    from sqlalchemy import select
    from app.extensions import db
    from app.lib.ids import new_ulid
    from app.lib.chrono import now_iso8601_ms

    now = now_iso8601_ms()
    try:
        from app.slices.entity.models import (
            Entity,
        )  # adjust if your path differs
    except Exception:
        click.echo(
            "ERROR: Entity model not found at app.slices.entity.models.Entity",
            err=True,
        )
        raise SystemExit(1)

    eu = entity_ulid or new_ulid()
    exists = db.session.execute(
        select(Entity.ulid).where(Entity.ulid == eu)
    ).scalar_one_or_none()
    if exists:
        click.echo(eu)
        return

    row = Entity(ulid=eu)
    if hasattr(row, "namefirst"):
        row.namefirst = namefirst
    if hasattr(row, "namelast"):
        row.namelast = namelast
    if hasattr(row, "kind") and getattr(row, "kind", None) is None:
        row.kind = "person"  # or "organization" for orgs
    if hasattr(row, "created_at_utc"):
        row.created_at_utc = now
    if hasattr(row, "updated_at_utc"):
        row.updated_at_utc = now
    db.session.add(row)
    db.session.commit()  # ← ensure FK target exists
    click.echo(eu)


@dev_group.command("seed-customer-min")
@with_appcontext
@click.argument("customer_ulid")
@click.option(
    "--entity-ulid",
    default=None,
    help="Existing Entity ULID; if omitted, one is created.",
)
@click.option("--name", default="Test Customer")
def dev_seed_customer_min(
    customer_ulid: str, entity_ulid: str | None, name: str
):
    """Create a minimal Customer row (and its Entity if missing)."""
    from sqlalchemy import select
    from app.extensions import db
    from app.lib.chrono import now_iso8601_ms
    from app.lib.ids import new_ulid

    now = now_iso8601_ms()
    try:
        from app.slices.customers.models import Customer
    except Exception:
        click.echo(
            "ERROR: Customer model not found at app.slices.customers.models.Customer",
            err=True,
        )
        raise SystemExit(1)
    try:
        from app.slices.entity.models import Entity
    except Exception:
        click.echo(
            "ERROR: Entity model not found at app.slices.entity.models.Entity",
            err=True,
        )
        raise SystemExit(1)

    # If Customer already exists, bail out gracefully
    exists = db.session.execute(
        select(Customer.ulid).where(Customer.ulid == customer_ulid)
    ).scalar_one_or_none()
    if exists:
        click.echo(f"Customer exists: {customer_ulid}")
        return

    # Ensure Entity (create + commit first so FK can pass)
    ent_ulid = entity_ulid
    if not ent_ulid:
        ent_ulid = new_ulid()
        ent = Entity(ulid=ent_ulid)
        if hasattr(ent, "namefirst"):
            ent.namefirst = name.split(" ", 1)[0]
        if hasattr(ent, "namelast"):
            ent.namelast = name.split(" ", 1)[1] if " " in name else "User"
        if hasattr(ent, "kind") and getattr(ent, "kind", None) is None:
            ent.kind = "person"
        if hasattr(ent, "created_at_utc"):
            ent.created_at_utc = now
        if hasattr(ent, "updated_at_utc"):
            ent.updated_at_utc = now
        db.session.add(ent)
        db.session.commit()  # ← commit Entity first

    # Build Customer, set required FK
    row = Customer(ulid=customer_ulid)
    if not hasattr(row, "entity_ulid"):
        click.echo(
            "ERROR: Customer model has no entity_ulid field; cannot satisfy FK.",
            err=True,
        )
        raise SystemExit(1)
    row.entity_ulid = ent_ulid  # ← the FK you just created/verified
    # Helpful echo
    click.echo(
        f"Using entity_ulid={ent_ulid} for customer_ulid={customer_ulid}"
    )

    # Optional common fields (only if present)
    if hasattr(row, "status") and not getattr(row, "status", None):
        row.status = "active"
    if hasattr(row, "created_at_utc"):
        row.created_at_utc = now
    if hasattr(row, "updated_at_utc"):
        row.updated_at_utc = now
    if hasattr(row, "name") and not getattr(row, "name", None):
        row.name = name
    if hasattr(row, "namefirst") and not getattr(row, "namefirst", None):
        row.namefirst = name.split(" ", 1)[0]
    if hasattr(row, "namelast") and not getattr(row, "namelast", None):
        row.namelast = name.split(" ", 1)[1] if " " in name else "User"

    db.session.add(row)
    db.session.commit()
    click.echo(f"Created customer: {customer_ulid} (entity_ulid={ent_ulid})")


@dev_group.command("inspect-entity-required")
@with_appcontext
def dev_inspect_entity_required():
    from app.slices.entity.models import Entity

    req = [
        (c.name, c.nullable)
        for c in Entity.__table__.columns
        if not c.nullable
    ]
    click.echo("Entity required (NOT NULL) columns:")
    for name, _ in req:
        click.echo(f"  - {name}")


@dev_group.command("inspect-customer-fks")
@with_appcontext
def dev_inspect_customer_fks():
    """Print Customer table foreign key columns for quick debugging."""
    from app.slices.customers.models import Customer

    cols = []
    for c in Customer.__table__.columns:
        if c.foreign_keys:
            refs = ", ".join(f"{fk.column}" for fk in c.foreign_keys)
            cols.append((c.name, refs, c.nullable))
    if not cols:
        click.echo("(Customer has no FKs)")
        return
    click.echo("Customer FKs (column -> references, nullable):")
    for name, refs, nullable in cols:
        click.echo(f"  - {name} -> {refs}  nullable={nullable}")


@dev_group.command("customer-snapshot")
@with_appcontext
@click.argument("customer_ulid")
def dev_customer_snapshot(customer_ulid: str):
    """Show the read-only eligibility snapshot used by policy rules."""
    import json
    from app.slices.customers.services import get_eligibility_snapshot

    snap = get_eligibility_snapshot(customer_ulid)
    click.echo(json.dumps(snap.__dict__, indent=2))


@dev_group.command("set-eligibility-flags")
@with_appcontext
@click.argument("customer_ulid")
@click.option("--vet", is_flag=True, help="Mark as veteran-verified (true).")
@click.option(
    "--homeless", is_flag=True, help="Mark as homeless-verified (true)."
)
def dev_set_eligibility_flags(customer_ulid: str, vet: bool, homeless: bool):
    from sqlalchemy import select

    from app.extensions import db
    from app.lib.chrono import now_iso8601_ms
    from app.lib.ids import new_ulid
    from app.slices.customers.models import Customer, CustomerEligibility

    # require the customer to exist to avoid FK explosions
    exists = db.session.execute(
        select(Customer.ulid).where(Customer.ulid == customer_ulid)
    ).scalar_one_or_none()
    if not exists:
        click.echo(
            "ERROR: customer ULID not found. Create the customer first (see: flask dev seed-customer-min).",
            err=True,
        )
        raise SystemExit(1)

    row = db.session.execute(
        select(CustomerEligibility).where(
            CustomerEligibility.customer_ulid == customer_ulid
        )
    ).scalar_one_or_none()

    now = now_iso8601_ms()
    if row is None:
        row = CustomerEligibility(
            ulid=new_ulid(),
            customer_ulid=customer_ulid,
            is_veteran_verified=bool(vet),
            is_homeless_verified=bool(homeless),
            tier1_min=None,
            tier2_min=None,
            tier3_min=None,
            created_at_utc=now,
            updated_at_utc=now,
        )
        db.session.add(row)
    else:
        if vet:
            row.is_veteran_verified = True
        if homeless:
            row.is_homeless_verified = True
        row.updated_at_utc = now
    db.session.commit()
    click.echo("Eligibility flags updated.")


@dev_group.command("cadence-debug")
@with_appcontext
@click.argument("customer_ulid")
@click.option("--class-key", default=None)
@click.option("--sku", "sku_code", default=None)
@click.option("--days", default=90, help="Period days")
@click.option("--max", "max_per", default=1, help="Max per period")
@click.option("--as-of", "as_of_iso", default=None)
def dev_cadence_debug(
    customer_ulid, class_key, sku_code, days, max_per, as_of_iso
):
    """Print cadence window and count for quick verification."""
    from app.lib.chrono import now_iso8601_ms, as_naive_utc
    from app.extensions.contracts import logistics_v2
    from datetime import timedelta

    as_of = as_of_iso or now_iso8601_ms()
    as_dt = as_naive_utc(as_of)
    start = (as_dt - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[
        :-3
    ] + "Z"

    cnt = logistics_v2.count_issues_in_window(
        customer_ulid=customer_ulid,
        classification_key=class_key,
        sku_code=sku_code,
        window_start_iso=start,
        as_of_iso=as_of,
    )
    click.echo(
        f"Window: {start} → {as_of}  count={cnt}  limit={max_per}  -> {'OK' if cnt < max_per else 'LIMITED'}"
    )


#############################
#     SEEDER & HELPERS
#############################

# --- helpers: load/validate ---------------------------------


def _read_json(path: str) -> list[dict] | dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _validate_skus(items: list[dict], schema_path: str | None) -> None:
    """Validate each row against sku.schema.json if provided."""
    if not schema_path or not os.path.exists(schema_path):
        click.echo("NOTE: schema file not found—skipping validation.")
        return
    try:
        from app.lib.schema import load_json_schema, validate_json
    except Exception:
        click.echo("NOTE: app.lib.schema unavailable—skipping validation.")
        return
    schema = load_json_schema(schema_path)
    for i, row in enumerate(items, 1):
        ok, errs = validate_json(row, schema)
        if not ok:
            raise SystemExit(f"Invalid SKU row #{i}: {errs}")


def _require_dev_mode():
    mode = (current_app.config.get("APP_MODE") or "dev").lower()
    if mode not in {"dev", "development", "local"}:
        raise SystemExit("Refusing outside DEV. Set APP_MODE=dev to proceed.")


# --- dev seeds ------------------------------------------------


@dev_group.command("seed-logistics-baseline")
@with_appcontext
@click.option(
    "--data-dir",
    default="app/slices/logistics/data",
    show_default=True,
    help="Directory containing skus.json and sku.schema.json",
)
@click.option("--loc-code", default="LOC-MAIN", show_default=True)
@click.option("--loc-name", default="Main Warehouse", show_default=True)
@click.option(
    "--per-sku",
    type=int,
    default=25,
    show_default=True,
    help="How many units to receive for each SKU",
)
@click.option("--unit", default="each", show_default=True)
def seed_logistics_baseline(
    data_dir: str, loc_code: str, loc_name: str, per_sku: int, unit: str
):
    """
    Seed a predictable baseline:
      - Ensure a single Location
      - Load & validate SKUs
      - Upsert InventoryItem rows
      - Receive N units into the Location (creates batch, movement, stock)
    """
    _require_dev_mode()

    # 0) paths
    skus_path = os.path.join(data_dir, "skus.json")
    schema_path = os.path.join(data_dir, "schemas/sku.schema.json")
    if not os.path.exists(skus_path):
        raise SystemExit(f"Cannot find {skus_path}")

    # 1) read + validate
    rows = _read_json(skus_path)
    if not isinstance(rows, list):
        raise SystemExit("skus.json must be a JSON array.")
    # Used to was _validate_skus(rows, schema_path)
    # strict validation: refuse to seed if any row is invalid
    from app.lib.schema import load_json_schema, try_validate_json

    if not os.path.exists(schema_path):
        raise SystemExit(f"Missing schema: {schema_path}")
    schema = load_json_schema(schema_path)
    for i, row in enumerate(rows, 1):
        ok, err = try_validate_json(schema, row)
        if not ok:
            raise SystemExit(
                f"Invalid SKU row #{i} (sku={row.get('sku')}): {err}"
            )

    # 2) ensure Location
    from app.lib.chrono import now_iso8601_ms
    from app.slices.logistics.services import (
        ensure_item,
        ensure_location,
        receive_inventory,
    )

    loc_ulid = ensure_location(code=loc_code, name=loc_name)

    # 3) upsert items + receive stock
    created = 0
    received = 0
    for row in rows:
        sku = row["sku"]
        name = row.get("name") or row.get("title") or "Unnamed"
        unit_row = row.get("unit") or unit
        # minimal categorization; keep it simple and consistent
        category = row.get("classification_key") or "unclassified"
        condition = "new"

        item_ulid = ensure_item(
            category=category,
            name=name,
            unit=unit_row,
            condition=condition,
            sku=sku,
        )
        created += 1

        # receive per-sku quantity
        recv = receive_inventory(
            item_ulid=item_ulid,
            quantity=per_sku,
            unit=unit_row,
            source="donation",
            received_at_utc=now_iso8601_ms(),
            location_ulid=loc_ulid,
            note=f"seed:{os.path.basename(skus_path)}",
            actor_id=None,
            source_entity_ulid=None,
        )
        received += 1

    click.echo(
        f"OK — location={loc_code} ({loc_ulid}) items={created} batches/receipts={received}"
    )
    click.echo(
        "Tip: run `flask dev list-stock --location {}` to view.".format(
            loc_code
        )
    )


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
        InventoryStock,
        InventoryItem,
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
    from app.slices.logistics.services import decide_and_issue_one

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

    res = decide_and_issue_one(
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
