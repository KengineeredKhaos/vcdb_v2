# app/slices/logistics/issuance_services.py

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from fnmatch import fnmatch
from typing import Any

from sqlalchemy import func, select

from app.extensions import db, event_bus
from app.extensions.contracts.customers_v2 import (
    CustomerCuesDTO,
    append_history_entry,
    get_customer_cues,
)
from app.extensions.policies import (
    load_policy_logistics_issuance,
)
from app.lib.chrono import (
    as_naive_utc,
    parse_iso8601,
    to_iso8601,
    utcnow_aware,
)
from app.lib.ids import new_ulid
from app.lib.jsonutil import stable_dumps

from .history_blob import build_customer_history_blob
from .models import (
    InventoryBatch,
    InventoryItem,
    InventoryMovement,
    InventoryStock,
    Issue,
    Location,
)
from .qualifiers import evaluate as evaluate_qualifiers
from .sku import classification_key_for, parse_sku, validate_sku

# Policy selector keys -> parse_sku() keys
_PART_KEY_MAP: dict[str, str] = {
    "category": "cat",
    "subcategory": "sub",
    "source": "src",
    "color": "col",
    # size, issuance_class, seq match parse_sku keys already
}


# -----------------
# Context + Results
# -----------------


@dataclass
class IssueContext:
    """
    Everything the decision engine needs, in one place.

    Keep this a dumb container. No side effects.
    """

    customer_ulid: str | None
    sku_code: str | None
    as_of_dt: datetime | None = None

    # Optional task context (Scenario #3 durable goods)
    project_ulid: str | None = None

    # Optional operational details (write path)
    location_ulid: str | None = None
    batch_ulid: str | None = None

    # Actor info (for overrides, audit)
    actor_ulid: str | None = None
    actor_domain_roles: list[str] | None = None

    # Controls
    force_blackout: bool = False
    override_cadence: bool = False

    # Derived / cached
    sku_parts: dict[str, str] | None = None
    classification_key: str | None = None

    # Cached cross-slice snapshot (avoid N calls for N SKUs)
    customer_cues: CustomerCuesDTO | None = None

    # Working fields (set by decide_issue)
    qualifiers: dict[str, Any] = field(default_factory=dict)
    defaults_cadence: dict[str, Any] = field(default_factory=dict)

    @property
    def when_iso(self) -> str | None:
        if self.as_of_dt is None:
            return None
        return to_iso8601(self.as_of_dt)

    @when_iso.setter
    def when_iso(self, value: str | datetime | None) -> None:
        if value is None:
            self.as_of_dt = None
            return
        if isinstance(value, datetime):
            self.as_of_dt = value
            return
        if isinstance(value, str):
            self.as_of_dt = parse_iso8601(value)
            return
        raise TypeError("when_iso must be str | datetime | None")


@dataclass(frozen=True)
class IssueDecision:
    allowed: bool
    reason: str

    approver_required: str | None = None
    limit_window_label: str | None = None
    next_eligible_at_iso: str | None = None
    cadence_enforcement: str | None = None
    override_requested: bool = False
    override_used: bool = False


@dataclass(frozen=True)
class IssueResult:
    ok: bool
    reason: str

    issue_ulid: str | None = None
    movement_ulid: str | None = None
    item_ulid: str | None = None
    batch_ulid: str | None = None
    qty_each: int = 0

    decision: IssueDecision | None = None


# -----------------
# Public entry points
# -----------------


