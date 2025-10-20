# app/slices/governance/services.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from jsonschema import Draft202012Validator, ValidationError
from sqlalchemy import asc, func, select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.lib.jsonutil import stable_dumps, stable_loads  # from your lib.zip

from .models import CanonicalState, Policy, RoleCode, ServiceClassification


class PolicyNotFoundError(ValueError):
    pass


class PolicyValidationError(ValueError):
    pass


def list_states() -> list[dict]:
    rows = (
        db.session.query(CanonicalState)
        .filter_by(is_active=True)
        .order_by(asc(CanonicalState.code))
        .all()
    )
    return [{"code": r.code, "name": r.name} for r in rows]


def list_service_classifications() -> list[dict]:
    rows = (
        db.session.query(ServiceClassification)
        .filter_by(is_active=True)
        .order_by(
            asc(ServiceClassification.sort), asc(ServiceClassification.code)
        )
        .all()
    )
    return [{"code": r.code, "label": r.label, "sort": r.sort} for r in rows]


def list_domain_roles() -> list[dict]:
    rows = (
        db.session.query(RoleCode)
        .filter_by(is_active=True)
        .order_by(asc(RoleCode.code))
        .all()
    )
    return [{"code": r.code, "description": r.description} for r in rows]


# -----------------
# Internal Services
# (contract v1)
# -----------------


def svc_list_states_rows() -> List[CanonicalState]:
    return (
        db.session.query(CanonicalState)
        .filter(CanonicalState.is_active.is_(True))
        .order_by(asc(CanonicalState.code))
        .all()
    )


def svc_list_domain_roles_rows() -> List[RoleCode]:
    return (
        db.session.query(RoleCode)
        .filter(RoleCode.is_active.is_(True))
        .order_by(asc(RoleCode.code))
        .all()
    )


def svc_get_policy_value(namespace: str, key: str) -> Optional[dict]:
    row = (
        db.session.query(Policy)
        .filter(
            Policy.namespace == namespace,
            Policy.key == key,
            Policy.is_active.is_(True),
        )
        .order_by(Policy.version.desc())
        .first()
    )
    return stable_loads(row.value_json) if row else None


# ---- Registry (schema + defaults) ------------------------------------------
# Keep each value as an OBJECT with a single array field so you can evolve later.

ROLES_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["roles"],
    "properties": {
        "roles": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["customer", "resource", "sponsor", "governor"],
            },
            "minItems": 1,
            "uniqueItems": True,
        }
    },
}
ROLES_DEFAULT = {"roles": ["customer", "resource", "sponsor", "governor"]}

POLICY_REGISTRY: Dict[str, tuple[Dict[str, Any], Dict[str, Any]]] = {
    "governance.roles": (ROLES_SCHEMA, ROLES_DEFAULT),
    # add more families here, e.g. "finance.chart_of_accounts", etc.
}

_VALIDATORS: dict[str, Draft202012Validator] = {
    key: Draft202012Validator(schema)
    for key, (schema, _default) in POLICY_REGISTRY.items()
}


def _normalize_value(key: str, value: Dict[str, Any]) -> Dict[str, Any]:
    # Trim/lower/dedupe the single array field
    schema, _ = POLICY_REGISTRY[key]
    (field_name,) = schema["properties"].keys()
    arr = value.get(field_name, [])
    seen: set[str] = set()
    out: list[str] = []
    for x in arr:
        if isinstance(x, str):
            s = x.strip().lower()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        else:
            raise PolicyValidationError("entries must be strings")
    return {field_name: out}


# -----------------
# Public API
# -----------------


def list_policy_keys() -> list[str]:
    # stable ordering helps tests and UX
    return sorted(POLICY_REGISTRY.keys())


def get_policy(namespace: str, key: str) -> tuple[Dict[str, Any], Policy]:
    stmt = (
        select(Policy)
        .where(
            Policy.namespace == namespace,
            Policy.key == key,
            Policy.is_active == True,
        )  # noqa: E712
        .limit(1)
    )
    row = db.session.execute(stmt).scalar_one_or_none()
    if not row:
        raise PolicyNotFoundError(f"No active policy for {namespace}.{key}")
    return stable_loads(row.value_json), row


