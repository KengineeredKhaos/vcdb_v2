# app/slices/finance/services_ops_float.py

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import or_, select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.request_ctx import ensure_request_id

from .models import Encumbrance, OpsFloat, Reserve

_VALID_ACTIONS = {"allocate", "repay", "forgive"}
_VALID_MODES = {"seed", "backfill", "bridge"}


def _active_rows(stmt):
    return db.session.execute(stmt).scalars().all()


def _open_amount(parent_ulid: str) -> int:
    parent = db.session.get(OpsFloat, parent_ulid)
    if parent is None:
        raise LookupError(f"unknown ops float: {parent_ulid}")
    if parent.action != "allocate":
        raise ValueError("parent ops float must be an allocate row")

    settled = 0
    rows = _active_rows(
        select(OpsFloat).where(
            OpsFloat.parent_ops_float_ulid == parent_ulid,
            OpsFloat.status == "active",
        )
    )
    for row in rows:
        settled += int(row.amount_cents or 0)
    return max(int(parent.amount_cents or 0) - settled, 0)


def _source_available_cents(
    *,
    funding_demand_ulid: str,
    fund_code: str,
) -> int:
    reserve_total = 0
    for row in _active_rows(
        select(Reserve).where(
            Reserve.funding_demand_ulid == funding_demand_ulid,
            Reserve.fund_code == fund_code,
            Reserve.status == "active",
        )
    ):
        reserve_total += int(row.amount_cents or 0)

    enc_open = 0
    for row in _active_rows(
        select(Encumbrance).where(
            Encumbrance.funding_demand_ulid == funding_demand_ulid,
            Encumbrance.fund_code == fund_code,
            Encumbrance.status == "active",
        )
    ):
        enc_open += max(
            int(row.amount_cents or 0) - int(row.relieved_cents or 0),
            0,
        )

    float_out_open = 0
    for row in _active_rows(
        select(OpsFloat).where(
            OpsFloat.source_funding_demand_ulid == funding_demand_ulid,
            OpsFloat.fund_code == fund_code,
            OpsFloat.action == "allocate",
            OpsFloat.status == "active",
        )
    ):
        float_out_open += _open_amount(row.ulid)

    return reserve_total - enc_open - float_out_open


def allocate_ops_float(payload: dict, *, dry_run: bool = False) -> dict:
    source_fd = payload.get("source_funding_demand_ulid")
    dest_fd = payload.get("dest_funding_demand_ulid")
    fund_code = payload.get("fund_code")
    support_mode = payload.get("support_mode")
    amount = int(payload.get("amount_cents") or 0)
    actor_ulid = payload.get("actor_ulid")
    request_id = str(payload.get("request_id") or ensure_request_id())

    if not source_fd:
        raise ValueError("source_funding_demand_ulid required")
    if not dest_fd:
        raise ValueError("dest_funding_demand_ulid required")
    if source_fd == dest_fd:
        raise ValueError("source and destination funding demand must differ")
    if not fund_code:
        raise ValueError("fund_code required")
    if support_mode not in _VALID_MODES:
        raise ValueError("support_mode must be seed|backfill|bridge")
    if amount <= 0:
        raise ValueError("amount_cents must be > 0")

    available = _source_available_cents(
        funding_demand_ulid=str(source_fd),
        fund_code=str(fund_code),
    )
    if amount > available:
        raise ValueError("ops float exceeds source available funds")

    if dry_run:
        return {
            "id": "DRY-RUN",
            "fund_code": str(fund_code),
            "amount_cents": amount,
            "support_mode": str(support_mode),
        }

    row = OpsFloat(
        action="allocate",
        support_mode=str(support_mode),
        source_funding_demand_ulid=str(source_fd),
        source_project_ulid=payload.get("source_project_ulid"),
        dest_funding_demand_ulid=str(dest_fd),
        dest_project_ulid=payload.get("dest_project_ulid"),
        fund_code=str(fund_code),
        amount_cents=amount,
        status="active",
        decision_fingerprint=payload.get("decision_fingerprint"),
        source_ref_ulid=payload.get("source_ref_ulid"),
        memo=payload.get("memo"),
    )
    db.session.add(row)
    db.session.flush()

    event_bus.emit(
        domain="finance",
        operation="ops_float_allocated",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "source_funding_demand_ulid": row.source_funding_demand_ulid,
            "source_project_ulid": row.source_project_ulid,
            "dest_funding_demand_ulid": row.dest_funding_demand_ulid,
            "dest_project_ulid": row.dest_project_ulid,
            "fund_code": row.fund_code,
            "support_mode": row.support_mode,
            "amount_cents": row.amount_cents,
            "decision_fingerprint": row.decision_fingerprint,
        },
        chain_key="finance.ops_float",
    )
    return {
        "id": row.ulid,
        "fund_code": row.fund_code,
        "amount_cents": row.amount_cents,
        "support_mode": row.support_mode,
    }


