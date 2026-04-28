# app/slices/finance/services_semantic_posting.py

from __future__ import annotations

from sqlalchemy import select

from app.lib.chrono import now_iso8601_ms
from app.extensions import db, event_bus
from app.lib.request_ctx import ensure_request_id

from .models import FinancePostingFact
from .services_commitments import relieve_encumbrance
from .services_journal import ensure_fund, post_journal
from .services_posting_map import (
    select_expense_account_codes,
    select_income_account_codes,
)


def _posting_idempotency_key(
    *,
    request_id: str,
    source: str,
    source_ref_ulid: str | None,
    semantic_key: str,
) -> str:
    """Build the explicit duplicate-posting guard key.

    Canon note for Future Dev:
      This is intentionally stored as a real database column instead of a
      clever multi-column constraint. Finance is a behind-the-curtain slice;
      inspectable, boring data beats DRY cleverness when money facts and
      retry safety are involved.
    """
    source_ref = source_ref_ulid or "~"
    return ":".join((request_id, source, source_ref, semantic_key))


def _facts_match(
    fact: FinancePostingFact,
    *,
    posting_family: str,
    semantic_key: str,
    method_key: str,
    funding_demand_ulid: str,
    project_ulid: str | None,
    fund_code: str,
    amount_cents: int,
    source: str,
    source_ref_ulid: str | None,
) -> bool:
    return (
        fact.posting_family == posting_family
        and fact.semantic_key == semantic_key
        and fact.method_key == method_key
        and fact.funding_demand_ulid == funding_demand_ulid
        and fact.project_ulid == project_ulid
        and fact.fund_code == fund_code
        and int(fact.amount_cents) == int(amount_cents)
        and fact.source == source
        and fact.source_ref_ulid == source_ref_ulid
    )


def _existing_posting_by_idempotency_key(
    idempotency_key: str,
) -> FinancePostingFact | None:
    return db.session.execute(
        select(FinancePostingFact).where(
            FinancePostingFact.idempotency_key == idempotency_key
        )
    ).scalar_one_or_none()


