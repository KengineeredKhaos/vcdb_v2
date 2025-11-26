# app/extensions/contracts/governance_v2.py

"""
VCDB v2 — Governance contract (v2)

This module is the **only public interface** other slices, CLI commands, and
UI code should use to interact with Governance policy and decisions.

It sits on top of the internal services layer defined in
``app.slices.governance.services`` (see that module’s policy map docstring for
full details of the policy families and storage model).

It is intentionally thin:

    routes / services / CLI
        -> app.extensions.contracts.governance_v2
        -> app.slices.governance.services   (read-only helpers & decision engines)
        -> app.slices.governance.services_admin  (admin write-path only)

The full “policy map” — which policy families exist, where they are stored
(DB vs JSON files), and which helpers interpret them — lives in the top-of-file
docstring in ``app.slices.governance.services``. See that file for the
canonical catalog of policy families and migration plan. :contentReference[oaicite:0]{index=0}

This contract module does three things:

* Expose **stable, versioned functions** that other slices can call
  (e.g. ``decide_issue``, ``get_role_catalogs``, POC/sponsor catalogs, etc.),
  returning simple DTOs instead of ORM rows.
* Normalize error handling, so callers only ever see
  ``app.extensions.errors.ContractError`` on failure.
* Hide storage and implementation details so we can move a policy family
  from JSON files to the ``Policy`` table (or update the decision logic)
  without touching callers.

Design
======

* No other slice imports ``app.slices.governance.services`` directly.
  They *only* import this contract module.
* This module does *not* reach into Governance models either; it delegates
  to ``governance.services`` / ``governance.services_admin`` and focuses on
  arguments, DTOs, and error translation.
* Once a v2 contract function signature ships, we treat it as stable; new
  behavior comes in as v3 side-by-side rather than mutating v2 in place.

* Single entry point
  - Callers import from here, never from ``governance.services`` or the
    ``Policy`` model directly.
  - This allows Governance to move policy families from file-backed JSON
    into DB-backed ``Policy`` rows without breaking callers.

* DTOs, not models
  - All functions here return simple dataclasses / dicts / primitives
    (IssueDecision, role catalogs, POC policy, etc.).
  - No SQLAlchemy models or raw JSON blobs cross this boundary.

* Runtime vs admin
  - **Runtime contracts** (safe for any slice to use at request time):
        - ``decide_issue(ctx) -> IssueDecision``
            Core issuance decision engine for Logistics and dev CLI.
        - ``get_role_catalogs() -> RoleCatalogDTO``
            RBAC + domain role vocab for Auth, Governance, Admin UI.
        - ``get_poc_policy() -> POCPolicyDTO``
            POC scopes / max rank for shared POC helpers (Resources/Sponsors).
        - (Planned) ``get_sponsor_capability_catalog() -> SponsorCapsDTO``
            Capability taxonomy for Sponsors slice.
        - (Planned) ``get_sponsor_lifecycle_policy() -> SponsorLifecycleDTO``
            Readiness/MOU vocab for Sponsors slice.
        - (Planned) Resource policy helpers
            e.g. availability windows, vendor allow/deny lists, SLA shapes.

  - **Admin contracts** (RBAC/domain guarded; used only by Admin/Devtools):
        - ``list_policies(validate: bool = False)``
        - ``get_policy(key: str, validate: bool = False)``
        - ``preview_policy_update(key: str, new_policy: dict)``
        - ``commit_policy_update(key: str, new_policy: dict, actor_ulid: str)``
      These delegate to ``app.slices.governance.services_admin`` to perform
      JSON Schema validation, atomic writes, and ledger emission when board
      policy changes.

Error model
===========

All public functions raise:

    ``extensions.contracts.errors.ContractError``

for caller-visible failures (bad input, missing policy, validation errors,
downstream contract failures).  Internal exceptions from services are caught
and normalized to ``ContractError`` so callers have a single error type to
handle.

Usage
=====

Runtime code (slices, routes, CLI):

    from app.extensions.contracts import governance_v2

    decision = governance_v2.decide_issue(ctx)
    catalogs = governance_v2.get_role_catalogs()
    poc_cfg  = governance_v2.get_poc_policy()

Admin-only code (policy editor UI / devtools):

    from app.extensions.contracts import governance_v2

    infos = governance_v2.list_policies(validate=True)
    old   = governance_v2.get_policy("policy_issuance", validate=True)
    diff  = governance_v2.preview_policy_update("policy_issuance", new_body)
    res   = governance_v2.commit_policy_update("policy_issuance", new_body, actor_ulid)

All future Governance policy access should follow this pattern.
"""


