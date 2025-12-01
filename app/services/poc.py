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
    - org_ulid
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

* At most one primary POC is allowed per `(org_ulid, relation="poc", scope)`.
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
        target_ulid: org_ulid
        meta: org/poc linkage details (ULIDs, scope, rank, flags, window).

* `update_poc(...)`
    - Looks up an existing POC link by `(org_ulid, person_entity_ulid)`.
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

from typing import Callable, Iterable, Optional, Type

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.extensions import event_bus
from app.extensions.contracts.governance_v2 import get_poc_policy
from app.extensions.errors import ContractError  # your existing error type
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
