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
       - ``load_policy_logitics_issuance()`` (JSON -> in-memory policy object),
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

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import asc, select

from app.extensions import db, event_bus
from app.extensions.policies import load_policy
from app.lib.chrono import add_years_utc, now_iso8601_ms
from app.lib.errors import PolicyError
from app.lib.geo import us_states
from app.lib.ids import new_ulid
from app.lib.jsonutil import (
    canonical_hash,
    safe_loads,
    stable_dumps,
    stable_loads,
)

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


class PolicyNotFoundError(ValueError):
    pass


class PolicyValidationError(ValueError):
    pass


@dataclass
class IssueDecision:
    allowed: bool
    reason: str | None = None
    approver_required: str | None = None
    limit_window_label: str | None = None
    next_eligible_at_iso: str | None = None

    # ✅ compatibility alias for older callers
    @property
    def ok(self) -> bool:
        return self.allowed


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


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


def svc_list_states_rows() -> list[CanonicalState]:
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


def svc_list_domain_roles_rows() -> list[RoleCode]:
    """Return ORM rows for active RoleCode, sorted by code."""

    return (
        db.session.query(RoleCode)
        .filter(RoleCode.is_active.is_(True))
        .order_by(asc(RoleCode.code))
        .all()
    )


# -----------------
# Registry
# (schema + defaults)
# Keep each value as
# an OBJECT with a
# single array field
# so you can evolve later.
# -----------------


ROLES_SCHEMA: dict[str, Any] = {
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


# -----------------
# Normalize policy value
# for a registered family
# -----------------
def _normalize_value(key: str, value: dict[str, Any]) -> dict[str, Any]:
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
def get_policy(namespace: str, key: str) -> tuple[dict[str, Any], Policy]:
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
def get_policy_value(family: str) -> dict[str, Any]:
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
        "value_prev_json": (
            stable_dumps(prev_value) if prev_value is not None else None
        ),
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
# Public Services
# used by the CLI
# -----------------


# Snapshot: canonical US state codes
def get_us_states_snapshot() -> list[str]:
    """Return a list of 2-letter state codes owned by Governance."""
    # read-only: Governance owns geo
    return [code for code, _name in us_states()]


# Seed: domain roles catalog
def seed_domain_roles(
    roles: list[dict[str, Any]],
    *,
    dry_run: bool = True,
    actor_ulid: str | None = None,
    happened_at: str | None = None,  # kept for signature symmetry; not used
) -> dict[str, Any]:
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
        emit_operation="role_catalog_updated",
    )


# Seed: officer catalog
def seed_office_catalog(
    offices: list[dict[str, Any]],
    *,
    dry_run: bool = True,
    actor_ulid: str | None = None,
    happened_at: str | None = None,
) -> dict[str, Any]:
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
        emit_operation="officer_catalog_updated",
    )


# Seed: spending policy v1
def seed_spending_policy_v1(
    policy: dict[str, Any],
    *,
    dry_run: bool = True,
    actor_ulid: str | None = None,
    happened_at: str | None = None,
) -> dict[str, Any]:
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
        emit_operation="spending_policy_updated",
    )


# Seed: restriction policy by opaque key
def seed_restriction_policies_v1(
    policy_row: dict[str, Any],
    *,
    dry_run: bool = True,
    actor_ulid: str | None = None,
    happened_at: str | None = None,
) -> dict[str, Any]:
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
        emit_operation="restriction_policy_updated",
        refs_extra={"policy_key": policy_key},
    )


# -----------------
# Publish a state machine
# as a policy
# -----------------


def publish_state_machine(
    sm: dict[str, Any],
    dry_run: bool = True,
    actor_ulid: str | None = None,
    happened_at: str | None = None,
) -> dict[str, Any]:
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
        emit_operation="state_machine_updated",
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
    db.session.flush()
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
        else datetime.now(UTC)
    )
    return dt.astimezone(UTC)


def _term_bounds_for_office(
    elected_on_iso: str, term_years: int = 2
) -> tuple[str, str]:
    start = _parse_date(elected_on_iso)
    end = add_years_utc(start, term_years)
    return (
        start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        end.astimezone(UTC).isoformat().replace("+00:00", "Z"),
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
        operation="role_domain_added",
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
        operation="role_domain_removed",
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
        emit_operation="officer_assigned",
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
        emit_operation="officer_revoked",
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
        emit_operation="pro_tem_assigned",
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
        emit_operation="pro_tem_revoked",
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