from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    TypedDict,
)

from flask import current_app

from app.extensions import event_bus
from app.extensions.contracts import customers_v2
from app.extensions.errors import ContractError
from app.lib.chrono import now_iso8601_ms
from app.slices.governance.services import decide_issue
from app.slices.governance.services_admin import (
    commit_update_impl,
    get_policy_impl,
    list_policies_impl,
    preview_update_impl,
)

# bind to live module

__all__ = [
    "IssueDecision",
    "RestrictionContext",
    "decide_issue",
    "get_role_catalogs",
    "get_poc_policy",
    "get_sponsor_capability_policy",
    "get_sponsor_lifecycle_policy",
]

# -----------------
# Policy Paths
# -----------------

AUTH_RBAC_PATH = Path("slices") / "auth" / "data" / "policy_rbac.json"
GOV_DOMAIN_PATH = (
    Path("slices") / "governance" / "data" / "policy_domain.json"
)
POC_POLICY_PATH = Path("slices") / "governance" / "data" / "policy_poc.json"
SPONSOR_CAPS_PATH = (
    Path("slices")
    / "governance"
    / "data"
    / "policy_sponsor_capabilities.json"
)
SPONSOR_LIFECYCLE_PATH = (
    Path("slices") / "governance" / "data" / "policy_sponsor_lifecycle.json"
)


# -----------------
# DTO's
# -----------------


class SpendingLimitsDTO(TypedDict):
    staff_limit_cents: int
    admin_over_cents: int


class ConstraintFlagsDTO(TypedDict):
    veteran_only: bool
    homeless_only: bool


class SponsorCapsDTO(TypedDict):
    caps: Dict[str, List[str]]
    all_codes: List[str]


class SponsorLifecycleDTO(TypedDict):
    readiness_allowed: List[str]
    mou_allowed: List[str]


__schema__ = {
    "get_spending_limits": {
        "requires": [],
        "returns_keys": ["staff_limit_cents", "admin_over_cents"],
    },
    "get_constraints": {
        "requires": [],
        "returns_keys": ["veteran_only", "homeless_only"],
    },
}


@dataclass(frozen=True)
class IssueDecision:
    allowed: bool
    reason: str | None
    approver_required: str | None  # e.g., "Treasurer" if over cap
    next_eligible_at_iso: str | None  # if denied by cadence
    limit_window_label: str | None  # e.g., "per_year", "per_quarter"


@dataclass(frozen=True)
class RestrictionContext:
    customer_ulid: str
    sku_code: str
    classification_key: str
    cost_cents: int
    as_of_iso: str
    project_ulid: str | None = None


@dataclass(frozen=True)
class DecisionDTO:
    customer_ulid: str
    is_veteran_verified: bool
    is_homeless_verified: bool
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    # Derived “policy” decisions:
    attention_required: bool  # Tier1_min == 1
    watchlist: bool  # Tier2_min == 1
    eligible_veteran_only: bool  # Veteran gates veteran-only programs
    eligible_homeless_only: bool  # Homeless gates homeless-only programs
    as_of_iso: str


# -----------------
# Role Code & POC
# Policy Mechanisms
# contract shape
# -----------------


# Contract general JSON shape example:
# {
#   "rbac_roles": ["admin","auditor","staff","user"],
#   "domain_roles": ["customer","resource","sponsor","governor","civilian","staff"],
#   "rbac_to_domain": {
#       "admin":    ["governor","staff"],
#       "auditor":  ["staff"],
#       "staff":    ["governor","staff"],
#       "user":     ["staff"]
#   }
# }


