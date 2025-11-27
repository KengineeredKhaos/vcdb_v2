# app/slices/governance/services.py

"""
VCDB v2 — Governance policy services

This module owns the *interpretation* of all Governance policy families.
It is the only place that is allowed to turn stored policy blobs (JSON) into
runtime-friendly objects and decision helpers.

High-level architecture
=======================

* Canonical store (target state)
  - All Governance policies live as JSON blobs in the ``Policy`` table
    (family, key, version, body_json).
  - During the v2 build-out, some older families are still file-backed under
    ``app/slices/governance/data/*.json``.  Helpers here (and in
    ``services_admin``) hide where the bits are stored from everyone else.

* Single access pipeline
  - Other slices and CLI commands MUST go through the
    ``app.extensions.contracts.governance_v2`` contract.
  - Callers never reach into this module or the ``Policy`` model directly.
  - Admin policy editing goes:
        Admin UI / CLI
        -> governance_v2 (admin layer)
        -> services_admin (file/DB read-write + schema validation)
        -> Policy table (or file, during transition)
        -> Ledger event.

* Read-only vs admin
  - This module focuses on **read-only** helpers and decision engines that
    the contract layer wraps (e.g. issuance decisions).
  - ``services_admin`` owns the **write path** for policies
    (preview/commit with JSON Schema validation and ledger emission).

Policy families
===============

Each family is a logical bucket of related rules with a shared JSON shape and
a single owner in the real world (the Board / Governance).  A given family has:

    * a storage location (file or Policy row, moving toward Policy-only),
    * a loader/validator here in ``governance.services``,
    * one or more accessors exposed via ``governance_v2``.

Current families (2025-11, v2 build-out):

1. Role catalogs (RBAC + domain roles)
   -----------------------------------
   * Subject:
       - RBAC roles (auth roles the app understands),
       - Domain roles (customer/resource/sponsor/governor, etc.).
   * Storage:
       - Seeded from JSON under ``governance/data/`` into code tables
         (e.g. ``RoleCode``), and/or Policy rows via the registry.
   * Helpers here:
       - Seed functions (e.g. ``seed_domain_roles``) that populate the DB
         from the canonical JSON/Policy blobs.
   * Exposed via contract:
       - ``governance_v2.get_role_catalogs()`` returns DTOs used by:
           - Auth slice (RBAC),
           - Governance/Admin UI (domain role assignment),
           - Devtools.

2. Issuance policy (inventory / cadence / blackout decisions)
   ----------------------------------------------------------
   * Subject:
       - Which SKUs can be issued to which customers,
       - Cadence windows, blackout behavior, and qualifiers
         (veteran / housing status, etc.).
   * Storage:
       - Currently file-backed (``policy_issuance.json``) under
         ``governance/data/``; target is a Policy row family
         (e.g. ``family="issuance"``).
   * Helpers here:
       - ``load_policy_issuance()`` (JSON -> in-memory policy object),
       - private helpers (``_rule_matches``, ``_check_qualifiers``,
         ``_apply_cadence``, etc.),
       - ``decide_issue(ctx)``: core decision engine.
   * Exposed via contract:
       - ``governance_v2.decide_issue(ctx) -> IssueDecision``
         used by Logistics slice, dev CLI ``dev decide-issue``,
         and issuance debug tooling.

   * Dependencies:
       - Calendar enforcers (blackout),
       - Logistics contracts (issuance counts in windows),
       - Customers contracts (eligibility snapshot).

3. Sponsor capability & lifecycle policy
   -------------------------------------
   * Subject:
       - Capability taxonomy for sponsors (what kinds of funding /
         in-kind support they offer),
       - Sponsor lifecycle states (readiness / MOU status enums).
   * Storage:
       - File-backed JSON (e.g. ``policy_sponsor_capabilities.json``,
         ``policy_sponsor_lifecycle.json``) under ``governance/data/``,
         with a planned migration into Policy rows
         (families like ``"sponsor_caps"`` and ``"sponsor_lifecycle"``).
   * Helpers here (planned):
       - Loader/validator functions such as
         ``get_sponsor_capability_policy()`` and
         ``get_sponsor_lifecycle_policy()`` that return normalized vocab.
   * Exposed via contract:
       - ``governance_v2.get_sponsor_capability_catalog()`` for the Sponsors
         slice to validate capability flags and build forms,
       - ``governance_v2.get_sponsor_lifecycle_policy()`` for validating
         readiness / MOU fields.

4. POC policy (points-of-contact)
   ------------------------------
   * Subject:
       - Controlled vocabulary for POC scopes (primary, backup, billing, etc.),
       - Maximum rank / counts where applicable.
   * Storage:
       - File-backed JSON (``policy_poc.json``) under ``governance/data/``,
         with target migration into a Policy family (e.g. ``"poc_policy"``).
   * Helpers:
       - Policy loader/validator lives in the contract layer today
         (``governance_v2.get_poc_policy()``); long term it may move here
         for consistency with other families.
   * Exposed via contract:
       - ``governance_v2.get_poc_policy()`` returns a DTO used by the shared
         POC helpers (Resource/Sponsor POC wiring, forms, and validations).

5. Spending / authorizations / officers
   ------------------------------------
   * Subject:
       - Officer catalog (Board offices, pro-tem roles),
       - Spending policies and who can authorize what
         (e.g., staff vs Treasurer for over-cap amounts),
       - Restrictions that apply to sponsors / programs.
   * Storage:
       - DB-backed via the ``Policy`` model and ``POLICY_REGISTRY``.
         Families include things like:
             * governance.officers
             * governance.spending_matrix
             * governance.restrictions
   * Helpers here:
       - ``_policy_upsert``, ``set_policy``, ``get_policy_value`` and seed
         helpers (e.g. ``seed_office_catalog``,
         ``seed_spending_policy_v1``, ``seed_restriction_policies_v1``).
   * Exposed via contract:
       - Read-only accessors (current and planned) that let the Admin, Finance,
         and Governance slices query these policies without touching the
         underlying tables directly.

Runtime rules
=============

* Only Governance reads/writes policy storage
  - No other slice should open JSON policy files or query the ``Policy``
    table directly.
  - All access flows through this module (for DB/file I/O) and the
    ``services_admin`` provider (for admin-grade edits).

* All external callers use contracts
  - Slices, routes, and CLI commands call
        ``app.extensions.contracts.governance_v2``
    for decisions and DTOs.
  - This allows the storage representation of any family (file vs Policy row)
    to change without forcing changes across the rest of the app.

* Migration strategy
  - As v2 stabilizes, file-backed families will be promoted into the Policy
    table one by one.  The public contract signatures (e.g.
    ``decide_issue``, ``get_role_catalogs``, ``get_poc_policy``, sponsor
    capability/lifecycle accessors) remain stable while the storage moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from typing import Any, Dict, List, Optional, Sequence

from jsonschema import Draft202012Validator
from jsonschema import ValidationError as JSONSchemaValidationError
from sqlalchemy import asc, func, select

from app.extensions import db, event_bus
from app.extensions.contracts import logistics_v2
from app.extensions.policies import (
    load_policy,
    load_policy_issuance,
)
from app.lib.chrono import add_years_utc, as_naive_utc, now_iso8601_ms
from app.lib.errors import PolicyError
from app.lib.geo import us_states
from app.lib.ids import new_ulid
from app.lib.jsonutil import (
    canonical_hash,
    is_json_equal,
    safe_loads,
    stable_dumps,
    stable_loads,
)
from app.slices.logistics.sku import parse_sku

from .models import CanonicalState, Policy, RoleCode, ServiceClassification

_PART_KEY_MAP = {
    "category": "cat",
    "subcategory": "sub",
    "source": "src",
    "size": "size",
    "color": "col",
    "issuance_class": "issuance_class",
    "seq": "seq",
}


def _map_part_key(k: str) -> str:
    return _PART_KEY_MAP.get(k, k)


class PolicyNotFoundError(ValueError):
    pass


class PolicyValidationError(ValueError):
    pass


@dataclass
class IssueDecision:
    allowed: bool
    reason: Optional[str] = None
    approver_required: Optional[str] = None
    limit_window_label: Optional[str] = None
    next_eligible_at_iso: Optional[str] = None

    # ✅ compatibility alias for older callers
    @property
    def ok(self) -> bool:
        return self.allowed


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


# -----------------
# Policy Loader Stack
# returns specific
# policy JSON as read
# from Governance/data/
# with eventual migration
# to read policy from
# governance.models.Polcy
# dbase table policy cache
# ------------------


# def get_resource_capabilities_policy() -> dict:
#     return _load_policy("policy_resource_capabilities.json")


# def get_resource_lifecycle_policy() -> dict:
#     return _load_policy("policy_resource_lifecycle.json")


# -----------------
# List active U.S. states
# (canonical rows)
# -----------------


def list_states() -> list[dict]:
    """
    Return [{'code','name'}, …] for active CanonicalState records,
    sorted by code.
    """
    rows = (
        db.session.query(CanonicalState)
        .filter_by(is_active=True)
        .order_by(asc(CanonicalState.code))
        .all()
    )
    return [{"code": r.code, "name": r.name} for r in rows]


# -----------------
# List Service Classifications
# (catalog)
# -----------------


def list_service_classifications() -> list[dict]:
    """
    Return [{'code','label','sort'}, …]
    for active ServiceClassification records, sorted.
    """

    rows = (
        db.session.query(ServiceClassification)
        .filter_by(is_active=True)
        .order_by(
            asc(ServiceClassification.sort), asc(ServiceClassification.code)
        )
        .all()
    )
    return [{"code": r.code, "label": r.label, "sort": r.sort} for r in rows]


# -----------------
# List Domain Roles
# (catalog)
# -----------------


def list_domain_roles() -> list[dict]:
    """
    Return [{'code','description'}, …]
    for active RoleCode records, sorted by code."""

    rows = (
        db.session.query(RoleCode)
        .filter_by(is_active=True)
        .order_by(asc(RoleCode.code))
        .all()
    )
    return [{"code": r.code, "description": r.description} for r in rows]


# -----------------
# Domain Roles
# JSON Policy-Backed
# (from policy_domain.json)
# -----------------


def _domain_rules():
    """
    Load the domain→RBAC assignment rules from JSON policy
    and return its 'assignment_rules' section."""

    return load_policy("policy_domain.json")["assignment_rules"]


# -----------------
# Guard:
# some domain roles
# may not have RBAC
# accounts during
# development
# (Staff/Governor)
# (Officers/ProTem)
# -----------------


def ensure_domain_allows_no_rbac(target_domain_roles: Sequence[str]) -> None:
    """
    Raise PolicyError if any role in target_domain_roles appears
    in 'domain_disallows_rbac'."""

    rules = _domain_rules()
    disallow = set(rules.get("domain_disallows_rbac", []))
    if disallow.intersection(target_domain_roles):
        raise PolicyError(
            "This entity's domain role(s) disallow RBAC accounts."
        )


# -----------------
# Permission:
# can this RBAC actor
# assign a domain role?
# -----------------


def can_assign_domain_role(
    actor_rbac: Sequence[str],
    target_domain_roles: Sequence[str],
    role_to_assign: str,
) -> None:
    """
    Raise PolicyError unless role_to_assign is in the
    actor’s allowed set and does not create a forbidden pair.
    """

    rules = _domain_rules()
    # RBAC→domain assignment permission
    allowed = set()
    for r in actor_rbac:
        allowed |= set(rules["rbac_can_assign"].get(r, []))
    if role_to_assign not in allowed:
        raise PolicyError(
            f"RBAC not permitted to assign domain role '{role_to_assign}'"
        )
    # Forbidden domain pairs (e.g., civilian + governor)
    for a, b in rules.get("forbidden_pairs", []):
        if role_to_assign == b and a in target_domain_roles:
            raise PolicyError(f"Cannot assign '{b}' to entity with '{a}'")


# -----------------
# Reconcile:
# domain roles required
# when RBAC roles are present
# -----------------


def reconcile_required_domain_for_rbac(
    target_rbac: Sequence[str], target_domain_roles: set[str]
) -> set[str]:
    """
    Return missing domain roles implied by target_rbac per
    policy 'must_include_when_rbac'.
    """

    rules = _domain_rules()
    required = set()
    for r in target_rbac:
        required |= set(rules.get("must_include_when_rbac", {}).get(r, []))
    return required - set(target_domain_roles)


# -----------------
# Internal Services
# (for contract v1)
# -----------------

# -----------------
# Internal:
# active CanonicalState rows
# -----------------


def svc_list_states_rows() -> List[CanonicalState]:
    """Return ORM rows for active CanonicalState, sorted by code."""
    return (
        db.session.query(CanonicalState)
        .filter(CanonicalState.is_active.is_(True))
        .order_by(asc(CanonicalState.code))
        .all()
    )


# -----------------
# Internal:
# active RoleCode rows
# -----------------


def svc_list_domain_roles_rows() -> List[RoleCode]:
    """Return ORM rows for active RoleCode, sorted by code."""

    return (
        db.session.query(RoleCode)
        .filter(RoleCode.is_active.is_(True))
        .order_by(asc(RoleCode.code))
        .all()
    )


# -----------------
# Internal:
# fetch policy row value
# -----------------


def svc_get_policy_value(namespace: str, key: str) -> Optional[dict]:
    """
    Return JSON value for the active Policy(namespace,key)
    or None if missing.
    """

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


# -----------------
# Registry
# (schema + defaults)
# Keep each value as
# an OBJECT with a
# single array field
# so you can evolve later.
# -----------------


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


# -----------------
# Normalize policy value
# for a registered family
# -----------------
def _normalize_value(key: str, value: Dict[str, Any]) -> Dict[str, Any]:
    """Lower/trim/dedupe the single array field defined by the family’s schema; raise PolicyValidationError on bad entries."""

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


# -----------------
# Enumerate known
# policy families
# (stable order)
# -----------------
def list_policy_keys() -> list[str]:
    """Return sorted POLICY_REGISTRY keys for discovery and UX/tests."""

    return sorted(POLICY_REGISTRY.keys())


# -----------------
# Get active policy
# (value + row)
# -----------------
def get_policy(namespace: str, key: str) -> tuple[Dict[str, Any], Policy]:
    """
    Fetch active Policy row and return (parsed_value, row);
    raise PolicyNotFoundError if none.
    """
    stmt = (
        select(Policy)
        .where(
            Policy.namespace == namespace,
            Policy.key == key,
            Policy.is_active.is_(True),
        )
        .limit(1)
    )
    row = db.session.execute(stmt).scalar_one_or_none()
    if not row:
        raise PolicyNotFoundError(f"No active policy for {namespace}.{key}")
    return stable_loads(row.value_json), row


# -----------------
# Get policy value
# (bootstrap with defaults if missing)
# -----------------
def get_policy_value(family: str) -> Dict[str, Any]:
    """
    Return parsed policy value for 'ns.key';
    if missing, create with defaults and return them.
    """

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
# Emit event to ledger
# for "Set Policy"
# -----------------


# -----------------
# Emit a governance.policy.* event
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
    Emit a normalized ledger event for policy create/update
    with compact JSON deltas and stable refs.
    Keeps ULIDs out of policy identity (which has no ULID)
    and records identity in meta.refs.
    """

    # Strongly prefer a caller-supplied request_id;
    # fall back to a new ULID if missing.
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

    # Emit using domain+operation. Leave ULID “targets” empty
    # (policies don’t have ULIDs).
    event_bus.emit(
        domain="governance",
        operation=f"policy.{op}",
        request_id=req_id,
        actor_ulid=actor_entity_ulid,
        # may be None for system bootstrap; your sink should tolerate this
        target_ulid=None,  # no natural ULID for policies
        changed=changed,
        refs=meta.get("refs"),
    )


