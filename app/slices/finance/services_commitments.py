# app/slices/finance/services_commitments.py

from __future__ import annotations

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.slices.finance.models import Encumbrance, Reserve

from .services_journal import ensure_fund


def reserve_funds(payload: dict, *, dry_run: bool = False) -> dict:
    """
    Off-GL fact: lock money to a demand/project.

    Required:
      funding_demand_ulid, fund_code, amount_cents, source

    Optional:
      project_ulid, source_ref_ulid, memo, fund_label, fund_restriction_type
    """
    fd = payload.get("funding_demand_ulid")
    fund_code = payload.get("fund_code")
    amount = int(payload.get("amount_cents") or 0)
    source = payload.get("source") or "unknown"
    actor_ulid = payload.get("actor_ulid")
    request_id = payload.get("request_id")

    if not fd:
        raise ValueError("funding_demand_ulid required")
    if not fund_code:
        raise ValueError("fund_code required")
    if amount < 0:
        raise ValueError("amount_cents must be >= 0")

    # Ensure fund row exists (cheap convenience)
    fund_label = payload.get("fund_label") or str(fund_code)
    fund_restr = payload.get("fund_restriction_type") or "unrestricted"
    ensure_fund(
        code=str(fund_code), name=str(fund_label), restriction=fund_restr
    )

    if dry_run:
        return {
            "id": "DRY-RUN",
            "fund_code": fund_code,
            "amount_cents": amount,
        }

    r = Reserve(
        funding_demand_ulid=str(fd),
        project_ulid=payload.get("project_ulid"),
        grant_ulid=payload.get("grant_ulid"),
        fund_code=str(fund_code),
        amount_cents=amount,
        status="active",
        source=str(source),
        source_ref_ulid=payload.get("source_ref_ulid"),
        memo=payload.get("memo"),
    )
    db.session.add(r)
    db.session.flush()
    event_bus.emit(
        domain="finance",
        operation="reserve_recorded",
        request_id=str(request_id or r.ulid),
        actor_ulid=actor_ulid,
        target_ulid=r.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "funding_demand_ulid": str(fd),
            "project_ulid": payload.get("project_ulid"),
            "grant_ulid": payload.get("grant_ulid"),
            "fund_code": str(fund_code),
            "amount_cents": amount,
            "source_ref_ulid": payload.get("source_ref_ulid"),
        },
        chain_key="finance.reserve",
    )
    return {"id": r.ulid, "fund_code": fund_code, "amount_cents": amount}


def encumber_funds(payload: dict, *, dry_run: bool = False) -> dict:
    """
    Off-GL fact: commit approved spending.

    Required:
      funding_demand_ulid, fund_code, amount_cents, source

    Optional:
      project_ulid, source_ref_ulid, memo, decision_fingerprint
      fund_label, fund_restriction_type
    """
    fd = payload.get("funding_demand_ulid")
    fund_code = payload.get("fund_code")
    amount = int(payload.get("amount_cents") or 0)
    source = payload.get("source") or "unknown"
    actor_ulid = payload.get("actor_ulid")
    request_id = payload.get("request_id")

    if not fd:
        raise ValueError("funding_demand_ulid required")
    if not fund_code:
        raise ValueError("fund_code required")
    if amount < 0:
        raise ValueError("amount_cents must be >= 0")

    fund_label = payload.get("fund_label") or str(fund_code)
    fund_restr = payload.get("fund_restriction_type") or "unrestricted"
    ensure_fund(
        code=str(fund_code), name=str(fund_label), restriction=fund_restr
    )

    if dry_run:
        return {
            "id": "DRY-RUN",
            "fund_code": fund_code,
            "amount_cents": amount,
        }

    e = Encumbrance(
        funding_demand_ulid=str(fd),
        project_ulid=payload.get("project_ulid"),
        grant_ulid=payload.get("grant_ulid"),
        fund_code=str(fund_code),
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
    event_bus.emit(
        domain="finance",
        operation="encumbrance_recorded",
        request_id=str(request_id or e.ulid),
        actor_ulid=actor_ulid,
        target_ulid=e.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "funding_demand_ulid": str(fd),
            "project_ulid": payload.get("project_ulid"),
            "grant_ulid": payload.get("grant_ulid"),
            "fund_code": str(fund_code),
            "amount_cents": amount,
            "source_ref_ulid": payload.get("source_ref_ulid"),
            "decision_fingerprint": payload.get("decision_fingerprint"),
        },
        chain_key="finance.encumbrance",
    )
    return {"id": e.ulid, "fund_code": fund_code, "amount_cents": amount}


def relieve_encumbrance(
    *,
    encumbrance_ulid: str,
    amount_cents: int,
    actor_ulid: str | None = None,
    request_id: str | None = None,
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
    event_bus.emit(
        domain="finance",
        operation="encumbrance_relieved",
        request_id=str(request_id or e.ulid),
        actor_ulid=actor_ulid,
        target_ulid=e.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "funding_demand_ulid": e.funding_demand_ulid,
            "project_ulid": e.project_ulid,
            "grant_ulid": e.grant_ulid,
            "fund_code": e.fund_code,
            "amount_cents": amount_cents,
        },
        changed={"fields": ["relieved_cents", "status"]},
        chain_key="finance.encumbrance",
    )
