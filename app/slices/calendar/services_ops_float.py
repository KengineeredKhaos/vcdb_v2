from __future__ import annotations

"""Calendar ops-float services using canonical published demand context."""

from app.extensions import db, event_bus
from app.extensions.contracts import finance_v2, governance_v2
from app.lib.chrono import now_iso8601_ms

from .mapper import OpsFloatAllocationResult, OpsFloatSettlementResult
from .services_funding import _get_demand_or_raise, get_funding_demand_context
from .taxonomy import OPS_FLOAT_SUPPORT_MODES

_SOURCE_OK = {"published", "funding_in_progress", "funded", "executing"}
_DEST_OK = {"published", "funding_in_progress", "funded", "executing"}
_REPAY_OK = {"funding_in_progress", "funded", "executing", "closed"}
_FORGIVE_OK = {"closed"}



def _has_required_approvals(
    required_approvals: tuple[str, ...] | list[str],
    *,
    actor_rbac_roles: tuple[str, ...] = (),
    actor_domain_roles: tuple[str, ...] = (),
) -> bool:
    held = set(actor_rbac_roles or ()) | set(actor_domain_roles or ())
    return all(req in held for req in (required_approvals or ()))



def _tupleish(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(x).strip() for x in value if str(x).strip())
    text = str(value).strip()
    return (text,) if text else ()



def _dest_context(funding_demand_ulid: str) -> dict[str, object]:
    payload = get_funding_demand_context(funding_demand_ulid)
    planning = dict(payload.get("planning") or {})
    policy = dict(payload.get("policy") or {})
    return {
        "spending_class": planning.get("spending_class"),
        "tag_any": _tupleish(policy.get("approved_tag_any") or planning.get("tag_any")),
        "eligible_fund_codes": _tupleish(policy.get("eligible_fund_codes")),
        "ops_support_planned": planning.get("ops_support_planned"),
    }



def allocate_ops_float_to_project(
    *,
    source_funding_demand_ulid: str,
    dest_funding_demand_ulid: str,
    fund_code: str,
    amount_cents: int,
    support_mode: str,
    memo: str | None = None,
    source_ref_ulid: str | None = None,
    actor_ulid: str | None,
    actor_rbac_roles: tuple[str, ...] = (),
    actor_domain_roles: tuple[str, ...] = (),
    request_id: str | None,
    dry_run: bool = False,
) -> OpsFloatAllocationResult:
    if not source_funding_demand_ulid:
        raise ValueError("source_funding_demand_ulid required")
    if not dest_funding_demand_ulid:
        raise ValueError("dest_funding_demand_ulid required")
    if source_funding_demand_ulid == dest_funding_demand_ulid:
        raise ValueError("source and destination funding demands must differ")
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")
    if not fund_code:
        raise ValueError("fund_code required")
    if support_mode not in set(OPS_FLOAT_SUPPORT_MODES):
        raise ValueError(f"invalid ops float support_mode: {support_mode}")

    source = _get_demand_or_raise(source_funding_demand_ulid)
    dest = _get_demand_or_raise(dest_funding_demand_ulid)
    if source.status not in _SOURCE_OK:
        raise ValueError("source funding demand is not available for ops float")
    if dest.status not in _DEST_OK:
        raise ValueError(
            "destination funding demand is not available for ops float"
        )

    ctx = _dest_context(dest.ulid)
    if ctx["eligible_fund_codes"] and fund_code not in tuple(
        ctx["eligible_fund_codes"] or ()
    ):
        raise ValueError("selected fund is not eligible for destination")
    if not str(ctx["spending_class"] or "").strip():
        raise ValueError("destination published demand context missing spending_class")

    preview = governance_v2.preview_ops_float(
        governance_v2.OpsFloatDecisionRequestDTO(
            support_mode=support_mode,
            amount_cents=amount_cents,
            fund_code=fund_code,
            source_funding_demand_ulid=source.ulid,
            source_project_ulid=source.project_ulid,
            dest_funding_demand_ulid=dest.ulid,
            dest_project_ulid=dest.project_ulid,
            spending_class=str(ctx["spending_class"] or "").strip() or None,
            tag_any=tuple(ctx["tag_any"] or ()),
            dest_eligible_fund_codes=tuple(ctx["eligible_fund_codes"] or ()),
            ops_support_planned=ctx["ops_support_planned"],
            actor_rbac_roles=actor_rbac_roles,
            actor_domain_roles=actor_domain_roles,
        )
    )
    if not preview.allowed:
        raise PermissionError("; ".join(preview.reason_codes) or "ops float denied")

    if preview.required_approvals and not _has_required_approvals(
        preview.required_approvals,
        actor_rbac_roles=actor_rbac_roles,
        actor_domain_roles=actor_domain_roles,
    ):
        raise PermissionError(
            "ops float requires approvals: " + ", ".join(preview.required_approvals)
        )

    out = finance_v2.allocate_ops_float(
        finance_v2.OpsFloatRequestDTO(
            source_funding_demand_ulid=source.ulid,
            source_project_ulid=source.project_ulid,
            dest_funding_demand_ulid=dest.ulid,
            dest_project_ulid=dest.project_ulid,
            fund_code=fund_code,
            amount_cents=amount_cents,
            support_mode=support_mode,
            decision_fingerprint=preview.decision_fingerprint,
            source_ref_ulid=source_ref_ulid,
            memo=memo,
            actor_ulid=actor_ulid,
            request_id=request_id,
            dry_run=dry_run,
        )
    )

    old_status = dest.status
    new_status = dest.status
    if not dry_run and dest.status == "published":
        dest.status = "funding_in_progress"
        db.session.flush()
        new_status = dest.status

    event_bus.emit(
        domain="calendar",
        operation="ops_float_allocated",
        request_id=str(request_id or out.id),
        actor_ulid=actor_ulid,
        target_ulid=dest.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "source_funding_demand_ulid": source.ulid,
            "source_project_ulid": source.project_ulid,
            "dest_funding_demand_ulid": dest.ulid,
            "dest_project_ulid": dest.project_ulid,
            "ops_float_ulid": out.id,
            "fund_code": fund_code,
            "support_mode": support_mode,
            "decision_fingerprint": preview.decision_fingerprint,
        },
        changed={"fields": ["status"]} if new_status != old_status else None,
    )

    return OpsFloatAllocationResult(
        source_funding_demand_ulid=source.ulid,
        dest_funding_demand_ulid=dest.ulid,
        source_project_ulid=source.project_ulid,
        dest_project_ulid=dest.project_ulid,
        fund_code=fund_code,
        amount_cents=amount_cents,
        support_mode=support_mode,
        ops_float_ulid=out.id,
        decision_fingerprint=preview.decision_fingerprint,
        status=new_status,
        flags=tuple(out.flags or ()),
    )