def repay_ops_float(payload: dict, *, dry_run: bool = False) -> dict:
    parent_ulid = payload.get("parent_ops_float_ulid")
    amount = int(payload.get("amount_cents") or 0)
    actor_ulid = payload.get("actor_ulid")
    request_id = str(payload.get("request_id") or ensure_request_id())

    if not parent_ulid:
        raise ValueError("parent_ops_float_ulid required")
    if amount <= 0:
        raise ValueError("amount_cents must be > 0")

    parent = db.session.get(OpsFloat, str(parent_ulid))
    if parent is None:
        raise LookupError(f"unknown ops float: {parent_ulid}")
    if parent.action != "allocate":
        raise ValueError("repayment parent must be an allocate row")

    open_cents = _open_amount(parent.ulid)
    if amount > open_cents:
        raise ValueError("repayment exceeds open ops float balance")

    if dry_run:
        return {
            "id": "DRY-RUN",
            "fund_code": parent.fund_code,
            "amount_cents": amount,
            "support_mode": parent.support_mode,
        }

    row = OpsFloat(
        action="repay",
        support_mode=parent.support_mode,
        source_funding_demand_ulid=parent.dest_funding_demand_ulid,
        source_project_ulid=parent.dest_project_ulid,
        dest_funding_demand_ulid=parent.source_funding_demand_ulid,
        dest_project_ulid=parent.source_project_ulid,
        fund_code=parent.fund_code,
        amount_cents=amount,
        status="active",
        parent_ops_float_ulid=parent.ulid,
        source_ref_ulid=payload.get("source_ref_ulid"),
        memo=payload.get("memo"),
    )
    db.session.add(row)
    db.session.flush()

    event_bus.emit(
        domain="finance",
        operation="ops_float_repaid",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "parent_ops_float_ulid": parent.ulid,
            "source_funding_demand_ulid": row.source_funding_demand_ulid,
            "dest_funding_demand_ulid": row.dest_funding_demand_ulid,
            "fund_code": row.fund_code,
            "support_mode": row.support_mode,
            "amount_cents": row.amount_cents,
        },
        chain_key="finance.ops_float",
    )
    return {
        "id": row.ulid,
        "fund_code": row.fund_code,
        "amount_cents": row.amount_cents,
        "support_mode": row.support_mode,
    }