def issue_inventory(
    *,
    customer_ulid: str | None,
    sku_code: str,
    qty_each: int = 1,
    as_of_dt: datetime | None = None,
    when_iso: str | None = None,
    project_ulid: str | None = None,
    location_ulid: str | None = None,
    batch_ulid: str | None = None,
    actor_ulid: str | None = None,
    actor_domain_roles: list[str] | None = None,
    override_cadence: bool = False,
    force_blackout: bool = False,
    request_id: str | None = None,
    reason: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Mutating entry point: evaluate policy then write Issue + decrement stock.

    Returns a plain dict suitable for JSON routes/CLI.
    """
    effective_as_of_dt = (
        as_of_dt
        or (parse_iso8601(when_iso) if when_iso else None)
        or utcnow_aware()
    )

    ctx = IssueContext(
        customer_ulid=customer_ulid,
        sku_code=sku_code,
        as_of_dt=effective_as_of_dt,
        project_ulid=project_ulid,
        location_ulid=location_ulid,
        batch_ulid=batch_ulid,
        actor_ulid=actor_ulid,
        actor_domain_roles=actor_domain_roles or [],
        override_cadence=override_cadence,
        force_blackout=force_blackout,
    )

    decision = decide_issue(ctx)
    if not decision.allowed:
        return {
            "ok": False,
            "reason": decision.reason,
            "decision": asdict(decision),
        }

    res = decide_and_issue_one(
        ctx=ctx,
        qty_each=qty_each,
        decision=decision,
        request_id=request_id,
        reason=reason,
        note=note,
    )

    try:
        db.session.flush()
    except Exception:
        db.session.rollback()
        raise

    out = asdict(res)
    out["decision"] = (
        asdict(res.decision) if res.decision else asdict(decision)
    )
    return out


def decide_issue(ctx: IssueContext) -> IssueDecision:
    """
    Enforcer →
    hard SKU constraints →
    invariants →
    qualifiers →
    cadence.

    Policy behavior:
      - qualifiers:
        merged across ALL matching sku_constraints.rules (True sticks)
      - cadence:
        choose the most-specific matching rule that has cadence
      - defaults cadence:
        used when no cadence rule matches (or no rules match + allow)
    """
    from app.extensions.enforcers import calendar_blackout_ok

    pol = load_policy_logistics_issuance() or {}
    issuance = pol.get("issuance") or {}
    sku_constraints = pol.get("sku_constraints") or {}

    default_behavior = (
        pol.get("default_behavior")
        or issuance.get("default_behavior")
        or "deny"
    ).lower()

    rules = sku_constraints.get("rules") or []

    # -------- derived fields --------
    if ctx.as_of_dt is None:
        ctx.as_of_dt = utcnow_aware()

    sku_code = ctx.sku_code or ""
    if not sku_code:
        return _decision(False, "sku_required")

    # Fast structural validation (allowed sources/units + syntax)
    # Structural validation is regex-based in sku.py.
    # Governance SKU policy constraints are enforced separately (see _check_sku_constraints
    # and policy_semantics.assert_sku_constraints_ok on the write path).
    if not validate_sku(sku_code):
        return _decision(False, "invalid_sku")

    if ctx.sku_parts is None:
        try:
            ctx.sku_parts = parse_sku(sku_code)
        except Exception:
            return _decision(False, "invalid_sku")

    if ctx.classification_key is None:
        ctx.classification_key = classification_key_for(sku_code)

    # -------- 1) calendar blackout --------
    ok, meta = calendar_blackout_ok(ctx)
    ok, why = _norm_gate(ok, meta, "calendar_blackout")
    if not ok:
        label = meta.get("label") if isinstance(meta, dict) else None
        return _decision(False, why, limit_window_label=label)

    # -------- 2) hard SKU constraints (structural invariants) --------
    ok_sku, why_sku = _check_sku_constraints({}, ctx)
    ok_sku, why_sku = _norm_gate(ok_sku, why_sku, "sku_restricted")
    if not ok_sku:
        return _decision(False, why_sku)

    # -------- 2.5) true invariants based on issuance_class --------
    ic = (ctx.sku_parts or {}).get("issuance_class")

    # U = unrestricted: skip qualifiers + cadence entirely
    if ic == "U":
        return _decision(True, "ok_unrestricted")

    # D = durable goods: require project/task context (Scenario #3)
    if ic == "D":
        if not ctx.project_ulid:
            return _decision(False, "durable_requires_project")
        return _decision(True, "ok_durable")

    # -------- helpers: specificity + merge --------
    def _specificity(rule: dict) -> int:
        m = rule.get("match") or {}
        score = 0
        if m.get("classification_key") is not None:
            score += 10
        if m.get("sku"):
            score += 8
        sp = m.get("sku_parts") or {}
        if isinstance(sp, dict):
            score += len(sp)
        return score

    def _merge_qualifiers(matches: list[dict]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for r in matches:
            q = r.get("qualifiers") or {}
            if not isinstance(q, dict):
                continue
            for k, v in q.items():
                if isinstance(v, bool):
                    out[k] = bool(out.get(k)) or v
                elif v is not None:
                    out[k] = v
        return out

    # -------- 3) collect ALL matching rules --------
    matches: list[dict] = []
    for r in rules:
        if _rule_matches(r, ctx):
            matches.append(r)

    # Defaults cadence (prefer issuance.defaults.cadence; allow future relocation)
    ctx.defaults_cadence = (
        (issuance.get("defaults") or {}).get("cadence")
        or (sku_constraints.get("defaults") or {}).get("cadence")
        or {}
    )

    # -------- 4) no rules matched → apply default posture --------
    if not matches:
        if default_behavior != "allow":
            return _decision(False, "no_matching_rule")

        ctx.qualifiers = {}
        ok_cad, window_label, next_eligible = _apply_cadence({}, ctx)
        if ok_cad:
            return _decision(True, "ok")

        enforcement = _cadence_enforcement({}, ctx=ctx)
        if enforcement == "advisory":
            if ctx.override_cadence:
                return _decision(
                    True,
                    "cadence_overridden",
                    limit_window_label=window_label,
                    next_eligible_at_iso=next_eligible,
                    cadence_enforcement=enforcement,
                    override_requested=ctx.override_cadence,
                    override_used=True,
                )
            return _decision(
                False,
                "cadence_advisory",
                limit_window_label=window_label,
                next_eligible_at_iso=next_eligible,
                cadence_enforcement=enforcement,
                override_requested=ctx.override_cadence,
            )

        return _decision(
            False,
            "cadence_limit",
            approver_required="governor",
            limit_window_label=window_label,
            next_eligible_at_iso=next_eligible,
            cadence_enforcement=enforcement,
            override_requested=ctx.override_cadence,
        )

    # -------- 5) matched rules → merged qualifiers then cadence --------
    ctx.qualifiers = _merge_qualifiers(matches)

    # Hydrate cues only if qualifiers exist and the caller didn't supply them.
    # (available_skus_for_customer preloads cues once for N SKUs.)
    if ctx.customer_ulid and ctx.customer_cues is None and ctx.qualifiers:
        ctx.customer_cues = _get_customer_cues(ctx)

    out_q = evaluate_qualifiers(
        qualifiers=ctx.qualifiers,
        customer_cues=ctx.customer_cues,
    )

    ok_q, why_q = _norm_gate(out_q.ok, out_q.reason, "qualifiers_not_met")
    if not ok_q:
        return _decision(False, why_q)

    cadence_candidates = [r for r in matches if (r.get("cadence") or None)]
    cadence_rule = None
    if cadence_candidates:
        best_score = -1
        for r in cadence_candidates:
            s = _specificity(r)
            if s > best_score:
                best_score = s
                cadence_rule = r

    ok_cad, window_label, next_eligible = _apply_cadence(
        cadence_rule or {}, ctx
    )
    if ok_cad:
        return _decision(True, "ok")

    enforcement = _cadence_enforcement(cadence_rule or {}, ctx=ctx)
    if enforcement == "advisory":
        if ctx.override_cadence:
            return _decision(
                True,
                "cadence_overridden",
                limit_window_label=window_label,
                next_eligible_at_iso=next_eligible,
                cadence_enforcement=enforcement,
                override_requested=ctx.override_cadence,
                override_used=True,
            )
        return _decision(
            False,
            "cadence_advisory",
            limit_window_label=window_label,
            next_eligible_at_iso=next_eligible,
            cadence_enforcement=enforcement,
            override_requested=ctx.override_cadence,
        )

    return _decision(
        False,
        "cadence_limit",
        limit_window_label=window_label,
        next_eligible_at_iso=next_eligible,
        cadence_enforcement=enforcement,
        override_requested=ctx.override_cadence,
    )


def preview_customer_issuance_cart(
    *,
    customer_ulid: str,
    location_ulid: str,
    as_of_iso: str | None = None,
) -> dict[str, Any]:
    """Read-only preview surface for a small customer issuance cart."""
    if not customer_ulid:
        raise ValueError("customer_ulid is required")
    if not location_ulid:
        raise ValueError("location_ulid is required")

    as_of_dt = parse_iso8601(as_of_iso) if as_of_iso else utcnow_aware()
    cues = get_customer_cues(entity_ulid=customer_ulid)

    location = db.session.execute(
        select(Location).where(Location.ulid == location_ulid)
    ).scalar_one_or_none()
    if location is None:
        raise LookupError("location not found")

    rows = db.session.execute(
        select(InventoryItem, InventoryStock)
        .join(InventoryStock, InventoryStock.item_ulid == InventoryItem.ulid)
        .where(InventoryStock.location_ulid == location_ulid)
        .order_by(InventoryItem.name.asc(), InventoryItem.sku.asc())
    ).all()

    lines: list[dict[str, Any]] = []
    eligible_count = 0
    advisory_count = 0
    blocked_count = 0

    for item, stock in rows:
        ctx = IssueContext(
            customer_ulid=customer_ulid,
            sku_code=item.sku,
            as_of_dt=as_of_dt,
            location_ulid=location_ulid,
            customer_cues=cues,
        )
        decision = decide_issue(ctx)

        if decision.allowed:
            status = "eligible"
            eligible_count += 1
        elif decision.reason == "cadence_advisory":
            status = "advisory_warn"
            advisory_count += 1
        else:
            status = "blocked"
            blocked_count += 1

        lines.append(
            {
                "item_ulid": item.ulid,
                "sku_code": item.sku,
                "item_name": item.name,
                "category": item.category,
                "unit": item.unit,
                "classification_key": classification_key_for(item.sku),
                "available_qty": int(stock.quantity or 0),
                "status": status,
                "decision": asdict(decision),
            }
        )

    return {
        "customer_ulid": customer_ulid,
        "location_ulid": location_ulid,
        "location_code": location.code,
        "location_name": location.name,
        "as_of_iso": to_iso8601(as_of_dt),
        "eligible_count": eligible_count,
        "advisory_count": advisory_count,
        "blocked_count": blocked_count,
        "lines": lines,
    }


def commit_customer_issuance_cart(
    *,
    customer_ulid: str,
    location_ulid: str,
    cart_lines: list[dict[str, Any]],
    actor_ulid: str,
    request_id: str | None = None,
    as_of_dt: datetime | None = None,
    when_iso: str | None = None,
    project_ulid: str | None = None,
    session_note: str | None = None,
    override_cadence: bool = False,
    override_reason: str | None = None,
) -> dict[str, Any]:
    """Commit a small cart-style issuance session for one customer visit."""
    if not customer_ulid:
        raise ValueError("customer_ulid is required")
    if not location_ulid:
        raise ValueError("location_ulid is required")
    if not actor_ulid:
        raise ValueError("actor_ulid is required")

    effective_as_of_dt = (
        as_of_dt
        or (parse_iso8601(when_iso) if when_iso else None)
        or utcnow_aware()
    )

    aggregated: dict[str, int] = {}
    for raw in cart_lines or []:
        sku_code = str(raw.get("sku_code") or raw.get("sku") or "").strip()
        qty_each = int(raw.get("qty_each") or raw.get("quantity") or 0)
        if not sku_code or qty_each <= 0:
            continue
        aggregated[sku_code] = aggregated.get(sku_code, 0) + qty_each

    if not aggregated:
        raise ValueError("at least one cart line is required")

    as_of_dt = effective_as_of_dt
    as_of_iso = to_iso8601(as_of_dt)
    req_id = request_id or new_ulid()
    issuance_session_ulid = new_ulid()
    cues = get_customer_cues(entity_ulid=customer_ulid)

    planned: list[tuple[str, int, IssueDecision, InventoryItem]] = []
    advisory_hits: list[str] = []

    for sku_code, qty_each in aggregated.items():
        item = db.session.execute(
            select(InventoryItem).where(InventoryItem.sku == sku_code)
        ).scalar_one_or_none()
        if item is None:
            raise LookupError(f"sku not found: {sku_code}")

        ctx = IssueContext(
            customer_ulid=customer_ulid,
            sku_code=sku_code,
            as_of_dt=as_of_dt,
            project_ulid=project_ulid,
            location_ulid=location_ulid,
            actor_ulid=actor_ulid,
            override_cadence=override_cadence,
            customer_cues=cues,
        )
        decision = decide_issue(ctx)
        if not decision.allowed:
            if decision.reason == "cadence_advisory":
                advisory_hits.append(sku_code)
                continue
            raise ValueError(f"{sku_code}: {decision.reason}")
        if decision.override_used:
            advisory_hits.append(sku_code)
        planned.append((sku_code, qty_each, decision, item))

    if advisory_hits and not override_cadence:
        raise ValueError("advisory cadence warning requires session override")

    if not planned:
        raise ValueError("no cart lines could be issued")

    if advisory_hits and not override_reason:
        raise ValueError(
            "override reason is required when advisory cadence is bypassed"
        )

    results: list[IssueResult] = []
    issued_items: list[dict[str, Any]] = []
    for sku_code, qty_each, decision, item in planned:
        ctx = IssueContext(
            customer_ulid=customer_ulid,
            sku_code=sku_code,
            as_of_dt=as_of_dt,
            project_ulid=project_ulid,
            location_ulid=location_ulid,
            actor_ulid=actor_ulid,
            override_cadence=override_cadence,
            customer_cues=cues,
        )
        res = decide_and_issue_one(
            ctx=ctx,
            qty_each=qty_each,
            decision=decision,
            request_id=req_id,
            reason=override_reason if decision.override_used else None,
            note=session_note,
        )
        if not res.ok:
            raise ValueError(f"{sku_code}: {res.reason}")
        results.append(res)
        issued_items.append(
            {
                "sku": sku_code,
                "nomenclature": item.name,
                "quantity": qty_each,
                "classification_key": classification_key_for(sku_code),
            }
        )

    if any(r.decision and r.decision.override_used for r in results):
        event_bus.emit(
            domain="logistics",
            operation="cadence_override_used",
            request_id=req_id,
            actor_ulid=actor_ulid,
            target_ulid=customer_ulid,
            refs={
                "issuance_session_ulid": issuance_session_ulid,
                "location_ulid": location_ulid,
                "sku_codes": [row["sku"] for row in issued_items],
            },
            meta={
                "override_reason": override_reason,
                "line_count": len(issued_items),
            },
            happened_at_utc=as_of_iso,
        )

    summary_names = ", ".join(row["nomenclature"] for row in issued_items[:3])
    if len(issued_items) > 3:
        summary_names += f" +{len(issued_items) - 3} more"

    blob = build_customer_history_blob(
        schema_name="logistics.issuance_summary",
        schema_version=1,
        title=(
            f"Issued {issued_items[0]['nomenclature']}"
            if len(issued_items) == 1
            else f"Issued {len(issued_items)} supply lines"
        ),
        summary=(
            f"Issued {summary_names}."
            if not advisory_hits
            else f"Issued {summary_names}; advisory cadence override used."
        ),
        source_slice="logistics",
        happened_at_iso=as_of_iso,
        severity="warn" if advisory_hits else "info",
        public_tags=["issuance", "logistics"],
        admin_tags=["cadence_override"] if advisory_hits else (),
        source_ref_ulid=issuance_session_ulid,
        created_by_actor_ulid=actor_ulid,
        refs={
            "issuance_session_ulid": issuance_session_ulid,
            "location_ulid": location_ulid,
            "line_count": len(issued_items),
        },
        payload={
            "issuance_session_ulid": issuance_session_ulid,
            "location_ulid": location_ulid,
            "issue_ulids": [r.issue_ulid for r in results if r.issue_ulid],
            "movement_ulids": [
                r.movement_ulid for r in results if r.movement_ulid
            ],
            "items": issued_items,
            "override_used": bool(advisory_hits),
            "override_reason": override_reason if advisory_hits else None,
            "note": session_note,
        },
    )
    history_ulid = append_history_entry(
        target_entity_ulid=customer_ulid,
        kind="logistics_issuance",
        blob_json=blob,
        actor_ulid=actor_ulid,
        request_id=req_id,
    )

    return {
        "ok": True,
        "issuance_session_ulid": issuance_session_ulid,
        "request_id": req_id,
        "customer_ulid": customer_ulid,
        "location_ulid": location_ulid,
        "history_ulid": history_ulid,
        "override_used": bool(advisory_hits),
        "lines": [
            {
                "issue_ulid": r.issue_ulid,
                "movement_ulid": r.movement_ulid,
                "item_ulid": r.item_ulid,
                "batch_ulid": r.batch_ulid,
                "qty_each": r.qty_each,
                "decision": asdict(r.decision) if r.decision else None,
            }
            for r in results
        ],
    }


def available_skus_for_customer(
    *,
    customer_ulid: str,
    as_of_iso: str | None = None,
    location_ulid: str | None = None,
    include_out_of_stock: bool = False,
    actor_ulid: str | None = None,
    actor_domain_roles: list[str] | None = None,
    override_cadence: bool = False,
) -> list[str]:
    """
    Read-only helper used by contracts/UI: return SKUs eligible *right now*
    for this customer.

    Notes:
      - This DOES evaluate cadence (so the picker won't offer blocked SKUs).
      - If include_out_of_stock is False and location_ulid is provided,
        we require stock > 0 at that location.
    """
    cues = get_customer_cues(entity_ulid=customer_ulid)
    effective_as_of_dt = (
        parse_iso8601(as_of_iso) if as_of_iso else utcnow_aware()
    )

    q = select(InventoryItem.sku).distinct()
    if location_ulid and not include_out_of_stock:
        q = q.join(
            InventoryStock, InventoryStock.item_ulid == InventoryItem.ulid
        ).where(
            InventoryStock.location_ulid == location_ulid,
            InventoryStock.quantity > 0,
        )

    skus = [s for s in db.session.execute(q).scalars().all() if s]
    out: list[str] = []
    for sku in skus:
        ctx = IssueContext(
            customer_ulid=customer_ulid,
            sku_code=sku,
            as_of_dt=effective_as_of_dt,
            location_ulid=location_ulid,
            actor_ulid=actor_ulid,
            actor_domain_roles=actor_domain_roles or [],
            override_cadence=override_cadence,
            customer_cues=cues,
        )
        d = decide_issue(ctx)
        if d.allowed:
            out.append(sku)
    return out


# -----------------
# Write path
# -----------------


def decide_and_issue_one(
    *,
    ctx: IssueContext,
    qty_each: int,
    decision: IssueDecision,
    request_id: str | None,
    reason: str | None,
    note: str | None,
) -> IssueResult:
    """
    Write path: reduce batch + stock, record Movement + Issue, emit Ledger event.
    Caller must commit (CLI should do db.session.commit().
    """
    sku_code = (ctx.sku_code or "").strip()
    if not validate_sku(sku_code):
        return IssueResult(ok=False, reason="invalid_sku", decision=decision)

    if not ctx.customer_ulid:
        return IssueResult(
            ok=False, reason="customer_required", decision=decision
        )

    if not ctx.location_ulid:
        return IssueResult(
            ok=False, reason="location_required", decision=decision
        )

    as_of_dt = ctx.as_of_dt or utcnow_aware()
    as_of_iso = to_iso8601(as_of_dt)
    req_id = request_id or new_ulid()
    ckey = ctx.classification_key or classification_key_for(sku_code)

    item = db.session.execute(
        select(InventoryItem).where(InventoryItem.sku == sku_code)
    ).scalar_one_or_none()
    if item is None:
        return IssueResult(
            ok=False, reason="sku_not_found", decision=decision
        )

    stock = db.session.execute(
        select(InventoryStock).where(
            InventoryStock.item_ulid == item.ulid,
            InventoryStock.location_ulid == ctx.location_ulid,
        )
    ).scalar_one_or_none()
    if stock is None or stock.quantity < qty_each:
        return IssueResult(ok=False, reason="out_of_stock", decision=decision)

    if ctx.batch_ulid:
        batch = db.session.execute(
            select(InventoryBatch).where(
                InventoryBatch.ulid == ctx.batch_ulid,
                InventoryBatch.location_ulid == ctx.location_ulid,
            )
        ).scalar_one_or_none()
    else:
        batch = db.session.execute(
            select(InventoryBatch)
            .where(
                InventoryBatch.item_ulid == item.ulid,
                InventoryBatch.location_ulid == ctx.location_ulid,
                InventoryBatch.quantity >= qty_each,
            )
            .order_by(InventoryBatch.ulid.desc())
            .limit(1)
        ).scalar_one_or_none()

    if batch is None or batch.quantity < qty_each:
        return IssueResult(ok=False, reason="out_of_stock", decision=decision)

    batch.quantity -= qty_each
    stock.quantity -= qty_each

    movement_ulid = new_ulid()
    issue_ulid = new_ulid()

    mv = InventoryMovement(
        ulid=movement_ulid,
        item_ulid=item.ulid,
        location_ulid=ctx.location_ulid,
        batch_ulid=batch.ulid,
        kind="issue",
        quantity=qty_each,
        unit=item.unit or stock.unit or "each",
        happened_at_utc=as_of_iso,
        source_ref_ulid=None,
        target_ref_ulid=ctx.customer_ulid,
        created_by_actor=ctx.actor_ulid,
        note=note,
    )
    db.session.add(mv)

    issue = Issue(
        ulid=issue_ulid,
        customer_ulid=ctx.customer_ulid,
        classification_key=ckey,
        sku_code=sku_code,
        quantity=qty_each,
        issued_at=as_of_iso,
        project_ulid=ctx.project_ulid,
        movement_ulid=movement_ulid,
        created_by_actor=ctx.actor_ulid,
        decision_json=stable_dumps(
            {
                "allowed": decision.allowed,
                "reason": decision.reason,
                "approver_required": decision.approver_required,
                "limit_window_label": decision.limit_window_label,
                "next_eligible_at_iso": decision.next_eligible_at_iso,
                "request_id": req_id,
                "note": note,
                "reason_freeform": reason,
            }
        ),
    )
    db.session.add(issue)

    db.session.flush()

    event_bus.emit(
        domain="logistics",
        operation="issue",
        request_id=req_id,
        actor_ulid=ctx.actor_ulid,
        target_ulid=ctx.customer_ulid,
        refs={
            "issue_ulid": issue_ulid,
            "movement_ulid": movement_ulid,
            "sku": sku_code,
            "classification_key": ckey,
            "batch_ulid": batch.ulid,
            "location_ulid": ctx.location_ulid,
            "project_ulid": ctx.project_ulid,
        },
        meta={
            "qty_each": qty_each,
            "decision_reason": decision.reason,
            "note": note,
            "reason": reason,
        },
        happened_at_utc=as_of_iso,
    )

    return IssueResult(
        ok=True,
        reason="issued",
        issue_ulid=issue_ulid,
        movement_ulid=movement_ulid,
        item_ulid=item.ulid,
        batch_ulid=batch.ulid,
        qty_each=qty_each,
        decision=decision,
    )


# -----------------
# Qualifiers + cadence
# -----------------


def _get_customer_cues(ctx: IssueContext) -> CustomerCuesDTO | None:
    """Lazy-load Customer cues into ctx.

    This is the *only* cross-slice read performed by the Logistics decision engine.
    It is cached in the IssueContext so SKU filtering can reuse one DTO.

    Fail-safe behavior: if the customer does not exist or the contract errors,
    return None (qualifiers that require cues will fail closed).
    """
    if ctx.customer_cues is not None:
        return ctx.customer_cues

    if not ctx.customer_ulid:
        ctx.customer_cues = None
        return None

    try:
        ctx.customer_cues = get_customer_cues(entity_ulid=ctx.customer_ulid)
    except Exception:
        ctx.customer_cues = None

    return ctx.customer_cues


def _cadence_from(rule: dict, *, defaults_cadence: dict) -> dict:
    out = dict(defaults_cadence or {})
    rc = rule.get("cadence") or {}
    if isinstance(rc, dict):
        out.update({k: v for k, v in rc.items() if v is not None})
    return out


def _cadence_enforcement(rule: dict, *, ctx: IssueContext) -> str:
    cad = _cadence_from(
        rule or {}, defaults_cadence=ctx.defaults_cadence or {}
    )
    return str(cad.get("enforcement") or "hard").strip().lower()


def _apply_cadence(
    rule: dict, ctx: IssueContext
) -> tuple[bool, str | None, str | None]:
    cad = _cadence_from(
        rule or {}, defaults_cadence=ctx.defaults_cadence or {}
    )
    label = cad.get("label")
    period_days = int(cad.get("period_days", 0) or 0)
    max_per = int(cad.get("max_per_period", 0) or 0)
    scope = (cad.get("scope") or "classification").lower()

    if not period_days or not max_per:
        return True, label, None

    as_of_dt = ctx.as_of_dt or utcnow_aware()
    if not isinstance(as_of_dt, datetime):
        raise TypeError("ctx.as_of_dt must be a datetime")

    as_of_naive = as_naive_utc(as_of_dt)
    as_of_iso = to_iso8601(as_of_dt)
    window_start_dt = as_of_naive - timedelta(days=period_days)
    window_start_iso = to_iso8601(window_start_dt)

    if not ctx.customer_ulid:
        return False, label, None

    if scope == "sku":
        count = _count_issues_in_window(
            customer_ulid=ctx.customer_ulid,
            sku_code=ctx.sku_code,
            window_start_iso=window_start_iso,
            as_of_iso=as_of_iso,
        )
        oldest_blocking = _nth_oldest_issue_at_in_window(
            customer_ulid=ctx.customer_ulid,
            sku_code=ctx.sku_code,
            window_start_iso=window_start_iso,
            as_of_iso=as_of_iso,
            n=max_per,
        )
    else:
        count = _count_issues_in_window(
            customer_ulid=ctx.customer_ulid,
            classification_key=ctx.classification_key,
            window_start_iso=window_start_iso,
            as_of_iso=as_of_iso,
        )
        oldest_blocking = _nth_oldest_issue_at_in_window(
            customer_ulid=ctx.customer_ulid,
            classification_key=ctx.classification_key,
            window_start_iso=window_start_iso,
            as_of_iso=as_of_iso,
            n=max_per,
        )

    if count < max_per:
        return True, label, None

    base_dt = (
        as_naive_utc(parse_iso8601(oldest_blocking))
        if oldest_blocking
        else window_start_dt
    )
    next_eligible_dt = base_dt + timedelta(days=period_days)
    next_eligible_iso = to_iso8601(next_eligible_dt)
    return False, label, next_eligible_iso


# -----------------
# Rule matching + invariants
# -----------------


def _rule_matches(rule: dict, ctx: IssueContext) -> bool:
    m = rule.get("match") or {}
    if not isinstance(m, dict):
        return False

    sku_code = ctx.sku_code or ""
    parts = ctx.sku_parts or (parse_sku(sku_code) if sku_code else None)
    if parts is None:
        return False

    r_ckey = m.get("classification_key")
    if r_ckey is not None:
        if (ctx.classification_key or "") != r_ckey:
            return False

    r_glob = m.get("sku")
    if r_glob:
        if not fnmatch(sku_code, r_glob):
            return False

    r_parts = m.get("sku_parts") or {}
    if r_parts:
        for human_k, expected in r_parts.items():
            pk = _PART_KEY_MAP.get(human_k, human_k)
            if parts.get(pk) != expected:
                return False

    return True


def _check_sku_constraints(
    rule: dict, ctx: IssueContext
) -> tuple[bool, str | None]:
    if not ctx.sku_code:
        return True, None

    p = parse_sku(ctx.sku_code)

    if p.get("src") == "DR":
        if p.get("issuance_class") != "V":
            return False, "sku_restricted"

    if p.get("cat") == "CG" and p.get("sub") == "SL" and p.get("src") == "LC":
        if p.get("issuance_class") != "H":
            return False, "sku_restricted"

    return True, None


# -----------------
# Small helpers
# -----------------


def _decision(
    ok: bool,
    reason: str,
    *,
    approver_required: str | None = None,
    limit_window_label: str | None = None,
    next_eligible_at_iso: str | None = None,
    cadence_enforcement: str | None = None,
    override_requested: bool = False,
    override_used: bool = False,
) -> IssueDecision:
    return IssueDecision(
        allowed=bool(ok),
        reason=reason,
        approver_required=approver_required,
        limit_window_label=limit_window_label,
        next_eligible_at_iso=next_eligible_at_iso,
        cadence_enforcement=cadence_enforcement,
        override_requested=bool(override_requested),
        override_used=bool(override_used),
    )


def _norm_gate(ok: Any, meta: Any, default_reason: str) -> tuple[bool, str]:
    if ok is True:
        return True, "ok"
    if isinstance(meta, str) and meta:
        return False, meta
    if isinstance(meta, dict):
        why = meta.get("reason") or meta.get("why")
        if isinstance(why, str) and why:
            return False, why
    return False, default_reason


# -----------------
# Decision engine helpers
# -----------------


def _count_issues_in_window(
    *,
    customer_ulid: str,
    window_start_iso: str,
    as_of_iso: str,
    sku_code: str | None = None,
    classification_key: str | None = None,
) -> int:
    """
    Local cadence counter (no self-contract calls).
    Assumes issued_at is ISO UTC text so lexical ordering works.
    """
    q = (
        select(func.count())
        .select_from(Issue)
        .where(
            Issue.customer_ulid == customer_ulid,
            Issue.issued_at >= window_start_iso,
            Issue.issued_at <= as_of_iso,
        )
    )

    if sku_code:
        q = q.where(Issue.sku_code == sku_code)

    if classification_key:
        q = q.where(Issue.classification_key == classification_key)

    return int(db.session.execute(q).scalar_one() or 0)


def _nth_oldest_issue_at_in_window(
    *,
    customer_ulid: str,
    window_start_iso: str,
    as_of_iso: str,
    n: int,
    sku_code: str | None = None,
    classification_key: str | None = None,
) -> str | None:
    """
    Return the issued_at ISO for the Nth oldest issue in the window (1-based).
    """
    if n <= 0:
        return None

    q = select(Issue.issued_at).where(
        Issue.customer_ulid == customer_ulid,
        Issue.issued_at >= window_start_iso,
        Issue.issued_at <= as_of_iso,
    )
    if sku_code:
        q = q.where(Issue.sku_code == sku_code)
    if classification_key:
        q = q.where(Issue.classification_key == classification_key)

    q = q.order_by(Issue.issued_at.asc()).offset(n - 1).limit(1)
    return db.session.execute(q).scalar_one_or_none()