def _bucket_amount(rows, key: str) -> int:
    for row in rows or ():
        if row.key == key:
            return int(row.amount_cents or 0)
    return 0



def repay_ops_float_to_operations(
    *,
    parent_ops_float_ulid: str,
    amount_cents: int,
    memo: str | None = None,
    source_ref_ulid: str | None = None,
    actor_ulid: str | None,
    actor_rbac_roles: tuple[str, ...] = (),
    actor_domain_roles: tuple[str, ...] = (),
    request_id: str | None,
    dry_run: bool = False,
) -> OpsFloatSettlementResult:
    if not parent_ops_float_ulid:
        raise ValueError("parent_ops_float_ulid required")
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")

    parent = finance_v2.get_ops_float(parent_ops_float_ulid)
    if parent.action != "allocate":
        raise ValueError("parent ops float must be an allocation")
    if parent.open_cents <= 0:
        raise ValueError("parent ops float has no open balance")

    source = _get_demand_or_raise(parent.source_funding_demand_ulid)
    dest = _get_demand_or_raise(parent.dest_funding_demand_ulid)
    if dest.status not in _REPAY_OK:
        raise ValueError(
            "destination funding demand is not available for ops float repayment"
        )

    money = finance_v2.get_funding_demand_money_view(dest.ulid)
    direct_available = _bucket_amount(
        money.reserved_by_fund, parent.fund_code
    ) - _bucket_amount(money.encumbered_by_fund, parent.fund_code)
    if amount_cents > direct_available:
        raise ValueError("ops float repayment exceeds direct available funds")

    ctx = _dest_context(dest.ulid)
    preview = governance_v2.preview_ops_float(
        governance_v2.OpsFloatDecisionRequestDTO(
            action="repay",
            support_mode=parent.support_mode,
            amount_cents=amount_cents,
            fund_code=parent.fund_code,
            source_funding_demand_ulid=source.ulid,
            source_project_ulid=source.project_ulid,
            dest_funding_demand_ulid=dest.ulid,
            dest_project_ulid=dest.project_ulid,
            spending_class=str(ctx["spending_class"] or "").strip() or None,
            tag_any=tuple(ctx["tag_any"] or ()),
            dest_eligible_fund_codes=tuple(ctx["eligible_fund_codes"] or ()),
            ops_support_planned=ctx["ops_support_planned"],
            actor_rbac_roles=actor_rbac_roles,
            actor_domain_roles=actor_domain_roles,
        )
    )
    if not preview.allowed:
        raise PermissionError("; ".join(preview.reason_codes) or "ops float denied")

    if preview.required_approvals and not _has_required_approvals(
        preview.required_approvals,
        actor_rbac_roles=actor_rbac_roles,
        actor_domain_roles=actor_domain_roles,
    ):
        raise PermissionError(
            "ops float requires approvals: " + ", ".join(preview.required_approvals)
        )

    out = finance_v2.repay_ops_float(
        finance_v2.OpsFloatSettleRequestDTO(
            parent_ops_float_ulid=parent.ops_float_ulid,
            amount_cents=amount_cents,
            source_ref_ulid=source_ref_ulid,
            memo=memo,
            actor_ulid=actor_ulid,
            request_id=request_id,
            dry_run=dry_run,
        )
    )

    event_bus.emit(
        domain="calendar",
        operation="ops_float_repaid",
        request_id=str(request_id or out.id),
        actor_ulid=actor_ulid,
        target_ulid=dest.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "parent_ops_float_ulid": parent.ops_float_ulid,
            "source_funding_demand_ulid": source.ulid,
            "source_project_ulid": source.project_ulid,
            "dest_funding_demand_ulid": dest.ulid,
            "dest_project_ulid": dest.project_ulid,
            "ops_float_ulid": out.id,
            "fund_code": parent.fund_code,
            "support_mode": parent.support_mode,
            "decision_fingerprint": preview.decision_fingerprint,
        },
    )

    return OpsFloatSettlementResult(
        parent_ops_float_ulid=parent.ops_float_ulid,
        ops_float_ulid=out.id,
        action="repay",
        support_mode=parent.support_mode,
        source_funding_demand_ulid=source.ulid,
        source_project_ulid=source.project_ulid,
        dest_funding_demand_ulid=dest.ulid,
        dest_project_ulid=dest.project_ulid,
        fund_code=parent.fund_code,
        amount_cents=amount_cents,
        decision_fingerprint=preview.decision_fingerprint,
        flags=tuple(out.flags or ()),
    )



