# app/services/poc.py
from __future__ import annotations

from typing import Callable, Iterable, Optional, Type

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.errors import ContractError  # your existing error type
from app.extensions import event_bus
from app.extensions.contracts.governance_v2 import get_poc_policy
from app.lib.chrono import now_iso8601_ms

# The slice model contract expected by this module:
# - class POCModel with columns:
#   ulid (PK), org_ulid, person_entity_ulid, relation, scope, rank, is_primary,
#   org_role, valid_from_utc, valid_to_utc, active, created_at_utc, updated_at_utc
#
# The slice must pass a SQLAlchemy Session, the model class, and constants below.

POC_RELATION = "poc"


def _normalize_scope_rank(
    *, scope: Optional[str], rank: Optional[int]
) -> tuple[str, int, dict]:
    policy = get_poc_policy()  # {poc_scopes, default_scope, max_rank}
    scopes = policy["poc_scopes"]
    default_scope = policy["default_scope"]
    max_rank = int(policy["max_rank"])

    sc = scope or default_scope
    if sc not in scopes:
        raise ContractError(
            code="policy_invalid",
            where="poc._normalize_scope_rank",
            message=f"invalid scope '{sc}'",
            http_status=400,
            data={"allowed_scopes": scopes},
        )

    rk = 0 if rank is None else int(rank)
    if not (0 <= rk <= max_rank):
        raise ContractError(
            code="policy_invalid",
            where="poc._normalize_scope_rank",
            message=f"rank must be within 0..{max_rank}",
            http_status=400,
            data={"max_rank": max_rank},
        )
    return sc, rk, policy


def _flip_existing_primary(
    sess: Session, POCModel: Type, org_ulid: str, scope: str
):
    # at most one primary per (org, relation='poc', scope)
    sess.query(POCModel).filter(
        and_(
            POCModel.org_ulid == org_ulid,
            POCModel.relation == POC_RELATION,
            POCModel.scope == scope,
            POCModel.is_primary == True,  # noqa: E712
        )
    ).update({"is_primary": False}, synchronize_session=False)


def link_poc(
    sess: Session,
    *,
    POCModel: Type,
    domain: str,  # "resources" | "sponsors"
    org_ulid: str,
    person_entity_ulid: str,
    scope: Optional[str] = None,
    rank: int = 0,
    is_primary: bool = False,
    window: Optional[dict] = None,  # {"from": isoZ|None, "to": isoZ|None}
    org_role: Optional[str] = None,
    actor_ulid: Optional[str] = None,
    request_id: str,
):
    if not request_id or not str(request_id).strip():
        raise ContractError(
            code="bad_request",
            where="poc.link_poc",
            message="request_id required",
            http_status=400,
        )

    sc, rk, _ = _normalize_scope_rank(scope=scope, rank=rank)
    if is_primary:
        _flip_existing_primary(sess, POCModel, org_ulid, sc)

    now = now_iso8601_ms()
    row = POCModel(
        org_ulid=org_ulid,
        person_entity_ulid=person_entity_ulid,
        relation=POC_RELATION,
        scope=sc,
        rank=rk,
        is_primary=bool(is_primary),
        active=True,
        org_role=(org_role or None),
        valid_from_utc=(window or {}).get("from"),
        valid_to_utc=(window or {}).get("to"),
        created_at_utc=now,
        updated_at_utc=now,
    )
    sess.add(row)
    sess.flush()  # ensure ULID is available if generated in-model

    event_bus.emit(
        domain=domain,
        operation="poc.linked",
        target_ulid=org_ulid,
        actor_ulid=actor_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        meta={
            "person_entity_ulid": person_entity_ulid,
            "relation": POC_RELATION,
            "scope": sc,
            "rank": rk,
            "is_primary": bool(is_primary),
            "org_role": row.org_role,
            "valid_from_utc": row.valid_from_utc,
            "valid_to_utc": row.valid_to_utc,
        },
    )
    return row


