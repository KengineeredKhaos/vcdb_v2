# app/slices/governance/services.py
from __future__ import annotations

import json
from typing import Any, Dict, Tuple

from jsonschema import Draft202012Validator, ValidationError
from sqlalchemy import asc, func, select

from app.extensions import db, event_bus
from app.extensions import policy as policy_cache
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps, stable_loads  # from your lib.zip

from .models import CanonicalState, RoleCode, ServiceClassification


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


# ---- Public API -------------------------------------------------------------


def list_policy_keys() -> list[str]:
    return list(POLICY_REGISTRY.keys())


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


def set_policy(
    namespace: str,
    key: str,
    value: Dict[str, Any],
    actor_entity_ulid: str | None,
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

    # find current active
    current = db.session.execute(
        select(Policy).where(
            Policy.namespace == namespace,
            Policy.key == key,
            Policy.is_active == True,
        )  # noqa: E712
    ).scalar_one_or_none()

    # determine next version
    if current:
        current.is_active = False
        current.updated_at_utc = now_iso8601_ms()
        db.session.add(current)
        next_ver = current.version + 1
        schema_json = current.schema_json or stable_dumps(
            POLICY_REGISTRY[family][0]
        )
    else:
        max_ver = db.session.execute(
            select(func.max(Policy.version)).where(
                Policy.namespace == namespace, Policy.key == key
            )
        ).scalar_one_or_none()
        next_ver = (int(max_ver) + 1) if max_ver else 1
        schema_json = stable_dumps(POLICY_REGISTRY[family][0])

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
    db.session.commit()

    # refresh cache + emit names-only event
    policy_cache.refresh()
    event_bus.emit(
        type="governance.policy.updated",
        slice="governance",
        operation="insert",
        actor_id=actor_entity_ulid,
        target_id=new_row.ulid,
        request_id=new_row.ulid,
        happened_at=now_iso8601_ms(),
        refs={"family": family, "version": next_ver},
    )

    return new_row