def _app_root() -> Path:
    return Path(current_app.root_path)


# -----------------
# Read Policy JSON
# -----------------


def _load_json(path: Path, where: str):
    where = "governance_v2._load_json"
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ContractError(
            code="policy_missing",
            where=where,
            message=f"policy file missing: {path}",
            http_status=503,
            data={"path": str(path)},
        )
    except Exception as e:
        raise ContractError(
            code="policy_read_error",
            where=where,
            message=str(e),
            http_status=503,
            data={"path": str(path)},
        )


# -----------------
# Role Policy Catalog
# -----------------


def get_role_catalogs() -> dict:
    """
    Read the current RBAC and Domain role catalogs from their canonical owners.
    Returns: {"rbac_roles":[...], "domain_roles":[...]}
    """
    where = "governance_v2.get_role_catalogs"
    root = _app_root()

    rbac_policy = _load_json(root / AUTH_RBAC_PATH, where)
    gov_policy = _load_json(root / GOV_DOMAIN_PATH, where)

    rbac_roles = sorted(
        {str(x) for x in (rbac_policy.get("rbac_roles") or [])}
    )
    domain_roles = sorted(
        {str(x) for x in (gov_policy.get("domain_roles") or [])}
    )

    if not rbac_roles:
        where = "governance_v2.get_role_catalogs.rbac_roles"
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="rbac_roles missing or empty",
            http_status=503,
            data={"path": str(root / AUTH_RBAC_PATH)},
        )
    if not domain_roles:
        where = "governance_v2.get_role_catalogs.domain_roles"
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="domain_roles missing or empty",
            http_status=503,
            data={"path": str(root / GOV_DOMAIN_PATH)},
        )

    return {"rbac_roles": rbac_roles, "domain_roles": domain_roles}


# -----------------
# POC policy for both
# Resource & Sponsor
# -----------------
"""
When you later wire JSON Schema validation, keep this function as-is
schema checks are a nice pre-filter, but this contract-level
validation guarantees a clean, normalized DTO for callers.
"""


def get_poc_policy() -> dict:
    """
    Read-only contract for POC linkage constraints.
    Returns: {"poc_scopes":[str,...], "default_scope":str, "max_rank":int}
    Raises ContractError (503) if the policy is missing or invalid.
    """
    where = "governance_v2.get_poc_policy"
    root = _app_root()
    obj = _load_json(root / POC_POLICY_PATH, where)

    # 1) Presence check first (avoid KeyError)
    required = ("poc_scopes", "default_scope", "max_rank")
    if any(k not in obj for k in required):
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="POC policy missing required keys",
            http_status=503,
            data={"required": required, "path": str(root / POC_POLICY_PATH)},
        )

    # 2) Shape / type checks + normalization
    scopes_raw = obj.get("poc_scopes")
    if not isinstance(scopes_raw, list) or not scopes_raw:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="poc_scopes must be a non-empty list",
            http_status=503,
            data={"path": str(root / POC_POLICY_PATH)},
        )
    # normalize to unique strings (sorted for determinism)
    scopes = sorted({str(s) for s in scopes_raw})

    default_scope = str(obj.get("default_scope"))
    try:
        max_rank = int(obj.get("max_rank"))
    except Exception:
        raise ContractError(  # noqa: B904
            code="policy_invalid",
            where=where,
            message="max_rank must be an integer",
            http_status=503,
            data={
                "path": str(root / POC_POLICY_PATH),
                "value": obj.get("max_rank"),
            },
        )

    # Optional bound—matches schema if you adopt it
    if max_rank < 0 or max_rank > 99:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="max_rank must be between 0 and 99",
            http_status=503,
            data={"path": str(root / POC_POLICY_PATH), "value": max_rank},
        )

    # 3) Invariant: default must be a valid scope
    if default_scope not in scopes:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="default_scope must be one of poc_scopes",
            http_status=503,
            data={
                "default_scope": default_scope,
                "poc_scopes": scopes,
                "path": str(root / POC_POLICY_PATH),
            },
        )

    return {
        "poc_scopes": scopes,
        "default_scope": default_scope,
        "max_rank": max_rank,
    }


