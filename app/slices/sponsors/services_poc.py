# app/slices/sponsors/services_poc.py

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.extensions import event_bus
from app.extensions.contracts.governance_v2 import get_poc_policy
from app.extensions.errors import ContractError
from app.lib.chrono import now_iso8601_ms

POC_RELATION = "poc"


@dataclass(frozen=True)
class POCSpec:
    owner_col: str
    person_col: str = "person_entity_ulid"
    relation_col: str = "relation"
    scope_col: str = "scope"
    rank_col: str = "rank"
    primary_col: str = "is_primary"
    active_col: str = "active"
    ulid_col: str = "ulid"
    org_role_col: str = "org_role"
    valid_from_col: str = "valid_from_utc"
    valid_to_col: str = "valid_to_utc"


def _c(POCModel: type, name: str):
    return getattr(POCModel, name)


def _normalize_scope_rank(*, scope: str | None, rank: int | None):
    policy = get_poc_policy()
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

    return sc, rk


def _flip_existing_primary(
    session: Session,
    POCModel: type,
    spec: POCSpec,
    owner_ulid: str,
    scope: str,
) -> None:
    (
        session.query(POCModel)
        .filter(
            and_(
                _c(POCModel, spec.owner_col) == owner_ulid,
                _c(POCModel, spec.relation_col) == POC_RELATION,
                _c(POCModel, spec.scope_col) == scope,
                _c(POCModel, spec.active_col) == True,  # noqa: E712
                _c(POCModel, spec.primary_col) == True,  # noqa: E712
            )
        )
        .update(
            {_c(POCModel, spec.primary_col): False}, synchronize_session=False
        )
    )


