# app/slices/calendar/services_finance_bridge.py

from __future__ import annotations

from dataclasses import dataclass

from app.extensions import db, event_bus
from app.extensions.contracts import finance_v2, governance_v2
from app.lib.chrono import now_iso8601_ms
from app.slices.calendar.mapper import (
    ProjectEncumbranceResult,
    ProjectSpendResult,
)
from app.slices.calendar.models import FundingDemand
from app.slices.calendar.services_funding import (
    _build_funding_decision_request,
    _get_demand_or_raise,
)

_TEMP_KEYS = {"temp", "temporary", "temporarily_restricted"}
_PERM_KEYS = {"perm", "permanent", "permanently_restricted"}
_ENCUMBER_OK = {
    "published",
    "funding_in_progress",
    "funded",
    "executing",
}
_SPEND_OK = {"funding_in_progress", "funded", "executing"}


def _derive_restriction_type(
    *,
    restriction_keys: tuple[str, ...],
    archetype: str,
) -> str:
    keys = {str(k).strip().lower() for k in restriction_keys}
    archetype_norm = (archetype or "").strip().lower()

    if keys.intersection(_PERM_KEYS) or archetype_norm in _PERM_KEYS:
        return "permanently_restricted"
    if keys.intersection(_TEMP_KEYS) or archetype_norm in _TEMP_KEYS:
        return "temporarily_restricted"
    return "unrestricted"


def _bucket_amount(rows, key: str) -> int:
    for row in rows or ():
        if row.key == key:
            return int(row.amount_cents or 0)
    return 0


def encumber_project_funds(
    *,
    funding_demand_ulid: str,
    amount_cents: int,
    fund_key: str,
    expense_kind: str,
    happened_at_utc: str,
    source_ref_ulid: str | None = None,
    memo: str | None = None,
    actor_ulid: str | None,
    actor_rbac_roles: tuple[str, ...] = (),
    actor_domain_roles: tuple[str, ...] = (),
    request_id: str | None,
    dry_run: bool = False,
) -> ProjectEncumbranceResult:
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")
    if not fund_key:
        raise ValueError("fund_key required")
    if not expense_kind:
        raise ValueError("expense_kind required")
    if not happened_at_utc:
        raise ValueError("happened_at_utc required")

    row = _get_demand_or_raise(funding_demand_ulid)
    if row.status not in _ENCUMBER_OK:
        raise ValueError(
            "funding demand must be published, funding_in_progress, "
            "funded, or executing"
        )
    if not row.spending_class:
        raise ValueError("funding demand spending_class required")

    money = finance_v2.get_funding_demand_money_view(row.ulid)
    ops_float = finance_v2.get_ops_float_summary(row.ulid)
    available_reserved = (
        _bucket_amount(money.reserved_by_fund, fund_key)
        + _bucket_amount(ops_float.incoming_open_by_fund, fund_key)
        - _bucket_amount(money.encumbered_by_fund, fund_key)
    )
    if amount_cents > available_reserved:
        raise ValueError("encumbrance exceeds available reserved funds")

    fund_meta = governance_v2.get_fund_key(fund_key)
    restriction_keys = governance_v2.apply_fund_defaults(
        fund_key=fund_key,
        restriction_keys=(),
    )
    sem = governance_v2.validate_semantic_keys(
        fund_key=fund_key,
        restriction_keys=restriction_keys,
        expense_kind=expense_kind,
        spending_class=row.spending_class,
        demand_eligible_fund_keys=tuple(row.eligible_fund_keys_json or ()),
    )
    if not sem.ok:
        raise ValueError("; ".join(sem.errors) or "invalid semantics")

    preview = governance_v2.preview_funding_decision(
        _build_funding_decision_request(
            row=row,
            op="spend",
            amount_cents=amount_cents,
            funding_demand_ulid=row.ulid,
            project_ulid=row.project_ulid,
            spending_class=row.spending_class,
            expense_kind=expense_kind,
            restriction_keys=restriction_keys,
            demand_eligible_fund_keys=tuple(
                row.eligible_fund_keys_json or ()
            ),
            tag_any=tuple(row.tag_any_json or ()),
            selected_fund_key=fund_key,
            actor_rbac_roles=actor_rbac_roles,
            actor_domain_roles=actor_domain_roles,
        )
    )
    if not preview.allowed:
        raise PermissionError(
            "; ".join(preview.reason_codes) or "encumber denied"
        )
    if preview.required_approvals:
        raise PermissionError(
            "encumber requires approvals: "
            + ", ".join(preview.required_approvals)
        )

    fund_restriction_type = _derive_restriction_type(
        restriction_keys=restriction_keys,
        archetype=fund_meta.archetype,
    )
    memo_txt = memo or f"encumber:{expense_kind}"

    out = finance_v2.encumber_funds(
        finance_v2.EncumbranceRequestDTO(
            funding_demand_ulid=row.ulid,
            fund_key=fund_key,
            amount_cents=amount_cents,
            source="calendar",
            fund_label=fund_meta.label,
            fund_restriction_type=fund_restriction_type,
            project_ulid=row.project_ulid,
            source_ref_ulid=source_ref_ulid,
            memo=memo_txt,
            decision_fingerprint=preview.decision_fingerprint,
            actor_ulid=actor_ulid,
            request_id=request_id,
            dry_run=dry_run,
        )
    )
    old_status = row.status
    new_status = row.status
    if not dry_run and row.status == "published":
        row.status = "funding_in_progress"
        db.session.flush()
        new_status = row.status

    event_bus.emit(
        domain="calendar",
        operation="project_funds_encumbered",
        request_id=str(request_id or out.id),
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "project_ulid": row.project_ulid,
            "funding_demand_ulid": row.ulid,
            "encumbrance_ulid": out.id,
            "fund_key": fund_key,
            "decision_fingerprint": preview.decision_fingerprint,
        },
        changed={"fields": ["status"]} if new_status != old_status else None,
    )

    return ProjectEncumbranceResult(
        funding_demand_ulid=row.ulid,
        project_ulid=row.project_ulid,
        fund_key=fund_key,
        amount_cents=amount_cents,
        encumbrance_ulid=out.id,
        decision_fingerprint=preview.decision_fingerprint,
        status=new_status,
        flags=tuple(out.flags or ()),
    )