# -----------------
# Customer Contract API
# -----------------


def get_spending_limits() -> SpendingLimitsDTO:
    return {"staff_limit_cents": 20000, "admin_over_cents": 20000}


def get_constraints() -> ConstraintFlagsDTO:
    return {"veteran_only": False, "homeless_only": False}


def evaluate_customer(
    customer_ulid: str, *, request_id: str, actor_ulid: str | None
) -> DecisionDTO:
    """
    Read-only evaluation. Emits governance.decision_made.
    """
    prof = customers_v2.get_needs_profile(customer_ulid)

    attention_required = prof.tier1_min == 1
    watchlist = prof.tier2_min == 1
    eligible_veteran_only = bool(prof.is_veteran_verified)
    eligible_homeless_only = bool(prof.is_homeless_verified)

    # Emit governance ledger event (PII-free)
    event_bus.emit(
        domain="governance",
        operation="decision_made",
        actor_ulid=actor_ulid,
        target_ulid=customer_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "policy": "core.needs.v1",
            "rules": [
                "veteran_required",
                "homeless_flag",
                "tier1_attention_if_min1",
                "tier2_watchlist_if_min1",
            ],
        },
        changed={
            "decisions": {
                "attention_required": attention_required,
                "watchlist": watchlist,
                "eligible_veteran_only": eligible_veteran_only,
                "eligible_homeless_only": eligible_homeless_only,
            }
        },
    )

    return DecisionDTO(
        customer_ulid=prof.customer_ulid,
        is_veteran_verified=prof.is_veteran_verified,
        is_homeless_verified=prof.is_homeless_verified,
        tier1_min=prof.tier1_min,
        tier2_min=prof.tier2_min,
        tier3_min=prof.tier3_min,
        attention_required=attention_required,
        watchlist=watchlist,
        eligible_veteran_only=eligible_veteran_only,
        eligible_homeless_only=eligible_homeless_only,
        as_of_iso=prof.as_of_iso,
    )


def describe():
    """
    Returns the governance catalogs used by guardrails:
      - domain_roles: list[str]
      - rbac_to_domain: { rbac_role: [domain_role, ...] }
      - calendar_policies: minimal descriptors (no PII)
    """
    from app.slices.governance.services import load_policy_bundle

    bundle = (
        load_policy_bundle()
    )  # reads JSON files under slices/governance/data/
    return {
        "domain_roles": bundle["domain"]["roles"],
        "rbac_to_domain": bundle["domain"]["rbac_to_domain"],
        "calendar": {"blackout": bundle["calendar"]["blackout_summary"]},
    }


# -----------------
# Sponsor Policy DTO's
# -----------------


def get_sponsor_capability_policy() -> SponsorCapsDTO:
    """
    Read-only contract for Sponsor capability taxonomy.

    Returns a normalized DTO:
        {
          "caps": {
              "funding": [ ... ],
              "in_kind": [ ... ],
              "meta": [ ... ]
          },
          "all_codes": [ ... ]  # flattened, sorted unique list
        }

    Raises ContractError (503) if the policy is missing or invalid.
    """
    where = "governance_v2.get_sponsor_capability_policy"
    root = _app_root()
    obj = _load_json(root / SPONSOR_CAPS_PATH, where)

    # Require "caps" top-level mapping
    caps_raw = obj.get("caps")
    if not isinstance(caps_raw, dict) or not caps_raw:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message='"caps" must be a non-empty object',
            http_status=503,
            data={"path": str(root / SPONSOR_CAPS_PATH)},
        )

    normalized: Dict[str, List[str]] = {}
    all_codes_set: set[str] = set()

    for family, codes in caps_raw.items():
        if not isinstance(codes, list) or not codes:
            raise ContractError(
                code="policy_invalid",
                where=where,
                message=f'"caps.{family}" must be a non-empty list',
                http_status=503,
                data={"path": str(root / SPONSOR_CAPS_PATH)},
            )
        # normalize each family to sorted unique strings
        codes_norm = sorted({str(c) for c in codes})
        normalized[str(family)] = codes_norm
        all_codes_set.update(codes_norm)

    if not all_codes_set:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="no capability codes defined",
            http_status=503,
            data={"path": str(root / SPONSOR_CAPS_PATH)},
        )

    return SponsorCapsDTO(
        caps=normalized,
        all_codes=sorted(all_codes_set),
    )