def link_poc(
    *,
    session: Session,
    POCModel: type,
    spec: POCSpec,
    domain: str,
    owner_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int = 0,
    is_primary: bool = False,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    if not request_id or not str(request_id).strip():
        raise ContractError(
            code="bad_request",
            where="poc.link_poc",
            message="request_id required",
            http_status=400,
        )

    sc, rk = _normalize_scope_rank(scope=scope, rank=rank)
    if is_primary:
        _flip_existing_primary(session, POCModel, spec, owner_ulid, sc)

    now = now_iso8601_ms()
    row = POCModel(
        **{
            spec.owner_col: owner_ulid,
            spec.person_col: person_entity_ulid,
            spec.relation_col: POC_RELATION,
            spec.scope_col: sc,
            spec.rank_col: rk,
            spec.primary_col: bool(is_primary),
            spec.active_col: True,
            spec.org_role_col: (org_role or None),
            spec.valid_from_col: (window or {}).get("from"),
            spec.valid_to_col: (window or {}).get("to"),
            "created_at_utc": now,
            "updated_at_utc": now,
        }
    )
    session.add(row)
    session.flush()

    event_bus.emit(
        domain="sponsors",
        operation="poc_linked",
        target_ulid=owner_ulid,
        actor_ulid=actor_ulid,
        request_id=request_id,
        happened_at_utc=now,
        meta={
            "person_entity_ulid": person_entity_ulid,
            "relation": POC_RELATION,
            "scope": sc,
            "rank": rk,
            "is_primary": bool(is_primary),
            "org_role": getattr(row, spec.org_role_col),
            "valid_from_utc": getattr(row, spec.valid_from_col),
            "valid_to_utc": getattr(row, spec.valid_to_col),
        },
    )
    return row


def update_poc(
    *,
    session: Session,
    POCModel: type,
    spec: POCSpec,
    domain: str,
    owner_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int | None = None,
    is_primary: bool | None = None,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    if not request_id or not str(request_id).strip():
        raise ContractError(
            code="bad_request",
            where="poc.update_poc",
            message="request_id required",
            http_status=400,
        )

    q = session.query(POCModel).filter(
        and_(
            _c(POCModel, spec.owner_col) == owner_ulid,
            _c(POCModel, spec.person_col) == person_entity_ulid,
            _c(POCModel, spec.relation_col) == POC_RELATION,
            _c(POCModel, spec.active_col) == True,  # noqa: E712
        )
    )
    if scope:
        q = q.filter(_c(POCModel, spec.scope_col) == scope)

    rows = q.all()
    if not rows:
        raise ContractError(
            code="not_found",
            where="poc.update_poc",
            message="POC link not found",
            http_status=404,
        )
    if len(rows) > 1 and not scope:
        scopes = sorted({getattr(r, spec.scope_col) for r in rows})
        raise ContractError(
            code="conflict",
            where="poc.update_poc",
            message="multiple POC links exist; specify scope",
            http_status=409,
            data={"available_scopes": scopes},
        )

    row = rows[0]

    new_scope = getattr(row, spec.scope_col) if scope is None else scope
    new_rank = getattr(row, spec.rank_col) if rank is None else rank
    sc, rk = _normalize_scope_rank(scope=new_scope, rank=new_rank)

    if is_primary is not None:
        if bool(is_primary):
            _flip_existing_primary(session, POCModel, spec, owner_ulid, sc)
        setattr(row, spec.primary_col, bool(is_primary))

    setattr(row, spec.scope_col, sc)
    setattr(row, spec.rank_col, rk)

    if org_role is not None:
        setattr(row, spec.org_role_col, org_role)

    if window is not None:
        setattr(row, spec.valid_from_col, (window or {}).get("from"))
        setattr(row, spec.valid_to_col, (window or {}).get("to"))

    now = now_iso8601_ms()
    row.updated_at_utc = now

    event_bus.emit(
        domain="sponsors",
        operation="poc_updated",
        target_ulid=owner_ulid,
        actor_ulid=actor_ulid,
        request_id=request_id,
        happened_at_utc=now,
        meta={
            "person_entity_ulid": person_entity_ulid,
            "relation": POC_RELATION,
            "scope": getattr(row, spec.scope_col),
            "rank": getattr(row, spec.rank_col),
            "is_primary": getattr(row, spec.primary_col),
            "org_role": getattr(row, spec.org_role_col),
            "valid_from_utc": getattr(row, spec.valid_from_col),
            "valid_to_utc": getattr(row, spec.valid_to_col),
        },
    )
    return row


def unlink_poc(
    *,
    session: Session,
    POCModel: type,
    spec: POCSpec,
    domain: str,
    owner_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    if not request_id or not str(request_id).strip():
        raise ContractError(
            code="bad_request",
            where="poc.unlink_poc",
            message="request_id required",
            http_status=400,
        )

    q = session.query(POCModel).filter(
        and_(
            _c(POCModel, spec.owner_col) == owner_ulid,
            _c(POCModel, spec.person_col) == person_entity_ulid,
            _c(POCModel, spec.relation_col) == POC_RELATION,
            _c(POCModel, spec.active_col) == True,  # noqa: E712
        )
    )
    if scope:
        q = q.filter(_c(POCModel, spec.scope_col) == scope)

    rows = q.all()
    if not rows:
        return

    if len(rows) > 1 and not scope:
        scopes = sorted({getattr(r, spec.scope_col) for r in rows})
        raise ContractError(
            code="conflict",
            where="poc.unlink_poc",
            message="multiple POC links exist; specify scope",
            http_status=409,
            data={"available_scopes": scopes},
        )

    row = rows[0]
    setattr(row, spec.active_col, False)

    now = now_iso8601_ms()
    row.updated_at_utc = now

    event_bus.emit(
        domain="sponsors",
        operation="poc_unlinked",
        target_ulid=owner_ulid,
        actor_ulid=actor_ulid,
        request_id=request_id,
        happened_at_utc=now,
        meta={
            "person_entity_ulid": person_entity_ulid,
            "relation": POC_RELATION,
            "scope": getattr(row, spec.scope_col),
        },
    )
    return row


def list_pocs(
    *,
    session: Session,
    POCModel: type,
    spec: POCSpec,
    owner_ulid: str,
) -> list[dict]:
    rows: Iterable = (
        session.query(POCModel)
        .filter(
            and_(
                _c(POCModel, spec.owner_col) == owner_ulid,
                _c(POCModel, spec.relation_col) == POC_RELATION,
            )
        )
        .order_by(
            _c(POCModel, spec.active_col).desc(),
            _c(POCModel, spec.scope_col).asc(),
            _c(POCModel, spec.rank_col).asc(),
            _c(POCModel, spec.ulid_col).asc(),
        )
        .all()
    )

    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "owner_ulid": owner_ulid,
                "person_entity_ulid": getattr(r, spec.person_col),
                "relation": getattr(r, spec.relation_col),
                "scope": getattr(r, spec.scope_col),
                "rank": getattr(r, spec.rank_col),
                "is_primary": getattr(r, spec.primary_col),
                "org_role": getattr(r, spec.org_role_col),
                "valid_from_utc": getattr(r, spec.valid_from_col),
                "valid_to_utc": getattr(r, spec.valid_to_col),
                "active": getattr(r, spec.active_col),
            }
        )
    return out


__all__ = ["link_poc", "update_poc", "unlink_poc", "list_pocs", "POCSpec"]