def forgive_ops_float_shortfall(
    *,
    parent_ops_float_ulid: str,
    amount_cents: int,
    memo: str | None = None,
    source_ref_ulid: str | None = None,
    actor_ulid: str | None,
    actor_rbac_roles: tuple[str, ...] = (),
    actor_domain_roles: tuple[str, ...] = (),
    request_id: str | None,
    dry_run: bool = False,
) -> OpsFloatSettlementResult:
    if not parent_ops_float_ulid:
        raise ValueError("parent_ops_float_ulid required")
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")

    parent = finance_v2.get_ops_float(parent_ops_float_ulid)
    if parent.action != "allocate":
        raise ValueError("parent ops float must be an allocation")
    if parent.open_cents <= 0:
        raise ValueError("parent ops float has no open balance")

    source = _get_demand_or_raise(parent.source_funding_demand_ulid)
    dest = _get_demand_or_raise(parent.dest_funding_demand_ulid)
    if dest.status not in _FORGIVE_OK:
        raise ValueError(
            "destination funding demand must be closed for forgiveness"
        )

    ctx = _dest_context(dest.ulid)
    preview = governance_v2.preview_ops_float(
        governance_v2.OpsFloatDecisionRequestDTO(
            action="forgive",
            support_mode=parent.support_mode,
            amount_cents=amount_cents,
            fund_code=parent.fund_code,
            source_funding_demand_ulid=source.ulid,
            source_project_ulid=source.project_ulid,
            dest_funding_demand_ulid=dest.ulid,
            dest_project_ulid=dest.project_ulid,
            spending_class=str(ctx["spending_class"] or "").strip() or None,
            tag_any=tuple(ctx["tag_any"] or ()),
            dest_eligible_fund_codes=tuple(ctx["eligible_fund_codes"] or ()),
            ops_support_planned=ctx["ops_support_planned"],
            actor_rbac_roles=actor_rbac_roles,
            actor_domain_roles=actor_domain_roles,
        )
    )
    if not preview.allowed:
        raise PermissionError("; ".join(preview.reason_codes) or "ops float denied")

    if preview.required_approvals and not _has_required_approvals(
        preview.required_approvals,
        actor_rbac_roles=actor_rbac_roles,
        actor_domain_roles=actor_domain_roles,
    ):
        raise PermissionError(
            "ops float requires approvals: " + ", ".join(preview.required_approvals)
        )

    out = finance_v2.forgive_ops_float(
        finance_v2.OpsFloatSettleRequestDTO(
            parent_ops_float_ulid=parent.ops_float_ulid,
            amount_cents=amount_cents,
            source_ref_ulid=source_ref_ulid,
            memo=memo,
            actor_ulid=actor_ulid,
            request_id=request_id,
            dry_run=dry_run,
        )
    )

    event_bus.emit(
        domain="calendar",
        operation="ops_float_forgiven",
        request_id=str(request_id or out.id),
        actor_ulid=actor_ulid,
        target_ulid=dest.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "parent_ops_float_ulid": parent.ops_float_ulid,
            "source_funding_demand_ulid": source.ulid,
            "source_project_ulid": source.project_ulid,
            "dest_funding_demand_ulid": dest.ulid,
            "dest_project_ulid": dest.project_ulid,
            "ops_float_ulid": out.id,
            "fund_code": parent.fund_code,
            "support_mode": parent.support_mode,
            "decision_fingerprint": preview.decision_fingerprint,
        },
    )

    return OpsFloatSettlementResult(
        parent_ops_float_ulid=parent.ops_float_ulid,
        ops_float_ulid=out.id,
        action="forgive",
        support_mode=parent.support_mode,
        source_funding_demand_ulid=source.ulid,
        source_project_ulid=source.project_ulid,
        dest_funding_demand_ulid=dest.ulid,
        dest_project_ulid=dest.project_ulid,
        fund_code=parent.fund_code,
        amount_cents=amount_cents,
        decision_fingerprint=preview.decision_fingerprint,
        flags=tuple(out.flags or ()),
    )