def get_policy_value(family: str) -> Dict[str, Any]:
    namespace, key = family.split(".", 1)
    try:
        value, _ = get_policy(namespace, key)
        return value
    except PolicyNotFoundError:
        # Bootstrap from defaults if first use
        schema, default_value = POLICY_REGISTRY[family]
        set_policy(namespace, key, default_value, actor_entity_ulid=None)
        return default_value


# -----------------
# Emit event to ledger for "Set Policy"
# -----------------
def _emit_policy_event(
    *,
    op: str,  # "policy.created" | "policy.updated"
    namespace: str,
    key: str,
    new_version: int,
    new_value: dict,
    prev_version: int | None,
    prev_value: dict | None,
    actor_entity_ulid: str | None,
    request_id: str | None,
) -> None:
    """
    Push a normalized governance policy event onto the emit bus.
    Keeps ULIDs out of policy identity (which has no ULID) and records identity in meta.refs.
    """

    # Strongly prefer a caller-supplied request_id; fall back to a new ULID if missing.
    req_id = request_id or new_ulid()

    # Minimal, PII-free change summary
    changed = {
        "version_prev": prev_version,
        "version_new": new_version,
        # store compact JSON strings to keep envelope small & deterministic
        "value_prev_json": stable_dumps(prev_value)
        if prev_value is not None
        else None,
        "value_new_json": stable_dumps(new_value),
    }

    # References to identify *which* policy changed
    meta = {
        "refs": {
            "policy": {
                "namespace": namespace,
                "key": key,
                "version": new_version,
            }
        }
    }

    # Emit using domain+operation. Leave ULID “targets” empty (policies don’t have ULIDs).
    event_bus.emit(
        domain="governance",
        operation=f"policy.{op}",
        request_id=req_id,
        actor_ulid=actor_entity_ulid,  # may be None for system bootstrap; your sink should tolerate this
        target_ulid=None,  # no natural ULID for policies
        changed=changed,
        refs=meta.get("refs"),
    )


# -----------------
# Set Policy
# -----------------
def set_policy(
    namespace: str,
    key: str,
    value: Dict[str, Any],
    actor_entity_ulid: str | None,
    request_id: str | None = None,  # <— NEW (preferred)
) -> Policy:
    family = f"{namespace}.{key}"
    if family not in POLICY_REGISTRY:
        raise PolicyValidationError(f"unknown policy family {family}")

    # normalize + validate
    norm = _normalize_value(family, value)
    try:
        _VALIDATORS[family].validate(norm)
    except ValidationError as e:
        raise PolicyValidationError(str(e)) from e

    # find current active (if any)
    current = db.session.execute(
        select(Policy).where(
            Policy.namespace == namespace,
            Policy.key == key,
            Policy.is_active == True,  # noqa: E712
        )
    ).scalar_one_or_none()

    if current:
        prev_version = current.version
        prev_value = stable_loads(current.value_json)
        # retire current
        current.is_active = False
        current.updated_at_utc = now_iso8601_ms()
        db.session.add(current)
        next_ver = prev_version + 1
        schema_json = current.schema_json or stable_dumps(
            POLICY_REGISTRY[family][0]
        )
        op = "updated"
    else:
        prev_version = None
        prev_value = None
        max_ver = db.session.execute(
            select(func.max(Policy.version)).where(
                Policy.namespace == namespace, Policy.key == key
            )
        ).scalar_one_or_none()
        next_ver = (int(max_ver) + 1) if max_ver else 1
        schema_json = stable_dumps(POLICY_REGISTRY[family][0])
        op = "created"

    new_row = Policy(
        namespace=namespace,
        key=key,
        version=next_ver,
        value_json=stable_dumps(norm),
        schema_json=schema_json,
        is_active=True,
        updated_by_actor_ulid=actor_entity_ulid,
    )
    db.session.add(new_row)
    db.session.commit()  # commit first so the event reflects persisted state

    # Emit governance policy event
    _emit_policy_event(
        op=op,
        namespace=namespace,
        key=key,
        new_version=next_ver,
        new_value=norm,
        prev_version=prev_version,
        prev_value=prev_value,
        actor_entity_ulid=actor_entity_ulid,
        request_id=request_id,
    )

    return new_row
