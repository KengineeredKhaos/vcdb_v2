# app/slices/finance/services_commitments.py

from __future__ import annotations

from app.extensions import db
from app.slices.finance.models import Encumbrance, Reserve

from .services_journal import ensure_fund


def reserve_funds(payload: dict, *, dry_run: bool = False) -> dict:
    """
    Off-GL fact: lock money to a demand/project.

    Required:
      funding_demand_ulid, fund_key, amount_cents, source

    Optional:
      project_ulid, source_ref_ulid, memo, fund_label, fund_restriction_type
    """
    fd = payload.get("funding_demand_ulid")
    fund_key = payload.get("fund_key")
    amount = int(payload.get("amount_cents") or 0)
    source = payload.get("source") or "unknown"

    if not fd:
        raise ValueError("funding_demand_ulid required")
    if not fund_key:
        raise ValueError("fund_key required")
    if amount < 0:
        raise ValueError("amount_cents must be >= 0")

    # Ensure fund row exists (cheap convenience)
    fund_label = payload.get("fund_label") or str(fund_key)
    fund_restr = payload.get("fund_restriction_type") or "unrestricted"
    ensure_fund(
        code=str(fund_key), name=str(fund_label), restriction=fund_restr
    )

    if dry_run:
        return {"id": "DRY-RUN", "fund_key": fund_key, "amount_cents": amount}

    r = Reserve(
        funding_demand_ulid=str(fd),
        project_ulid=payload.get("project_ulid"),
        fund_code=str(fund_key),
        amount_cents=amount,
        status="active",
        source=str(source),
        source_ref_ulid=payload.get("source_ref_ulid"),
        memo=payload.get("memo"),
    )
    db.session.add(r)
    db.session.flush()
    return {"id": r.ulid, "fund_key": fund_key, "amount_cents": amount}


def encumber_funds(payload: dict, *, dry_run: bool = False) -> dict:
    """
    Off-GL fact: commit approved spending.

    Required:
      funding_demand_ulid, fund_key, amount_cents, source

    Optional:
      project_ulid, source_ref_ulid, memo, decision_fingerprint
      fund_label, fund_restriction_type
    """
    fd = payload.get("funding_demand_ulid")
    fund_key = payload.get("fund_key")
    amount = int(payload.get("amount_cents") or 0)
    source = payload.get("source") or "unknown"

    if not fd:
        raise ValueError("funding_demand_ulid required")
    if not fund_key:
        raise ValueError("fund_key required")
    if amount < 0:
        raise ValueError("amount_cents must be >= 0")

    fund_label = payload.get("fund_label") or str(fund_key)
    fund_restr = payload.get("fund_restriction_type") or "unrestricted"
    ensure_fund(
        code=str(fund_key), name=str(fund_label), restriction=fund_restr
    )

    if dry_run:
        return {"id": "DRY-RUN", "fund_key": fund_key, "amount_cents": amount}

    e = Encumbrance(
        funding_demand_ulid=str(fd),
        project_ulid=payload.get("project_ulid"),
        fund_code=str(fund_key),
        amount_cents=amount,
        relieved_cents=0,
        status="active",
        decision_fingerprint=payload.get("decision_fingerprint"),
        source=str(source),
        source_ref_ulid=payload.get("source_ref_ulid"),
        memo=payload.get("memo"),
    )
    db.session.add(e)
    db.session.flush()
    return {"id": e.ulid, "fund_key": fund_key, "amount_cents": amount}


def relieve_encumbrance(
    *,
    encumbrance_ulid: str,
    amount_cents: int,
) -> None:
    if amount_cents <= 0:
        return
    e = db.session.get(Encumbrance, encumbrance_ulid)
    if not e:
        raise LookupError(f"unknown encumbrance: {encumbrance_ulid}")

    e.relieved_cents = min(e.amount_cents, e.relieved_cents + amount_cents)
    if e.relieved_cents >= e.amount_cents:
        e.status = "relieved"
    db.session.flush()
