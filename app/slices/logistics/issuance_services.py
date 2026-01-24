# app/slices/logistics/issuance_services.py

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta
from fnmatch import fnmatch
from typing import Any, Optional

from sqlalchemy import func, select

from app.extensions import db, event_bus
from app.extensions.contracts.customers_v2 import get_needs_profile
from app.extensions.policies import (
    load_policy_logistics_issuance,
    load_policy_sku_constraints,
)
from app.lib.chrono import as_naive_utc, now_iso8601_ms
from app.lib.ids import new_ulid
from app.lib.jsonutil import stable_dumps

from .models import (
    InventoryBatch,
    InventoryItem,
    InventoryMovement,
    InventoryStock,
    Issue,
)
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

    customer_ulid: Optional[str]
    sku_code: Optional[str]
    when_iso: Optional[str] = None

    # Optional task context (Scenario #3 durable goods)
    project_ulid: Optional[str] = None

    # Optional operational details (write path)
    location_ulid: Optional[str] = None
    batch_ulid: Optional[str] = None

    # Actor info (for overrides, audit)
    actor_ulid: Optional[str] = None
    actor_domain_roles: Optional[list[str]] = None

    # Controls
    force_blackout: bool = False
    override_cadence: bool = False

    # Derived / cached
    sku_parts: Optional[dict[str, str]] = None
    classification_key: Optional[str] = None

    # Cached cross-slice snapshot (avoid N calls for N SKUs)
    needs_profile: Optional[dict[str, Any]] = None

    # Working fields (set by decide_issue)
    qualifiers: dict[str, Any] = field(default_factory=dict)
    defaults_cadence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IssueDecision:
    allowed: bool
    reason: str

    approver_required: Optional[str] = None
    limit_window_label: Optional[str] = None
    next_eligible_at_iso: Optional[str] = None


@dataclass(frozen=True)
class IssueResult:
    ok: bool
    reason: str

    issue_ulid: Optional[str] = None
    movement_ulid: Optional[str] = None
    item_ulid: Optional[str] = None
    batch_ulid: Optional[str] = None
    qty_each: int = 0

    decision: Optional[IssueDecision] = None


# Back-compat alias (older callers)
def issue_inventory_policy(ctx: IssueContext) -> IssueDecision:
    return decide_issue(ctx)


# -----------------
# Public entry points
# -----------------