def get_sponsor_lifecycle_policy() -> SponsorLifecycleDTO:
    """
    Read-only contract for Sponsor readiness/MOU lifecycle vocabulary.

    Returns:
        {
          "readiness_allowed": [...],
          "mou_allowed": [...]
        }

    Both lists are normalized to sorted unique strings.

    Raises ContractError (503) if the policy is missing or invalid.
    """
    where = "governance_v2.get_sponsor_lifecycle_policy"
    root = _app_root()
    obj = _load_json(root / SPONSOR_LIFECYCLE_PATH, where)

    readiness = obj.get("readiness_allowed")
    mou = obj.get("mou_allowed")

    if not isinstance(readiness, list) or not readiness:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message='"readiness_allowed" must be a non-empty list',
            http_status=503,
            data={"path": str(root / SPONSOR_LIFECYCLE_PATH)},
        )

    if not isinstance(mou, list) or not mou:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message='"mou_allowed" must be a non-empty list',
            http_status=503,
            data={"path": str(root / SPONSOR_LIFECYCLE_PATH)},
        )

    readiness_norm = sorted({str(x) for x in readiness})
    mou_norm = sorted({str(x) for x in mou})

    return SponsorLifecycleDTO(
        readiness_allowed=readiness_norm,
        mou_allowed=mou_norm,
    )


# -----------------
# Governance Policy
# typed DTOs for
# Admin policy change
# -----------------
"""
Expose pure functions with typed DTOs.
These are the only functions Admin/Devtools/Tests call.
They return only DTOs, never internal models or file paths.

"""
# -----------------
# Typed DTOs
# -----------------


class PolicyIndexItemDTO(TypedDict, total=False):
    key: str
    has_schema: bool
    schema_valid: bool
    schema_errors: List[str]
    domains: List[str]
    focus: str


class PolicyIndexDTO(TypedDict):
    ok: bool
    policies: List[PolicyIndexItemDTO]


class PolicyUpdatePreviewDTO(TypedDict):
    ok: bool
    dry_run: bool
    diff_summary: Dict[str, list]  # added_keys / removed_keys / changed_keys


class PolicyUpdateCommitDTO(TypedDict):
    ok: bool
    dry_run: bool
    diff_summary: Dict[str, list]


# -----------------
# Calls to DTOs
# -----------------


def list_policies(*, validate: bool = False) -> Dict[str, Any]:
    """
    Discover governance policies (PII-free).
    Optionally JSON-Schema validate.
    """
    return list_policies_impl(validate=validate)


def get_policy(*, key: str, validate: bool = False) -> Dict[str, Any]:
    """
    Fetch one policy’s raw JSON (PII-free).
    Optionally JSON-Schema validate.
    """
    return get_policy_impl(key=key, validate=validate)


def preview_policy_update(
    *, key: str, new_policy: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Dry-run: canonicalize + validate + diff, but do not write or emit.
    """
    return preview_update_impl(key=key, new_policy=new_policy)


def commit_policy_update(
    *, key: str, new_policy: Dict[str, Any], actor_ulid: str
) -> Dict[str, Any]:
    """
    Commit: canonicalize + validate, atomic write with backup, and
    emit a single ledger event (PII-free).
    """
    return commit_update_impl(
        key=key, new_policy=new_policy, actor_ulid=actor_ulid
    )