def post_income(payload: dict, *, dry_run: bool = False) -> dict:
    """
    Finance semantic income posting.

    Required:
      amount_cents (>0), happened_at_utc, fund_code, fund_label,
      fund_restriction_type, income_kind, receipt_method, source

    Optional:
      funding_demand_ulid, project_ulid, source_ref_ulid, memo,
      created_by_actor, payer_entity_ulid
    """
    amount = int(payload.get("amount_cents") or 0)
    if amount <= 0:
        raise ValueError("amount_cents must be > 0")

    fund_code = payload.get("fund_code")
    if not fund_code:
        raise ValueError("fund_code required")

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
    request_id = str(payload.get("request_id") or ensure_request_id())

    funding_demand_ulid = payload.get("funding_demand_ulid")
    if not funding_demand_ulid:
        raise ValueError("funding_demand_ulid required")

    fund_label = payload.get("fund_label") or str(fund_code)
    fund_restr = payload.get("fund_restriction_type") or "unrestricted"
    ensure_fund(
        code=str(fund_code),
        name=str(fund_label),
        restriction=fund_restr,
    )

    debit_acct, credit_acct = select_income_account_codes(
        income_kind=str(income_kind),
        receipt_method=str(receipt_method),
    )

    memo = payload.get("memo") or f"income:{income_kind}"
    source_ref_ulid = payload.get("source_ref_ulid")
    created_by_actor = payload.get("created_by_actor")
    idempotency_key = _posting_idempotency_key(
        request_id=request_id,
        source=str(source),
        source_ref_ulid=source_ref_ulid,
        semantic_key=str(income_kind),
    )

    if dry_run:
        return {"id": "DRY-RUN", "amount_cents": amount, "flags": ["dry_run"]}

    existing = _existing_posting_by_idempotency_key(idempotency_key)
    if existing is not None:
        same_fact = _facts_match(
            existing,
            posting_family="income",
            semantic_key=str(income_kind),
            method_key=str(receipt_method),
            funding_demand_ulid=str(funding_demand_ulid),
            project_ulid=payload.get("project_ulid"),
            fund_code=str(fund_code),
            amount_cents=amount,
            source=str(source),
            source_ref_ulid=source_ref_ulid,
        )
        if same_fact:
            return {
                "id": existing.journal_ulid,
                "fund_code": str(fund_code),
                "amount_cents": amount,
                "flags": ["posted", "idempotent"],
            }
        raise ValueError(
            "idempotency_key already used for different income facts"
        )

    lines = [
        {
            "account_code": debit_acct,
            "fund_code": str(fund_code),
            "funding_demand_ulid": str(funding_demand_ulid),
            "project_ulid": payload.get("project_ulid"),
            "grant_ulid": payload.get("grant_ulid"),
            "amount_cents": amount,
            "memo": memo,
        },
        {
            "account_code": credit_acct,
            "fund_code": str(fund_code),
            "funding_demand_ulid": str(funding_demand_ulid),
            "project_ulid": payload.get("project_ulid"),
            "grant_ulid": payload.get("grant_ulid"),
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
        request_id=request_id,
        project_ulid=payload.get("project_ulid"),
        grant_ulid=payload.get("grant_ulid"),
    )

    fact = FinancePostingFact(
        journal_ulid=str(journal_ulid),
        request_id=request_id,
        posting_family="income",
        semantic_key=str(income_kind),
        method_key=str(receipt_method),
        funding_demand_ulid=str(funding_demand_ulid),
        project_ulid=payload.get("project_ulid"),
        fund_code=str(fund_code),
        amount_cents=amount,
        source=str(source),
        source_ref_ulid=source_ref_ulid,
        idempotency_key=idempotency_key,
        happened_at_utc=str(happened_at_utc),
        actor_ulid=created_by_actor,
    )
    db.session.add(fact)
    db.session.flush()

    # Optional extra semantic event (keeps UI/reporting glue easy)
    event_bus.emit(
        domain="finance",
        operation="income_posted",
        request_id=request_id,
        actor_ulid=created_by_actor,
        target_ulid=journal_ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "fund_code": str(fund_code),
            "income_kind": str(income_kind),
            "receipt_method": str(receipt_method),
            "amount_cents": amount,
            "project_ulid": payload.get("project_ulid"),
            "grant_ulid": payload.get("grant_ulid"),
            "funding_demand_ulid": payload.get("funding_demand_ulid"),
            "payer_entity_ulid": payload.get("payer_entity_ulid"),
            "source_ref_ulid": source_ref_ulid,
        },
        chain_key="finance.income",
    )

    return {
        "id": journal_ulid,
        "fund_code": str(fund_code),
        "amount_cents": amount,
        "flags": ["posted"],
    }