# -----------------
# Set Policy
# -----------------


# -----------------
# Set/replace active
# policy version
# (with validation + event)
# -----------------
def set_policy(
    namespace: str,
    key: str,
    value: Dict[str, Any],
    actor_entity_ulid: str | None,
    request_id: str | None = None,  # <— NEW (preferred)
) -> Policy:
    """
    Normalize + validate input, retire current active (if any),
    insert new active version, and emit a ledger event.
    """
    family = f"{namespace}.{key}"
    if family not in POLICY_REGISTRY:
        raise PolicyValidationError(f"unknown policy family {family}")

    # normalize + validate
    norm = _normalize_value(family, value)
    try:
        _VALIDATORS[family].validate(norm)
    except JSONSchemaValidationError as e:
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


# -----------------
# Generic Policy Upsert
# (DB-backed)
# (versioned; emits single event)
# -----------------


def _policy_upsert(
    *,
    namespace: str,
    key: str,
    version: int,
    value: Dict[str, Any],
    schema: Dict[str, Any] | None,
    actor_ulid: str | None,
    dry_run: bool,
    emit_operation: str,
    refs_extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Create or update Policy(namespace,key,version);
    returns a small “diff plan”, and emits a single governance event
    on commit. Stores JSON strings in Policy.value_json / Policy.schema_json
    (ISO-8601 timestamps already handled by model).
    """
    existing: Policy | None = Policy.query.filter_by(
        namespace=namespace, key=key, version=version
    ).first()
    value_json = stable_dumps(value)
    schema_json = stable_dumps(schema or {})

    if existing:
        # Compare normalized JSON
        changed = (existing.value_json != value_json) or (
            existing.schema_json != schema_json
        )
        if not changed:
            return {
                "added": [],
                "removed": [],
                "unchanged": [f"{namespace}:{key}@{version}"],
                "changed": False,
            }

        if dry_run:
            return {
                "added": [f"update {namespace}:{key}@{version}"],
                "removed": [],
                "unchanged": [],
                "changed": True,
            }

        existing_value = safe_loads(
            existing.value_json or "null", default=None
        )
        existing_schema = safe_loads(
            existing.schema_json or "null", default=None
        )
        changed = (not is_json_equal(existing_value, value)) or (
            not is_json_equal(existing_schema, schema or {})
        )
        existing.value_json = value_json
        existing.schema_json = schema_json
        existing.updated_by_actor_ulid = actor_ulid
        db.session.add(existing)
        db.session.commit()

        event_bus.emit(
            domain="governance",
            operation=emit_operation,
            request_id=new_ulid(),
            actor_ulid=actor_ulid,
            target_ulid=None,
            changed={
                "namespace": namespace,
                "key": key,
                "version": version,
                "diff_summary": "created" if not existing else "updated",
                "content_hash": canonical_hash(
                    {"value": value, "schema": schema or {}}
                ),
            },
            refs={
                "policy": {
                    "namespace": namespace,
                    "key": key,
                    "version": version,
                },
                **(refs_extra or {}),
            },
            happened_at_utc=now_iso8601_ms(),
        )
        return {
            "added": [f"update {namespace}:{key}@{version}"],
            "removed": [],
            "unchanged": [],
            "changed": True,
        }

    # Create new
    if dry_run:
        return {
            "added": [f"create {namespace}:{key}@{version}"],
            "removed": [],
            "unchanged": [],
            "changed": True,
        }

    row = Policy(
        namespace=namespace,
        key=key,
        version=version,
        value_json=value_json,
        schema_json=schema_json,
        updated_by_actor_ulid=actor_ulid,
    )
    db.session.add(row)
    db.session.commit()

    event_bus.emit(
        domain="governance",
        operation=emit_operation,
        request_id=new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=None,
        changed={
            "namespace": namespace,
            "key": key,
            "version": version,
            "diff_summary": "created",
        },
        refs={
            "policy": {
                "namespace": namespace,
                "key": key,
                "version": version,
            },
            **(refs_extra or {}),
        },
        happened_at_utc=now_iso8601_ms(),
    )
    return {
        "added": [f"create {namespace}:{key}@{version}"],
        "removed": [],
        "unchanged": [],
        "changed": True,
    }


# -----------------
# Public Services
# used by the CLI
# -----------------


# Snapshot: canonical US state codes
def get_us_states_snapshot() -> List[str]:
    """Return a list of 2-letter state codes owned by Governance."""
    # read-only: Governance owns geo
    return [code for code, _name in us_states()]


# Seed: domain roles catalog
def seed_domain_roles(
    roles: List[Dict[str, Any]],
    *,
    dry_run: bool = True,
    actor_ulid: str | None = None,
    happened_at: str | None = None,  # kept for signature symmetry; not used
) -> Dict[str, Any]:
    """
    Upsert governance.roles@1 with a normalized unique list of role codes;
    emits 'role.catalog.updated'. Normalize to lowercase codes
    (matches your existing row preview)"""
    codes = [
        str(r.get("code", "")).strip().lower() for r in roles if r.get("code")
    ]
    payload = {"roles": sorted(set(codes))}
    schema = {
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
                "uniqueItems": True,
                "minItems": 1,
            }
        },
    }
    return _policy_upsert(
        namespace="governance",
        key="roles",
        version=1,
        value=payload,
        schema=schema,
        actor_ulid=actor_ulid,
        dry_run=dry_run,
        emit_operation="role.catalog.updated",
    )


# Seed: officer catalog
def seed_office_catalog(
    offices: List[Dict[str, Any]],
    *,
    dry_run: bool = True,
    actor_ulid: str | None = None,
    happened_at: str | None = None,
) -> Dict[str, Any]:
    """
    Upsert governance.officers@1 catalog (code/name/cycle/term);
    emits 'officer.catalog.updated'.
    """
    normalized = []
    for o in offices:
        normalized.append(
            {
                "office_code": str(o["office_code"]).lower(),
                "name": o["name"],
                "election_cycle": str(
                    o["election_cycle"]
                ).lower(),  # "even"/"odd"
                "term_years": int(o.get("term_years", 2)),
            }
        )
    payload = {"offices": normalized}
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["offices"],
        "properties": {
            "offices": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "office_code",
                        "name",
                        "election_cycle",
                        "term_years",
                    ],
                    "properties": {
                        "office_code": {"type": "string"},
                        "name": {"type": "string"},
                        "election_cycle": {
                            "type": "string",
                            "enum": ["even", "odd"],
                        },
                        "term_years": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
                },
                "minItems": 1,
            }
        },
        "additionalProperties": False,
    }
    return _policy_upsert(
        namespace="governance",
        key="offices",
        version=1,
        value=payload,
        schema=schema,
        actor_ulid=actor_ulid,
        dry_run=dry_run,
        emit_operation="officer.catalog.updated",
    )


# Seed: spending policy v1
def seed_spending_policy_v1(
    policy: Dict[str, Any],
    *,
    dry_run: bool = True,
    actor_ulid: str | None = None,
    happened_at: str | None = None,
) -> Dict[str, Any]:
    """
    Upsert governance.spending.matrix@version with action→role caps;
    emits 'spending.policy.updated'.
    """
    version = int(policy.get("version", 1))
    payload = {
        "version": version,
        "actions": policy.get("actions", []),
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["version", "actions"],
        "properties": {
            "version": {"type": "integer", "minimum": 1},
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["action", "role_caps"],
                    "properties": {
                        "action": {"type": "string"},
                        "role_caps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["role_code"],
                                "properties": {
                                    "role_code": {"type": "string"},
                                    "cap": {"type": ["number", "null"]},
                                },
                                "additionalProperties": False,
                            },
                        },
                        "countersign": {"type": ["string", "null"]},
                        "notify": {"type": ["string", "null"]},
                        "notify_sla_hours": {"type": ["integer", "null"]},
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }
    return _policy_upsert(
        namespace="governance.spending",
        key="matrix",
        version=version,
        value=payload,
        schema=schema,
        actor_ulid=actor_ulid,
        dry_run=dry_run,
        emit_operation="spending.policy.updated",
    )


# Seed: restriction policy by opaque key
def seed_restriction_policies_v1(
    policy_row: Dict[str, Any],
    *,
    dry_run: bool = True,
    actor_ulid: str | None = None,
    happened_at: str | None = None,
) -> Dict[str, Any]:
    """
    Upsert <namespace>.restrictions@version inferred from policy_key;
    emits 'restriction.policy.updated'.
    """
    policy_key = str(policy_row["policy_key"])
    version = int(policy_row.get("version", 1))
    payload = {
        "policy_key": policy_key,
        "version": version,
        "payload": policy_row.get("payload", {}),
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["policy_key", "version", "payload"],
        "properties": {
            "policy_key": {"type": "string"},
            "version": {"type": "integer", "minimum": 1},
            "payload": {"type": "object"},
        },
        "additionalProperties": False,
    }
    # namespacing by domain inferred from policy_key
    # e.g., "finance.donations.restrictions" ->
    # namespace="finance.donations", key="restrictions"
    parts = policy_key.split(".")
    namespace = ".".join(parts[:-1]) if len(parts) > 1 else "governance"
    key = parts[-1] if parts else "policy"
    return _policy_upsert(
        namespace=namespace,
        key=key,
        version=version,
        value=payload,
        schema=schema,
        actor_ulid=actor_ulid,
        dry_run=dry_run,
        emit_operation="restriction.policy.updated",
        refs_extra={"policy_key": policy_key},
    )


# -----------------
# Publish a state machine
# as a policy
# -----------------


def publish_state_machine(
    sm: Dict[str, Any],
    dry_run: bool = True,
    actor_ulid: str | None = None,
    happened_at: str | None = None,
) -> Dict[str, Any]:
    """
    Validate and upsert governance.state_machine:
    <policy_key>:<entity>@version with states/transitions;
    emits 'state_machine.updated'.
    Persist a state machine under a stable policy namespace:
      namespace="governance.state_machine"
      key=f"{policy_key}:{entity_kind}"
      version=sm['version']
      value={"policy_key","entity_kind","version","states","transitions"}
    """
    required = [
        "policy_key",
        "entity_kind",
        "version",
        "states",
        "transitions",
    ]
    missing = [k for k in required if k not in sm]
    if missing:
        return {
            "added": [],
            "removed": [],
            "unchanged": [],
            "changed": False,
            "error": f"missing keys: {', '.join(missing)}",
        }

    policy_key = str(sm["policy_key"])
    entity_kind = str(sm["entity_kind"])
    version = int(sm["version"])

    payload = {
        "policy_key": policy_key,
        "entity_kind": entity_kind,
        "version": version,
        "states": sm.get("states", []),
        "transitions": sm.get("transitions", []),
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": [
            "policy_key",
            "entity_kind",
            "version",
            "states",
            "transitions",
        ],
        "properties": {
            "policy_key": {"type": "string"},
            "entity_kind": {"type": "string"},
            "version": {"type": "integer", "minimum": 1},
            "states": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["code"],
                    "properties": {
                        "code": {"type": "string"},
                        "initial": {"type": "boolean"},
                        "terminal": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            },
            "transitions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["from", "to"],
                    "properties": {
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "guards": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }
    return _policy_upsert(
        namespace="governance.state_machine",
        key=f"{policy_key}:{entity_kind}",
        version=version,
        value=payload,
        schema=schema,
        actor_ulid=actor_ulid,
        dry_run=dry_run,
        emit_operation="state_machine.updated",
        refs_extra={"policy_key": policy_key, "entity_kind": entity_kind},
    )


# -----------------
# Officers & Pro-Tem
# DB-backed stubs
# -----------------

# Storage shape (in Policy):
# - Officers:
#   namespace="governance.officers", key="assignments", version=1
#   value = {"assignments":[{"grant_ulid","office_code","holder_ulid",
#            "elected_on","term_start","term_end","active":true}]}
# - Pro-Tem:
#   namespace="governance.pro_tem", key="assignments", version=1
#   value = {"assignments":[{"grant_ulid","office_code","assignee_ulid",
#            "effective_start","effective_end","active":true}]}

# -----------------
# tiny helpers
# -----------------


def _load_policy_value(namespace: str, key: str, version: int = 1) -> dict:
    row = Policy.query.filter_by(
        namespace=namespace, key=key, version=version
    ).first()
    if not row or not row.value_json:
        return {"assignments": []}
    return safe_loads(row.value_json, default={"assignments": []})


def _save_policy_value(
    *,
    namespace: str,
    key: str,
    version: int,
    value: dict,
    actor_ulid: str,
    emit_operation: str,
    diff_summary: str,
    refs_extra: dict | None = None,
) -> None:
    payload_json = stable_dumps(value)
    row = Policy.query.filter_by(
        namespace=namespace, key=key, version=version
    ).first()
    if row:
        row.value_json = payload_json
        row.updated_by_actor_ulid = actor_ulid
        db.session.add(row)
    else:
        row = Policy(
            namespace=namespace,
            key=key,
            version=version,
            value_json=payload_json,
            schema_json=stable_dumps(
                {"$schema": "https://json-schema.org/draft/2020-12/schema"}
            ),
            updated_by_actor_ulid=actor_ulid,
        )
        db.session.add(row)
    db.session.commit()
    event_bus.emit(
        domain="governance",
        operation=emit_operation,
        request_id=new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=None,
        changed={
            "namespace": namespace,
            "key": key,
            "version": version,
            "diff_summary": diff_summary,
            "content_hash": canonical_hash(value),
        },
        refs={
            "policy": {
                "namespace": namespace,
                "key": key,
                "version": version,
            },
            **(refs_extra or {}),
        },
        happened_at_utc=now_iso8601_ms(),
    )


def _parse_date(s: str) -> datetime:
    # expects ISO8601 Z or naive; returns aware UTC
    dt = (
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        if s
        else datetime.now(timezone.utc)
    )
    return dt.astimezone(timezone.utc)


def _term_bounds_for_office(
    elected_on_iso: str, term_years: int = 2
) -> tuple[str, str]:
    start = _parse_date(elected_on_iso)
    end = add_years_utc(start, term_years)
    return (
        start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def _find_office_term(
    officers_value: dict, office_code: str
) -> tuple[str, str] | None:
    # finds the active officer for the office and returns
    # (term_start, term_end)
    for a in officers_value.get("assignments", []):
        if a.get("office_code") == office_code and a.get("active"):
            return (a["term_start"], a["term_end"])
    return None


def _entity_has_any_gov_assignment(
    officers_value: dict, protem_value: dict, subject_ulid: str
) -> bool:
    for a in officers_value.get("assignments", []):
        if a.get("holder_ulid") == subject_ulid and a.get("active"):
            return True
    for p in protem_value.get("assignments", []):
        if p.get("assignee_ulid") == subject_ulid and p.get("active"):
            return True
    return False


def _emit_domain_role_added_governor(
    entity_ulid: str,
    actor_ulid: str,
    reason: str = "auto-grant via officer/pro-tem",
):
    event_bus.emit(
        domain="governance",
        operation="role.domain.added",
        request_id=new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=entity_ulid,
        changed={"role_code": "governor", "reason": reason},
        refs={},
        happened_at_utc=now_iso8601_ms(),
    )


def _emit_domain_role_removed_governor(
    entity_ulid: str,
    actor_ulid: str,
    reason: str = "auto-revoke; no remaining officer/pro-tem grants",
):
    event_bus.emit(
        domain="governance",
        operation="role.domain.removed",
        request_id=new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=entity_ulid,
        changed={"role_code": "governor", "reason": reason},
        refs={},
        happened_at_utc=now_iso8601_ms(),
    )


# -----------------
# Officer Assignments
# (public stubs)
# (DB-backed via Policy)
# -----------------

# -----------------
# Assign Officer
# (single active per office)
# -----------------


def assign_officer(
    subject_ulid: str,
    office_code: str,
    elected_on: str,
    actor_ulid: str,
    *,
    term_years: int = 2,
    dry_run: bool = False,
) -> dict:
    """
    Deactivate any active holder, create a new grant (term bounds),
    persist policy, emit events, and auto-grant Governor role (event).
    """
    office_code = office_code.lower().strip()
    officers = _load_policy_value("governance.officers", "assignments", 1)

    # close any active holder for this office
    changed = False
    for a in officers["assignments"]:
        if a.get("office_code") == office_code and a.get("active"):
            a["active"] = False
            changed = True

    term_start, term_end = _term_bounds_for_office(elected_on, term_years)
    grant_ulid = new_ulid()
    new_row = {
        "grant_ulid": grant_ulid,
        "office_code": office_code,
        "holder_ulid": subject_ulid,
        "elected_on": elected_on,
        "term_start": term_start,
        "term_end": term_end,
        "active": True,
    }
    officers["assignments"].append(new_row)
    changed = True or changed

    if dry_run:
        return {
            "added": [f"officer {office_code}→{subject_ulid}"],
            "removed": [],
            "unchanged": [],
            "changed": True,
        }

    _save_policy_value(
        namespace="governance.officers",
        key="assignments",
        version=1,
        value=officers,
        actor_ulid=actor_ulid,
        emit_operation="officer.assigned",
        diff_summary=f"{office_code}→{subject_ulid}",
        refs_extra={"grant_ulid": grant_ulid, "office_code": office_code},
    )

    # officer grant implies Governor domain role (event)
    _emit_domain_role_added_governor(subject_ulid, actor_ulid)

    return new_row


# -----------------
# Revoke Officer grant
# -----------------


def revoke_officer(
    grant_ulid: str, reason: str, actor_ulid: str, *, dry_run: bool = False
) -> dict:
    """
    Deactivate the specified officer grant;
    reconcile and emit Governor removal if no remaining grants exist.
    """

    officers = _load_policy_value("governance.officers", "assignments", 1)
    prot = _load_policy_value("governance.pro_tem", "assignments", 1)

    found = None
    for a in officers["assignments"]:
        if a.get("grant_ulid") == grant_ulid and a.get("active"):
            a["active"] = False
            found = a
            break
    if not found:
        return {
            "added": [],
            "removed": [],
            "unchanged": [f"officer grant {grant_ulid} not active"],
            "changed": False,
        }

    subject_ulid = found["holder_ulid"]
    if dry_run:
        return {
            "added": [],
            "removed": [f"officer grant {grant_ulid}"],
            "unchanged": [],
            "changed": True,
        }

    _save_policy_value(
        namespace="governance.officers",
        key="assignments",
        version=1,
        value=officers,
        actor_ulid=actor_ulid,
        emit_operation="officer.revoked",
        diff_summary=f"grant {grant_ulid} ({reason})",
        refs_extra={
            "grant_ulid": grant_ulid,
            "office_code": found["office_code"],
        },
    )

    # If no other active officer/pro-tem grants remain for this subject,
    # emit Governor removal
    if not _entity_has_any_gov_assignment(officers, prot, subject_ulid):
        _emit_domain_role_removed_governor(subject_ulid, actor_ulid)

    return {"revoked_grant_ulid": grant_ulid, "reason": reason}


# -----------------
# Assign Pro-Tem
# (clamped to officer term)
# -----------------


def assign_pro_tem(
    subject_ulid: str,
    office_code: str,
    actor_ulid: str,
    *,
    start_on: str | None = None,
    end_on: str | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Create an active pro-tem grant within the officer term window;
    persist, emit events, and auto-grant Governor role (event).
    """

    office_code = office_code.lower().strip()
    officers = _load_policy_value("governance.officers", "assignments", 1)
    protem = _load_policy_value("governance.pro_tem", "assignments", 1)

    # derive officer term window (must exist)
    term = _find_office_term(officers, office_code)
    if not term:
        return {
            "added": [],
            "removed": [],
            "unchanged": [f"no active officer for {office_code}"],
            "changed": False,
        }
    term_start_iso, term_end_iso = term

    eff_start = (
        _parse_date(start_on or now_iso8601_ms())
        .isoformat()
        .replace("+00:00", "Z")
    )
    eff_end_candidate = (
        _parse_date(end_on).isoformat().replace("+00:00", "Z")
        if end_on
        else term_end_iso
    )
    # clamp to officer term_end
    eff_end = min(eff_end_candidate, term_end_iso)

    grant_ulid = new_ulid()
    row = {
        "grant_ulid": grant_ulid,
        "office_code": office_code,
        "assignee_ulid": subject_ulid,
        "effective_start": eff_start,
        "effective_end": eff_end,
        "active": True,
    }
    protem["assignments"].append(row)

    if dry_run:
        return {
            "added": [f"pro-tem {office_code}→{subject_ulid}"],
            "removed": [],
            "unchanged": [],
            "changed": True,
        }

    _save_policy_value(
        namespace="governance.pro_tem",
        key="assignments",
        version=1,
        value=protem,
        actor_ulid=actor_ulid,
        emit_operation="pro_tem.assigned",
        diff_summary=f"{office_code}→{subject_ulid}",
        refs_extra={"grant_ulid": grant_ulid, "office_code": office_code},
    )

    _emit_domain_role_added_governor(subject_ulid, actor_ulid)

    return row


# -----------------
# Revoke Pro-Tem grant
# -----------------


def revoke_pro_tem(
    grant_ulid: str, reason: str, actor_ulid: str, *, dry_run: bool = False
) -> dict:
    """
    Deactivate the specified pro-tem grant;
    emit Governor removal if no officer/pro-tem grants remain.
    """
    protem = _load_policy_value("governance.pro_tem", "assignments", 1)
    officers = _load_policy_value("governance.officers", "assignments", 1)

    found = None
    for p in protem["assignments"]:
        if p.get("grant_ulid") == grant_ulid and p.get("active"):
            p["active"] = False
            found = p
            break
    if not found:
        return {
            "added": [],
            "removed": [],
            "unchanged": [f"pro-tem grant {grant_ulid} not active"],
            "changed": False,
        }

    subject_ulid = found["assignee_ulid"]

    if dry_run:
        return {
            "added": [],
            "removed": [f"pro-tem grant {grant_ulid}"],
            "unchanged": [],
            "changed": True,
        }

    _save_policy_value(
        namespace="governance.pro_tem",
        key="assignments",
        version=1,
        value=protem,
        actor_ulid=actor_ulid,
        emit_operation="pro_tem.revoked",
        diff_summary=f"grant {grant_ulid} ({reason})",
        refs_extra={
            "grant_ulid": grant_ulid,
            "office_code": found["office_code"],
        },
    )

    # If no other active officer/pro-tem grants remain for this subject,
    # emit Governor removal
    if not _entity_has_any_gov_assignment(officers, protem, subject_ulid):
        _emit_domain_role_removed_governor(subject_ulid, actor_ulid)

    return {"revoked_grant_ulid": grant_ulid, "reason": reason}


# -----------------
# Elements Under Test
# (v2 evaluator)
# -----------------


@dataclass(frozen=True)
class _Cadence:
    max_per_period: int
    period_days: int
    label: str


@dataclass(frozen=True)
class _Rule:
    id: str
    match: Dict[str, Any]
    qualifiers: Dict[str, Any]
    cadence: _Cadence


# --- Unda Test ---
# Cadence calculator
# (with defaults + scope)
# --- Unda Test ---


def _apply_cadence(rule, ctx):
    """
    Enforce rule/default cadence (period_days/max_per,
    scope=sku|classification); returns (ok, window_label, next_eligible_iso?).
    """

    cad = rule.get("cadence") or {}
    label = cad.get("label")
    period_days = int(cad.get("period_days", 0) or 0)
    max_per = int(cad.get("max_per_period", 0) or 0)
    scope = cad.get("scope") or "classification"  # "classification" | "sku"

    if not period_days or not max_per:
        # no cadence => always ok
        return True, label, None

    # compute window start
    as_of = (
        getattr(ctx, "as_of_iso", None)
        or getattr(ctx, "when_iso", None)
        or now_iso8601_ms()
    )
    as_of_dt = as_naive_utc(as_of)  # or your existing parse
    window_start_dt = as_of_dt - timedelta(days=period_days)
    window_start_iso = (
        window_start_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z"
    )  # match your format

    # count issues per scope
    if scope == "sku":
        count = logistics_v2.count_issues_in_window(
            customer_ulid=ctx.customer_ulid,
            sku_code=ctx.sku_code,
            window_start_iso=window_start_iso,
            as_of_iso=as_of,
        )
    else:  # classification
        count = logistics_v2.count_issues_in_window(
            customer_ulid=ctx.customer_ulid,
            classification_key=ctx.classification_key,
            window_start_iso=window_start_iso,
            as_of_iso=as_of,
        )

    if count < max_per:
        # still within quota
        return True, label, None

    # over limit — compute next eligibility = end of window
    next_eligible_dt = window_start_dt + timedelta(days=period_days)
    next_eligible_iso = (
        next_eligible_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z"
    )
    return False, label, next_eligible_iso


# --- Unda Test ---
# Build cadence dict
# from preset or rule,
# inheriting defaults
# --- Unda Test ---


def _cadence_from(rule: dict, *, defaults: dict) -> dict:
    """
    Return a cadence dict merging preset/rule values with
    policy.defaults.cadence (period_days, max_per_period, label, scope).
    """

    preset = rule.get("cadence_preset")
    if preset:
        mapping = {
            "annual": {
                "period_days": 365,
                "max_per_period": 1,
                "label": "annual",
            },
            "semiannual": {
                "period_days": 182,
                "max_per_period": 1,
                "label": "semiannual",
            },
            "quarterly": {
                "period_days": 90,
                "max_per_period": 1,
                "label": "quarterly",
            },
        }
        c = dict(mapping[preset])
    else:
        c = dict(rule.get("cadence", {}))
    # inherit defaults, then override
    d = (defaults or {}).get("cadence", {})
    c.setdefault("period_days", d.get("period_days", 365))
    c.setdefault("max_per_period", d.get("max_per_period", 1))
    c.setdefault("label", d.get("label"))
    c.setdefault("scope", d.get("scope", "classification"))
    return c


# --- Unda Test ---
# Rule Matching
# scan for sku
# rule matches
# --- Unda Test ---


def _rule_matches(rule: dict, ctx) -> bool:
    """
    Return True if ctx matches rule.match.
    {classification_key, sku (glob), sku_parts}.
    A missing key in the rule means "don't care" for that dimension.
    """
    m = rule.get("match") or {}

    # 1) classification key (optional)
    r_ckey = m.get("classification_key", None)
    if r_ckey is not None:
        if getattr(ctx, "classification_key", None) != r_ckey:
            return False

    # 2) sku glob (optional)
    r_sku_glob = m.get("sku", None)
    if r_sku_glob:
        if not fnmatch(getattr(ctx, "sku_code", "") or "", r_sku_glob):
            return False

    # 3) sku_parts (optional; all listed parts must match exactly)
    r_parts = m.get("sku_parts") or {}
    if r_parts:
        parts = getattr(ctx, "sku_parts", None) or parse_sku(
            getattr(ctx, "sku_code", "") or ""
        )
        if not parts:
            return False
        for human_k, expected_v in r_parts.items():
            pk = _PART_KEY_MAP.get(human_k, human_k)
            if parts.get(pk) != expected_v:
                return False

    return True


# --- Unda Test ---
# Glob match for SKU codes
# --- Unda Test ---


def _sku_glob_match(code: str, pattern: str) -> bool:
    """
    Return fnmatch(code, pattern) for SKU strings like 'CG-SL-LC-*-*-H-*'.
    """
    import fnmatch

    return fnmatch.fnmatch(code, pattern)


# --- Unda Test ---
# Per-SKU hard constraints
# (hard and fast rules)
# Check SKU for V | H
# Vertran required: True
# Homeless required: True
# --- Unda Test ---


def _check_sku_constraints(rule: dict, ctx):
    if not ctx.sku_code:
        return True, None

    p = parse_sku(ctx.sku_code)  # {cat, sub, src, size, col, qual, seq}

    # 1) Any 'DR' source requires issuance_class == 'V'
    if p["src"] == "DR":
        if p["issuance_class"] != "V":
            return False, "sku_restricted"  # wrong issuance class

    # 2) (CG, SL, LC) requires issuance_class == 'H'
    if p["cat"] == "CG" and p["sub"] == "SL" and p["src"] == "LC":
        if p["issuance_class"] != "H":
            return False, "sku_restricted"

    return True, None


# -----------------
# Decision Matrix
# decide who can get
# what and how often
#
# governance/services.py
# (helpers near the top of the file)
# -----------------

# -----------------
# Decision helper
# typed IssueDecision
# -----------------


def _decision(
    *,
    ok: bool,
    reason: str,
    approver_required: str | None = None,
    limit_window_label: str | None = None,
    next_eligible_at_iso: str | None = None,
):
    """
    Construct and return an IssueDecision DTO for a consistent caller surface.
    """
    # IssueDecision comes from extensions.contracts.governance_v2
    from app.extensions.contracts.governance_v2 import IssueDecision

    return IssueDecision(
        allowed=ok,
        reason=reason,
        approver_required=approver_required,
        limit_window_label=limit_window_label,
        next_eligible_at_iso=next_eligible_at_iso,
    )


# -----------------
# Gate Normalizer
# this is aa band aid
# applied while chasing
# a bug that reports
# Fail as okay
# which is wrong,
# Yet here we are
# patching stupid
# -----------------
def _norm_gate(
    ok: bool, why: str | dict | None, default_fail_reason: str
) -> tuple[bool, str | None]:
    """
    Normalize a gate result:
      - success → (True, None)
      - failure → (False, reason or default_fail_reason)
    Accepts why as str/dict/None (dict should have "reason").
    """
    if ok:
        return True, None
    # failure
    if isinstance(why, dict):
        why = why.get("reason") or default_fail_reason
    elif isinstance(why, str):
        why = why or default_fail_reason
    else:
        why = default_fail_reason
    return False, why


# -----------------
# Entry point:
# decide if an item
# can be issued
# to a customer now
# -----------------


def decide_issue(ctx):
    """
    Enforcer → rule match (or default posture) → hard SKU constraints → qualifiers → cadence.
    Returns IssueDecision(ok/why, window label, next eligible).
    """
    from app.extensions.enforcers import calendar_blackout_ok

    pol = load_policy_issuance()
    default_behavior = (pol.get("default_behavior") or "deny").lower()

    # 1) Calendar blackout
    ok, meta = calendar_blackout_ok(ctx)
    ok, why = _norm_gate(ok, meta, "calendar_blackout")
    if not ok:
        label = meta.get("label") if isinstance(meta, dict) else None
        return _decision(ok=False, reason=why, limit_window_label=label)

    # 2) First matching rule
    matching = None
    for r in pol.get("rules", []):
        if _rule_matches(r, ctx):
            matching = r
            break

    # 3) Hard SKU constraints always enforced
    ok_sku, why_sku = _check_sku_constraints(matching or {}, ctx)
    ok_sku, why_sku = _norm_gate(ok_sku, why_sku, "sku_restricted")
    if not ok_sku:
        return _decision(ok=False, reason=why_sku)

    # 4) No rule matched → apply default posture
    if not matching:
        if default_behavior == "allow":
            ctx.qualifiers = {}
            ctx.defaults_cadence = (pol.get("defaults") or {}).get(
                "cadence"
            ) or {}
            ok_cad, window_label, next_eligible = _apply_cadence({}, ctx)
            ok_cad, why_cad = _norm_gate(ok_cad, None, "cadence_limit")
            if not ok_cad:
                return _decision(
                    ok=False,
                    reason=why_cad,
                    limit_window_label=window_label,
                    next_eligible_at_iso=next_eligible,
                )
            return _decision(ok=True, reason="ok")
        return _decision(ok=False, reason="no_matching_rule")

    # 5) Rule matched → qualifiers then cadence
    ctx.qualifiers = matching.get("qualifiers") or {}
    ctx.defaults_cadence = (pol.get("defaults") or {}).get("cadence") or {}

    ok_q, why_q = _check_qualifiers(ctx)
    ok_q, why_q = _norm_gate(ok_q, why_q, "qualifiers_not_met")
    if not ok_q:
        return _decision(ok=False, reason=why_q)

    ok_cad, window_label, next_eligible = _apply_cadence(matching, ctx)
    ok_cad, why_cad = _norm_gate(ok_cad, None, "cadence_limit")
    if not ok_cad:
        return _decision(
            ok=False,
            reason=why_cad,
            limit_window_label=window_label,
            next_eligible_at_iso=next_eligible,
        )

    return _decision(ok=True, reason="ok")


def _check_qualifiers(ctx) -> tuple[bool, str | None]:
    """
    Returns (ok, reason_if_denied).
    Uses the snapshot from customers_v2 (or your current customer_v2) contract.
    """
    from app.extensions.contracts import customer_v2

    # your actual module name

    snap = customer_v2.get_eligibility_snapshot(ctx.customer_ulid)

    # If the rule requires veteran / homeless, ensure snapshot says so
    req = getattr(ctx, "qualifiers", {}) or {}
    if req.get("veteran_required") and not snap.is_veteran_verified:
        return (False, "qualifiers_not_met")
    if req.get("homeless_required") and not snap.is_homeless_verified:
        return (False, "qualifiers_not_met")
    return (True, None)