def spend_project_funds(
    *,
    encumbrance_ulid: str,
    amount_cents: int,
    expense_kind: str,
    payment_method: str,
    happened_at_utc: str,
    source_ref_ulid: str | None = None,
    payee_entity_ulid: str | None = None,
    memo: str | None = None,
    actor_ulid: str | None,
    actor_rbac_roles: tuple[str, ...] = (),
    actor_domain_roles: tuple[str, ...] = (),
    request_id: str | None,
    dry_run: bool = False,
) -> ProjectSpendResult:
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")
    if not encumbrance_ulid:
        raise ValueError("encumbrance_ulid required")
    if not expense_kind:
        raise ValueError("expense_kind required")
    if not payment_method:
        raise ValueError("payment_method required")
    if not happened_at_utc:
        raise ValueError("happened_at_utc required")

    enc = finance_v2.get_encumbrance(encumbrance_ulid)
    if enc.status != "active":
        raise ValueError("encumbrance must be active")
    if amount_cents > enc.open_cents:
        raise ValueError("expense exceeds open encumbered balance")

    row = _get_demand_or_raise(enc.funding_demand_ulid)
    if row.status not in _SPEND_OK:
        raise ValueError(
            "funding demand must be funding_in_progress, funded, "
            "or executing"
        )
    if not row.spending_class:
        raise ValueError("funding demand spending_class required")

    fund_meta = governance_v2.get_fund_key(enc.fund_key)
    restriction_keys = governance_v2.apply_fund_defaults(
        fund_key=enc.fund_key,
        restriction_keys=(),
    )
    sem = governance_v2.validate_semantic_keys(
        fund_key=enc.fund_key,
        restriction_keys=restriction_keys,
        expense_kind=expense_kind,
        spending_class=row.spending_class,
        demand_eligible_fund_keys=tuple(row.eligible_fund_keys_json or ()),
    )
    if not sem.ok:
        raise ValueError("; ".join(sem.errors) or "invalid semantics")

    preview = governance_v2.preview_funding_decision(
        _build_funding_decision_request(
            row=row,
            op="spend",
            amount_cents=amount_cents,
            funding_demand_ulid=row.ulid,
            project_ulid=row.project_ulid,
            spending_class=row.spending_class,
            expense_kind=expense_kind,
            restriction_keys=restriction_keys,
            demand_eligible_fund_keys=tuple(
                row.eligible_fund_keys_json or ()
            ),
            tag_any=tuple(row.tag_any_json or ()),
            selected_fund_key=enc.fund_key,
            actor_rbac_roles=actor_rbac_roles,
            actor_domain_roles=actor_domain_roles,
        )
    )
    if not preview.allowed:
        raise PermissionError(
            "; ".join(preview.reason_codes) or "spend denied"
        )
    if preview.required_approvals:
        raise PermissionError(
            "spend requires approvals: "
            + ", ".join(preview.required_approvals)
        )

    fund_restriction_type = _derive_restriction_type(
        restriction_keys=restriction_keys,
        archetype=fund_meta.archetype,
    )
    memo_txt = memo or f"expense:{expense_kind}"

    out = finance_v2.post_expense(
        finance_v2.ExpensePostRequestDTO(
            amount_cents=amount_cents,
            happened_at_utc=happened_at_utc,
            fund_key=enc.fund_key,
            fund_label=fund_meta.label,
            fund_restriction_type=fund_restriction_type,
            expense_kind=expense_kind,
            payment_method=payment_method,
            source="calendar",
            source_ref_ulid=source_ref_ulid,
            funding_demand_ulid=row.ulid,
            project_ulid=row.project_ulid,
            payee_entity_ulid=payee_entity_ulid,
            encumbrance_ulid=enc.encumbrance_ulid,
            memo=memo_txt,
            created_by_actor=actor_ulid,
            request_id=request_id,
            dry_run=dry_run,
        )
    )

    old_status = row.status

    new_status = row.status
    if not dry_run and row.status != "executing":
        row.status = "executing"
        db.session.flush()
        new_status = row.status

    event_bus.emit(
        domain="calendar",
        operation="project_funds_spent",
        request_id=str(request_id or out.id),
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "project_ulid": row.project_ulid,
            "funding_demand_ulid": row.ulid,
            "encumbrance_ulid": enc.encumbrance_ulid,
            "journal_ulid": out.id,
            "fund_key": enc.fund_key,
            "decision_fingerprint": preview.decision_fingerprint,
        },
        changed={"fields": ["status"]} if new_status != old_status else None,
    )

    return ProjectSpendResult(
        funding_demand_ulid=row.ulid,
        project_ulid=row.project_ulid,
        encumbrance_ulid=enc.encumbrance_ulid,
        journal_ulid=out.id,
        amount_cents=amount_cents,
        decision_fingerprint=preview.decision_fingerprint,
        status=new_status,
        flags=tuple(out.flags or ()),
    )