def post_expense(payload: dict, *, dry_run: bool = False) -> dict:
    """
    Finance semantic expense posting.

    Required:
      amount_cents (>0), happened_at_utc, fund_code, fund_label,
      fund_restriction_type, expense_kind, payment_method, source

    Optional:
      funding_demand_ulid, project_ulid, source_ref_ulid, memo,
      created_by_actor, payee_entity_ulid, encumbrance_ulid
    """
    amount = int(payload.get("amount_cents") or 0)
    if amount <= 0:
        raise ValueError("amount_cents must be > 0")

    fund_code = payload.get("fund_code")
    if not fund_code:
        raise ValueError("fund_code required")

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
    request_id = str(payload.get("request_id") or ensure_request_id())

    funding_demand_ulid = payload.get("funding_demand_ulid")
    if not funding_demand_ulid:
        raise ValueError("funding_demand_ulid required")

    fund_label = payload.get("fund_label") or str(fund_code)
    fund_restr = payload.get("fund_restriction_type") or "unrestricted"
    ensure_fund(
        code=str(fund_code),
        name=str(fund_label),
        restriction=fund_restr,
    )

    debit_acct, credit_acct = select_expense_account_codes(
        expense_kind=str(expense_kind),
        payment_method=str(payment_method),
    )

    memo = payload.get("memo") or f"expense:{expense_kind}"
    source_ref_ulid = payload.get("source_ref_ulid")
    created_by_actor = payload.get("created_by_actor")
    idempotency_key = _posting_idempotency_key(
        request_id=request_id,
        source=str(source),
        source_ref_ulid=source_ref_ulid,
        semantic_key=str(expense_kind),
    )

    if dry_run:
        return {"id": "DRY-RUN", "amount_cents": amount, "flags": ["dry_run"]}

    existing = _existing_posting_by_idempotency_key(idempotency_key)
    if existing is not None:
        same_fact = _facts_match(
            existing,
            posting_family="expense",
            semantic_key=str(expense_kind),
            method_key=str(payment_method),
            funding_demand_ulid=str(funding_demand_ulid),
            project_ulid=payload.get("project_ulid"),
            fund_code=str(fund_code),
            amount_cents=amount,
            source=str(source),
            source_ref_ulid=source_ref_ulid,
        )
        if same_fact:
            return {
                "id": existing.journal_ulid,
                "fund_code": str(fund_code),
                "amount_cents": amount,
                "flags": ["posted", "idempotent"],
            }
        raise ValueError(
            "idempotency_key already used for different expense facts"
        )

    lines = [
        {
            "account_code": debit_acct,
            "fund_code": str(fund_code),
            "funding_demand_ulid": str(funding_demand_ulid),
            "project_ulid": payload.get("project_ulid"),
            "grant_ulid": payload.get("grant_ulid"),
            "amount_cents": amount,
            "memo": memo,
        },
        {
            "account_code": credit_acct,
            "fund_code": str(fund_code),
            "funding_demand_ulid": str(funding_demand_ulid),
            "project_ulid": payload.get("project_ulid"),
            "grant_ulid": payload.get("grant_ulid"),
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
        request_id=request_id,
        project_ulid=payload.get("project_ulid"),
        grant_ulid=payload.get("grant_ulid"),
    )

    fact = FinancePostingFact(
        journal_ulid=str(journal_ulid),
        request_id=request_id,
        posting_family="expense",
        semantic_key=str(expense_kind),
        method_key=str(payment_method),
        funding_demand_ulid=str(funding_demand_ulid),
        project_ulid=payload.get("project_ulid"),
        fund_code=str(fund_code),
        amount_cents=amount,
        source=str(source),
        source_ref_ulid=source_ref_ulid,
        idempotency_key=idempotency_key,
        happened_at_utc=now_iso8601_ms(),
        actor_ulid=created_by_actor,
    )
    db.session.add(fact)
    db.session.flush()

    enc_ulid = payload.get("encumbrance_ulid")
    if enc_ulid:
        relieve_encumbrance(
            encumbrance_ulid=str(enc_ulid),
            amount_cents=amount,
            actor_ulid=created_by_actor,
            request_id=request_id,
        )

    event_bus.emit(
        domain="finance",
        operation="expense_posted",
        request_id=request_id,
        actor_ulid=created_by_actor,
        target_ulid=journal_ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "fund_code": str(fund_code),
            "expense_kind": str(expense_kind),
            "payment_method": str(payment_method),
            "amount_cents": amount,
            "project_ulid": payload.get("project_ulid"),
            "grant_ulid": payload.get("grant_ulid"),
            "funding_demand_ulid": payload.get("funding_demand_ulid"),
            "payee_entity_ulid": payload.get("payee_entity_ulid"),
            "source_ref_ulid": source_ref_ulid,
            "encumbrance_ulid": enc_ulid,
        },
        chain_key="finance.expense",
    )

    return {
        "id": journal_ulid,
        "fund_code": str(fund_code),
        "amount_cents": amount,
        "flags": ["posted"],
    }
