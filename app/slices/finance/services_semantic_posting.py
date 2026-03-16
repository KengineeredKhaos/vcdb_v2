# app/slices/finance/services_semantic_posting.py

from __future__ import annotations

from app.extensions import event_bus
from app.lib.chrono import now_iso8601_ms

from .services_commitments import relieve_encumbrance
from .services_journal import ensure_fund, post_journal
from .services_posting_map import (
    select_expense_account_codes,
    select_income_account_codes,
)


def post_income(payload: dict, *, dry_run: bool = False) -> dict:
    """
    Finance semantic income posting.

    Required:
      amount_cents (>0), happened_at_utc, fund_key, fund_label,
      fund_restriction_type, income_kind, receipt_method, source

    Optional:
      funding_demand_ulid, project_ulid, source_ref_ulid, memo,
      created_by_actor, payer_entity_ulid
    """
    amount = int(payload.get("amount_cents") or 0)
    if amount <= 0:
        raise ValueError("amount_cents must be > 0")

    fund_key = payload.get("fund_key")
    if not fund_key:
        raise ValueError("fund_key required")

    happened_at_utc = payload.get("happened_at_utc")
    if not happened_at_utc:
        raise ValueError("happened_at_utc required")

    income_kind = payload.get("income_kind")
    receipt_method = payload.get("receipt_method")
    if not income_kind:
        raise ValueError("income_kind required")
    if not receipt_method:
        raise ValueError("receipt_method required")

    source = payload.get("source") or "income"
    funding_demand_ulid = payload.get("funding_demand_ulid")
    if not funding_demand_ulid:
        raise ValueError("funding_demand_ulid required")

    fund_label = payload.get("fund_label") or str(fund_key)
    fund_restr = payload.get("fund_restriction_type") or "unrestricted"
    ensure_fund(
        code=str(fund_key), name=str(fund_label), restriction=fund_restr
    )

    debit_acct, credit_acct = select_income_account_codes(
        income_kind=str(income_kind),
        receipt_method=str(receipt_method),
    )

    memo = payload.get("memo") or f"income:{income_kind}"
    source_ref_ulid = payload.get("source_ref_ulid")
    created_by_actor = payload.get("created_by_actor")

    if dry_run:
        return {"id": "DRY-RUN", "amount_cents": amount, "flags": ["dry_run"]}

    lines = [
        {
            "account_code": debit_acct,
            "fund_code": str(fund_key),
            "funding_demand_ulid": str(funding_demand_ulid),
            "project_ulid": payload.get("project_ulid"),
            "amount_cents": amount,
            "memo": memo,
        },
        {
            "account_code": credit_acct,
            "fund_code": str(fund_key),
            "funding_demand_ulid": str(funding_demand_ulid),
            "project_ulid": payload.get("project_ulid"),
            "amount_cents": -amount,
            "memo": memo,
        },
    ]

    journal_ulid = post_journal(
        source=str(source),
        external_ref_ulid=source_ref_ulid,
        happened_at_utc=str(happened_at_utc),
        currency="USD",
        memo=memo,
        lines=lines,
        created_by_actor=created_by_actor,
    )

    # Optional extra semantic event (keeps UI/reporting glue easy)
    event_bus.emit(
        domain="finance",
        operation="income_posted",
        request_id=journal_ulid,
        actor_ulid=created_by_actor,
        target_ulid=journal_ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "fund_key": str(fund_key),
            "income_kind": str(income_kind),
            "receipt_method": str(receipt_method),
            "amount_cents": amount,
            "project_ulid": payload.get("project_ulid"),
            "funding_demand_ulid": payload.get("funding_demand_ulid"),
            "payer_entity_ulid": payload.get("payer_entity_ulid"),
            "source_ref_ulid": source_ref_ulid,
        },
        chain_key="finance.income",
    )

    return {
        "id": journal_ulid,
        "amount_cents": amount,
        "flags": ["posted"],
    }


def post_expense(payload: dict, *, dry_run: bool = False) -> dict:
    """
    Finance semantic expense posting.

    Required:
      amount_cents (>0), happened_at_utc, fund_key, fund_label,
      fund_restriction_type, expense_kind, payment_method, source

    Optional:
      funding_demand_ulid, project_ulid, source_ref_ulid, memo,
      created_by_actor, payee_entity_ulid, encumbrance_ulid
    """
    amount = int(payload.get("amount_cents") or 0)
    if amount <= 0:
        raise ValueError("amount_cents must be > 0")

    fund_key = payload.get("fund_key")
    if not fund_key:
        raise ValueError("fund_key required")

    happened_at_utc = payload.get("happened_at_utc")
    if not happened_at_utc:
        raise ValueError("happened_at_utc required")

    expense_kind = payload.get("expense_kind")
    payment_method = payload.get("payment_method")
    if not expense_kind:
        raise ValueError("expense_kind required")
    if not payment_method:
        raise ValueError("payment_method required")


    source = payload.get("source") or "expense"
    funding_demand_ulid = payload.get("funding_demand_ulid")
    if not funding_demand_ulid:
        raise ValueError("funding_demand_ulid required")

    fund_label = payload.get("fund_label") or str(fund_key)
    fund_restr = payload.get("fund_restriction_type") or "unrestricted"
    ensure_fund(
        code=str(fund_key), name=str(fund_label), restriction=fund_restr
    )

    debit_acct, credit_acct = select_expense_account_codes(
        expense_kind=str(expense_kind),
        payment_method=str(payment_method),
    )

    memo = payload.get("memo") or f"expense:{expense_kind}"
    source_ref_ulid = payload.get("source_ref_ulid")
    created_by_actor = payload.get("created_by_actor")

    if dry_run:
        return {"id": "DRY-RUN", "amount_cents": amount, "flags": ["dry_run"]}

    lines = [
        {
            "account_code": debit_acct,
            "fund_code": str(fund_key),
            "funding_demand_ulid": str(funding_demand_ulid),
            "project_ulid": payload.get("project_ulid"),
            "amount_cents": amount,
            "memo": memo,
        },
        {
            "account_code": credit_acct,
            "fund_code": str(fund_key),
            "funding_demand_ulid": str(funding_demand_ulid),
            "project_ulid": payload.get("project_ulid"),
            "amount_cents": -amount,
            "memo": memo,
        },
    ]

    journal_ulid = post_journal(
        source=str(source),
        external_ref_ulid=source_ref_ulid,
        happened_at_utc=str(happened_at_utc),
        currency="USD",
        memo=memo,
        lines=lines,
        created_by_actor=created_by_actor,
    )

    enc_ulid = payload.get("encumbrance_ulid")
    if enc_ulid:
        relieve_encumbrance(
            encumbrance_ulid=str(enc_ulid), amount_cents=amount
        )

    event_bus.emit(
        domain="finance",
        operation="expense_posted",
        request_id=journal_ulid,
        actor_ulid=created_by_actor,
        target_ulid=journal_ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "fund_key": str(fund_key),
            "expense_kind": str(expense_kind),
            "payment_method": str(payment_method),
            "amount_cents": amount,
            "project_ulid": payload.get("project_ulid"),
            "funding_demand_ulid": payload.get("funding_demand_ulid"),
            "payee_entity_ulid": payload.get("payee_entity_ulid"),
            "source_ref_ulid": source_ref_ulid,
            "encumbrance_ulid": enc_ulid,
        },
        chain_key="finance.expense",
    )

    return {
        "id": journal_ulid,
        "amount_cents": amount,
        "flags": ["posted"],
    }