def issue_inventory(
    *,
    customer_ulid: str | None,
    sku_code: str,
    qty_each: int = 1,
    when_iso: Optional[str] = None,
    project_ulid: Optional[str] = None,
    location_ulid: Optional[str] = None,
    batch_ulid: Optional[str] = None,
    actor_ulid: Optional[str] = None,
    actor_domain_roles: Optional[list[str]] = None,
    override_cadence: bool = False,
    force_blackout: bool = False,
    request_id: Optional[str] = None,
    reason: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Mutating entry point: evaluate policy then write Issue + decrement stock.

    Returns a plain dict suitable for JSON routes/CLI.
    """
    ctx = IssueContext(
        customer_ulid=customer_ulid,
        sku_code=sku_code,
        when_iso=when_iso or now_iso8601_ms(),
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
    if ctx.when_iso is None:
        ctx.when_iso = now_iso8601_ms()

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

        if ctx.override_cadence and "governor" in (
            ctx.actor_domain_roles or []
        ):
            return _decision(True, "cadence_overridden")

        return _decision(
            False,
            "cadence_limit",
            approver_required="governor",
            limit_window_label=window_label,
            next_eligible_at_iso=next_eligible,
        )

    # -------- 5) matched rules → merged qualifiers then cadence --------
    ctx.qualifiers = _merge_qualifiers(matches)

    ok_q, why_q = _check_qualifiers(ctx)
    ok_q, why_q = _norm_gate(ok_q, why_q, "qualifiers_not_met")
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

    if ctx.override_cadence and "governor" in (ctx.actor_domain_roles or []):
        return _decision(True, "cadence_overridden")

    return _decision(
        False,
        "cadence_limit",
        approver_required="governor",
        limit_window_label=window_label,
        next_eligible_at_iso=next_eligible,
    )


def available_skus_for_customer(
    *,
    customer_ulid: str,
    as_of_iso: Optional[str] = None,
    location_ulid: Optional[str] = None,
    include_out_of_stock: bool = False,
    actor_ulid: Optional[str] = None,
    actor_domain_roles: Optional[list[str]] = None,
    override_cadence: bool = False,
) -> list[str]:
    """
    Read-only helper used by contracts/UI: return SKUs eligible *right now* for this customer.

    Notes:
      - This DOES evaluate cadence (so the picker won't offer blocked SKUs).
      - If include_out_of_stock is False and location_ulid is provided, we require stock > 0 at that location.
    """
    prof = get_needs_profile(customer_ulid=customer_ulid)

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
            when_iso=as_of_iso or now_iso8601_ms(),
            location_ulid=location_ulid,
            actor_ulid=actor_ulid,
            actor_domain_roles=actor_domain_roles or [],
            override_cadence=override_cadence,
            needs_profile=prof,
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
    Caller must commit (CLI should do db.session.commit()).
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

    as_of = ctx.when_iso or now_iso8601_ms()
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

    # --- apply stock deltas ---
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
        happened_at_utc=as_of,
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
        issued_at=as_of,
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

    # Ledger slice write (event bus) — does NOT touch logistics tables.
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
        happened_at_utc=as_of,
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


def _get_needs_profile(ctx: IssueContext) -> dict[str, Any]:
    if ctx.needs_profile is None:
        if not ctx.customer_ulid:
            ctx.needs_profile = {}
        else:
            ctx.needs_profile = get_needs_profile(
                customer_ulid=ctx.customer_ulid
            )
    return ctx.needs_profile or {}


def _check_qualifiers(ctx: IssueContext) -> tuple[bool, str | None]:
    q = ctx.qualifiers or {}
    if not q:
        return True, None

    prof = _get_needs_profile(ctx)

    if q.get("veteran_required") is True:
        if not bool(prof.get("is_veteran_verified")):
            return False, "veteran_required"

    if q.get("homeless_required") is True:
        if not bool(prof.get("is_homeless_verified")):
            return False, "homeless_required"

    return True, None


def _cadence_from(rule: dict, *, defaults_cadence: dict) -> dict:
    out = dict(defaults_cadence or {})
    rc = rule.get("cadence") or {}
    if isinstance(rc, dict):
        out.update({k: v for k, v in rc.items() if v is not None})
    return out


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

    as_of = ctx.when_iso or now_iso8601_ms()
    as_of_dt = as_naive_utc(as_of)
    window_start_dt = as_of_dt - timedelta(days=period_days)

    window_start_iso = (
        window_start_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z"
    )

    if not ctx.customer_ulid:
        return False, label, None

    if scope == "sku":
        count = _count_issues_in_window(
            customer_ulid=ctx.customer_ulid,
            sku_code=ctx.sku_code,
            window_start_iso=window_start_iso,
            as_of_iso=as_of,
        )
    else:
        count = _count_issues_in_window(
            customer_ulid=ctx.customer_ulid,
            classification_key=ctx.classification_key,
            window_start_iso=window_start_iso,
            as_of_iso=as_of,
        )

    if count < max_per:
        return True, label, None

    next_eligible_dt = window_start_dt + timedelta(days=period_days)
    next_eligible_iso = (
        next_eligible_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z"
    )
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
    approver_required: Optional[str] = None,
    limit_window_label: Optional[str] = None,
    next_eligible_at_iso: Optional[str] = None,
) -> IssueDecision:
    return IssueDecision(
        allowed=bool(ok),
        reason=reason,
        approver_required=approver_required,
        limit_window_label=limit_window_label,
        next_eligible_at_iso=next_eligible_at_iso,
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
    sku_code: Optional[str] = None,
    classification_key: Optional[str] = None,
) -> Optional[str]:
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
