# app/services/poc.py

"""
Shared POC (Point-of-Contact) link helpers.

This module is a small, slice-agnostic service for managing the relationship
between an organization and its point-of-contact people. It is intended to be
reused by multiple slices (e.g. Resources, Sponsors) rather than each slice
reinventing its own POC tables and logic. :contentReference[oaicite:0]{index=0}

Core ideas
----------
* The POC link itself lives in a slice-owned SQLAlchemy model ("POCModel")
  with columns:
    - ulid (PK)
    - owner_ulid
    - person_entity_ulid
    - relation (fixed to "poc" here)
    - scope (policy-defined string, e.g. "general", "whk", etc.)
    - rank (0..max_rank within a scope)
    - is_primary (bool)
    - org_role (free-text role label)
    - valid_from_utc / valid_to_utc (optional window)
    - active (soft-delete flag)
    - created_at_utc / updated_at_utc
  The slice passes this model class and a Session into the helper functions.

* All scope/rank semantics come from the Governance POC policy via
  `get_poc_policy()`. Policy defines:
    - allowed `poc_scopes`
    - `default_scope`
    - `max_rank`
  `_normalize_scope_rank()` applies those rules and raises `ContractError`
  (`code="policy_invalid"`) if a scope or rank is out of bounds.

* At most one primary POC is allowed per `(owner_ulid, relation="poc", scope)`.
  When `is_primary=True` is requested, `_flip_existing_primary()` clears any
  existing primary for that org/scope before inserting or updating the row.

What the helpers do
-------------------
* `link_poc(...)`
    - Validates `request_id` and scope/rank against policy.
    - Optionally flips existing primary for the same org/scope.
    - Inserts a new POC row and flushes to obtain its ULID.
    - Emits a PII-free ledger event via `event_bus.emit` with:
        domain   : caller-supplied slice name (e.g. "resources", "sponsors")
        operation: "poc.linked"
        target_ulid: owner_ulid
        meta: org/poc linkage details (ULIDs, scope, rank, flags, window).

* `update_poc(...)`
    - Looks up an existing POC link by `(owner_ulid, person_entity_ulid)`.
    - Applies optional changes to scope, rank, primary flag, window, org_role.
    - Enforces the single-primary-per-scope rule when `is_primary=True`.
    - Emits "poc.updated" with the new linkage metadata (no PII).

* `unlink_poc(...)`
    - Idempotently marks a POC link inactive (soft delete).
    - Emits "poc.unlinked" with org + person ULIDs and scope.
    - Returns quietly if no matching row is found.

* `list_pocs(...)`
    - Returns a list of simple dicts describing all POC links for an org,
      ordered by active desc, scope asc, rank asc, ulid asc.
    - The result is suitable for contracts/UIs that will join to Entity to
      display human-friendly names and contact details.

Error model & PII boundary
--------------------------
All helpers raise `ContractError` for caller-visible failures (bad request,
policy violation, not found). The ledger events are ULID-only and never
include names, phone numbers, email addresses, or other PII; those remain
in the Entity slice. Callers are expected to use this module to manage POC
links and then resolve the related entity ULIDs through the Entity contracts
for display.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.extensions import event_bus
from app.extensions.contracts.governance_v2 import get_poc_policy
from app.extensions.errors import ContractError  # your existing error type
from app.lib.chrono import now_iso8601_ms

# The slice model contract expected by this module:
# - class POCModel with columns:
#   ulid (PK), owner_ulid, person_entity_ulid, relation, scope, rank, is_primary,
#   org_role, valid_from_utc, valid_to_utc, active, created_at_utc, updated_at_utc
#
# The slice must pass a SQLAlchemy Session, the model class, and constants below.

POC_RELATION = "poc"


@dataclass(frozen=True)
class POCSpec:
    # which column names exist on the slice POC model
    owner_col: str  # "sponsor_entity_ulid" or "resource_entity_ulid"
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
    return sc, rk


def _flip_existing_primary(sess, POCModel, spec, owner_ulid, scope):
    sess.query(POCModel).filter(
        and_(
            _c(POCModel, spec.owner_col) == owner_ulid,
            _c(POCModel, spec.relation_col) == POC_RELATION,
            _c(POCModel, spec.scope_col) == scope,
            _c(POCModel, spec.active_col) == True,  # noqa: E712
            _c(POCModel, spec.primary_col) == True,  # noqa: E712
        )
    ).update(
        {_c(POCModel, spec.primary_col): False},
        synchronize_session=False,
    )


def link_poc(
    sess: Session,
    *,
    POCModel: type,
    spec: POCSpec,
    domain: str,
    owner_ulid: str,  # sponsor_ulid or resource_ulid
    person_entity_ulid: str,  # entity_entity.ulid
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
        _flip_existing_primary(sess, POCModel, spec, owner_ulid, sc)

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
    sess.add(row)
    sess.flush()

    # Signal chain: target is the slice aggregate you mutated
    event_bus.emit(
        domain=domain,
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
    sess: Session,
    *,
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

    # Find target row (scope optional, but must be unambiguous if omitted)
    q = sess.query(POCModel).filter(
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
            message="multiple POC links exist for this person; specify scope",
            http_status=409,
            data={
                "owner_ulid": owner_ulid,
                "person_entity_ulid": person_entity_ulid,
                "available_scopes": scopes,
            },
        )

    row = rows[0]

    # propose new scope/rank
    new_scope = getattr(row, spec.scope_col) if scope is None else scope
    new_rank = getattr(row, spec.rank_col) if rank is None else rank
    sc, rk = _normalize_scope_rank(scope=new_scope, rank=new_rank)

    if is_primary is not None:
        if bool(is_primary):
            _flip_existing_primary(sess, POCModel, spec, owner_ulid, sc)
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
        domain=domain,
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
    sess: Session,
    *,
    POCModel: type,
    spec: POCSpec,
    domain: str,
    owner_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,  # if provided, constrain to that scope
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

    q = sess.query(POCModel).filter(
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
        return  # idempotent

    if len(rows) > 1 and not scope:
        scopes = sorted({getattr(r, spec.scope_col) for r in rows})
        raise ContractError(
            code="conflict",
            where="poc.unlink_poc",
            message="multiple POC links exist for this person; specify scope",
            http_status=409,
            data={
                "owner_ulid": owner_ulid,
                "person_entity_ulid": person_entity_ulid,
                "available_scopes": scopes,
            },
        )

    row = rows[0]

    # --- MISSING BLOCK (this is what your paste lost) ---
    setattr(row, spec.active_col, False)
    now = now_iso8601_ms()
    row.updated_at_utc = now

    event_bus.emit(
        domain=domain,
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
    sess: Session,
    *,
    POCModel: type,
    spec: POCSpec,
    owner_ulid: str,
) -> list[dict]:
    rows: Iterable = (
        sess.query(POCModel)
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