def forgive_ops_float(payload: dict, *, dry_run: bool = False) -> dict:
    parent_ulid = payload.get("parent_ops_float_ulid")
    amount = int(payload.get("amount_cents") or 0)
    actor_ulid = payload.get("actor_ulid")
    request_id = str(payload.get("request_id") or ensure_request_id())

    if not parent_ulid:
        raise ValueError("parent_ops_float_ulid required")
    if amount <= 0:
        raise ValueError("amount_cents must be > 0")

    parent = db.session.get(OpsFloat, str(parent_ulid))
    if parent is None:
        raise LookupError(f"unknown ops float: {parent_ulid}")
    if parent.action != "allocate":
        raise ValueError("forgiveness parent must be an allocate row")

    open_cents = _open_amount(parent.ulid)
    if amount > open_cents:
        raise ValueError("forgiveness exceeds open ops float balance")

    if dry_run:
        return {
            "id": "DRY-RUN",
            "fund_code": parent.fund_code,
            "amount_cents": amount,
            "support_mode": parent.support_mode,
        }

    row = OpsFloat(
        action="forgive",
        support_mode=parent.support_mode,
        source_funding_demand_ulid=parent.source_funding_demand_ulid,
        source_project_ulid=parent.source_project_ulid,
        dest_funding_demand_ulid=parent.dest_funding_demand_ulid,
        dest_project_ulid=parent.dest_project_ulid,
        fund_code=parent.fund_code,
        amount_cents=amount,
        status="active",
        parent_ops_float_ulid=parent.ulid,
        source_ref_ulid=payload.get("source_ref_ulid"),
        memo=payload.get("memo"),
    )
    db.session.add(row)
    db.session.flush()

    event_bus.emit(
        domain="finance",
        operation="ops_float_forgiven",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "parent_ops_float_ulid": parent.ulid,
            "source_funding_demand_ulid": row.source_funding_demand_ulid,
            "dest_funding_demand_ulid": row.dest_funding_demand_ulid,
            "fund_code": row.fund_code,
            "support_mode": row.support_mode,
            "amount_cents": row.amount_cents,
        },
        chain_key="finance.ops_float",
    )
    return {
        "id": row.ulid,
        "fund_code": row.fund_code,
        "amount_cents": row.amount_cents,
        "support_mode": row.support_mode,
    }


def get_ops_float_summary(
    funding_demand_ulid: str,
) -> dict[str, object]:
    incoming = defaultdict(int)
    outgoing = defaultdict(int)
    ulids: list[str] = []

    rows = _active_rows(
        select(OpsFloat).where(
            OpsFloat.action == "allocate",
            OpsFloat.status == "active",
            or_(
                OpsFloat.source_funding_demand_ulid == funding_demand_ulid,
                OpsFloat.dest_funding_demand_ulid == funding_demand_ulid,
            ),
        )
    )
    for row in rows:
        open_cents = _open_amount(row.ulid)
        if open_cents <= 0:
            continue
        ulids.append(row.ulid)
        if row.source_funding_demand_ulid == funding_demand_ulid:
            outgoing[str(row.fund_code)] += open_cents
        if row.dest_funding_demand_ulid == funding_demand_ulid:
            incoming[str(row.fund_code)] += open_cents

    return {
        "funding_demand_ulid": funding_demand_ulid,
        "incoming_open_cents": int(sum(incoming.values())),
        "outgoing_open_cents": int(sum(outgoing.values())),
        "incoming_open_by_fund": [
            {"key": key, "amount_cents": int(incoming[key])}
            for key in sorted(incoming.keys())
        ],
        "outgoing_open_by_fund": [
            {"key": key, "amount_cents": int(outgoing[key])}
            for key in sorted(outgoing.keys())
        ],
        "ops_float_ulids": tuple(sorted(ulids)),
    }


def get_ops_float(ops_float_ulid: str) -> dict[str, object]:
    row = db.session.get(OpsFloat, ops_float_ulid)
    if row is None:
        raise LookupError(f"unknown ops float: {ops_float_ulid}")

    open_cents = 0
    if row.action == "allocate" and row.status == "active":
        open_cents = _open_amount(row.ulid)

    return {
        "ops_float_ulid": row.ulid,
        "action": row.action,
        "support_mode": row.support_mode,
        "source_funding_demand_ulid": row.source_funding_demand_ulid,
        "source_project_ulid": row.source_project_ulid,
        "dest_funding_demand_ulid": row.dest_funding_demand_ulid,
        "dest_project_ulid": row.dest_project_ulid,
        "fund_code": row.fund_code,
        "amount_cents": int(row.amount_cents or 0),
        "open_cents": int(open_cents),
        "status": row.status,
        "parent_ops_float_ulid": row.parent_ops_float_ulid,
        "decision_fingerprint": row.decision_fingerprint,
        "source_ref_ulid": row.source_ref_ulid,
    }