def update_poc(
    sess: Session,
    *,
    POCModel: Type,
    domain: str,
    org_ulid: str,
    person_entity_ulid: str,
    scope: Optional[str] = None,
    rank: Optional[int] = None,
    is_primary: Optional[bool] = None,
    window: Optional[dict] = None,
    org_role: Optional[str] = None,
    actor_ulid: Optional[str] = None,
    request_id: str,
):
    if not request_id or not str(request_id).strip():
        raise ContractError(
            code="bad_request",
            where="poc.update_poc",
            message="request_id required",
            http_status=400,
        )

    q = sess.query(POCModel).filter(
        and_(
            POCModel.org_ulid == org_ulid,
            POCModel.person_entity_ulid == person_entity_ulid,
            POCModel.relation == POC_RELATION,
        )
    )
    row = q.one_or_none()
    if not row:
        raise ContractError(
            code="not_found",
            where="poc.update_poc",
            message="POC link not found",
            http_status=404,
        )

    # propose new scope/rank
    new_scope = row.scope if scope is None else scope
    new_rank = row.rank if rank is None else rank
    sc, rk, _ = _normalize_scope_rank(scope=new_scope, rank=new_rank)

    if is_primary is not None:
        if is_primary:
            _flip_existing_primary(sess, POCModel, org_ulid, sc)
        row.is_primary = bool(is_primary)

    row.scope = sc
    row.rank = rk
    if org_role is not None:
        row.org_role = org_role
    if window is not None:
        row.valid_from_utc = (window or {}).get("from")
        row.valid_to_utc = (window or {}).get("to")
    row.updated_at_utc = now_iso8601_ms()

    event_bus.emit(
        domain=domain,
        operation="poc.updated",
        target_ulid=org_ulid,
        actor_ulid=actor_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        meta={
            "person_entity_ulid": person_entity_ulid,
            "relation": POC_RELATION,
            "scope": row.scope,
            "rank": row.rank,
            "is_primary": row.is_primary,
            "org_role": row.org_role,
            "valid_from_utc": row.valid_from_utc,
            "valid_to_utc": row.valid_to_utc,
        },
    )
    return row


def unlink_poc(
    sess: Session,
    *,
    POCModel: Type,
    domain: str,
    org_ulid: str,
    person_entity_ulid: str,
    scope: Optional[str] = None,  # if provided, constrain to that scope
    actor_ulid: Optional[str] = None,
    request_id: str,
):
    if not request_id or not str(request_id).strip():
        raise ContractError(
            code="bad_request",
            where="poc.unlink_poc",
            message="request_id required",
            http_status=400,
        )

    q = sess.query(POCModel).filter(
        and_(
            POCModel.org_ulid == org_ulid,
            POCModel.person_entity_ulid == person_entity_ulid,
            POCModel.relation == POC_RELATION,
        )
    )
    if scope:
        q = q.filter(POCModel.scope == scope)

    row = q.one_or_none()
    if not row:
        return  # idempotent

    row.active = False
    row.updated_at_utc = now_iso8601_ms()

    event_bus.emit(
        domain=domain,
        operation="poc.unlinked",
        target_ulid=org_ulid,
        actor_ulid=actor_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        meta={
            "person_entity_ulid": person_entity_ulid,
            "relation": POC_RELATION,
            "scope": row.scope,
        },
    )


def list_pocs(sess: Session, *, POCModel: Type, org_ulid: str) -> list[dict]:
    rows: Iterable = (
        sess.query(POCModel)
        .filter(
            POCModel.org_ulid == org_ulid,
            POCModel.relation == POC_RELATION,
        )
        .order_by(
            POCModel.active.desc(),
            POCModel.scope.asc(),
            POCModel.rank.asc(),
            POCModel.ulid.asc(),
        )
        .all()
    )
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "org_ulid": r.org_ulid,
                "person_entity_ulid": r.person_entity_ulid,
                "relation": r.relation,
                "scope": r.scope,
                "rank": r.rank,
                "is_primary": r.is_primary,
                "org_role": r.org_role,
                "valid_from_utc": r.valid_from_utc,
                "valid_to_utc": r.valid_to_utc,
                "active": r.active,
            }
        )
    return out
