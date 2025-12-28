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

Admin-only code (policy editor UI):

    infos = governance_v2.list_policies(validate=True)
    old   = governance_v2.get_policy("policy_issuance", validate=True)
    diff  = governance_v2.preview_policy_update("policy_issuance", new_body)
    res   = governance_v2.commit_policy_update(
        "policy_issuance",
        new_body,
        actor_ulid=current_user.ulid,
    )

These admin contracts are intended for the Admin slice UI and for
offline policy management tools (e.g. CLI). Dev-only endpoints may call
them during development but are not part of the production surface.

"""


from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    TypedDict,
)

from flask import current_app

from app.extensions import event_bus
from app.extensions.contracts import customers_v2
from app.extensions.errors import ContractError
from app.lib.chrono import now_iso8601_ms
from app.slices.governance import services as gov_svc
from app.slices.governance import services_budget as svc_budget
from app.slices.governance.services_admin import (
    commit_update_impl,
    get_policy_impl,
    list_policies_impl,
    preview_update_impl,
)

# bind/expose to live module

__all__ = [
    "IssueDecision",
    "RestrictionContext",
    "decide_issue",
    "get_role_catalogs",
    "get_poc_policy",
    "get_sponsor_capability_policy",
    "get_sponsor_lifecycle_policy",
    "get_sponsor_pledge_policy",
    # New budget / spend helpers (runtime-safe)
    "get_budget_position",
    "preview_spend_decision",
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
# ContractError
# -----------------


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    # If we’re already looking at a ContractError, just bubble it up unchanged
    if isinstance(exc, ContractError):
        return exc

    msg = str(exc) or exc.__class__.__name__

    if isinstance(exc, ValueError):
        return ContractError(
            code="bad_argument",
            where=where,
            message=msg,
            http_status=400,
        )
    if isinstance(exc, PermissionError):
        return ContractError(
            code="permission_denied",
            where=where,
            message=msg,
            http_status=403,
        )
    if isinstance(exc, LookupError):
        return ContractError(
            code="not_found",
            where=where,
            message=msg,
            http_status=404,
        )

    # Fallback: unexpected system/runtime error
    return ContractError(
        code="internal_error",
        where=where,
        message="unexpected error in contract; see logs",
        http_status=500,
        data={"exc_type": exc.__class__.__name__},
    )


# -----------------
# Error Check Helpers
# -----------------


def _ok(payload: Mapping[str, Any] | None = None) -> dict:
    return {"ok": True, "data": {} if payload is None else dict(payload)}


def _one(name: str, value: Any) -> dict:
    return {"ok": True, "data": {name: value}}


def _require_str(name: str, value: Optional[str]) -> str:
    if not value or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _require_ulid(name: str, value: Optional[str]) -> str:
    v = _require_str(name, value)
    if len(v) != 26:
        raise ValueError(f"{name} must be a 26-char ULID")
    return v


def _require_int_ge(name: str, value: Any, minval: int = 0) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an int")
    if value < minval:
        raise ValueError(f"{name} must be >= {minval}")
    return value


# -----------------
# DTO's
# -----------------


@dataclass
class DonationIntentDTO:
    sponsor_ulid: str
    amount_cents: int
    fund_archetype_key: Optional[str] = None
    period_label: Optional[str] = None
    source: Optional[str] = None
    prospect_ulid: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class DonationClassificationDTO:
    ok: bool
    reason: str
    fund_archetype_key: str
    journal_flags: List[str]
    reporting_tags: List[str]
    restricted_project_type_keys: List[str]


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


class ProjectBudgetDemandDTO(TypedDict):
    project_ulid: str
    project_title: str
    project_type_key: str | None
    period_label: str | None
    total_expected_cents: int
    monetary_expected_cents: int
    in_kind_expected_cents: int
    by_fund_archetype: Dict[str, int]


class BudgetPositionDTO(TypedDict):
    """
    PII-free budget position, exposed at the contract boundary.

    Mirrors governance.services_budget.BudgetPosition, but uses only
    primitives so it can be easily JSON-encoded and consumed by any
    slice, CLI, or UI.
    """

    fund_archetype_key: str
    project_type_key: str | None
    period_label: str | None
    cap_cents: int | None
    spent_cents: int | None
    remaining_cents: int | None


class SpendDecisionDTO(TypedDict):
    """
    PII-free decision about a proposed spend.

    Callers (typically Finance, possibly Calendar) can use this DTO
    to drive UI and control flow:

      * ok: overall allow/deny signal.
      * requires_override: whether an admin override is required.
      * reason: short machine-/human-readable code ('ok',
        'over_budget_cap', etc.).
    """

    ok: bool
    reason: str

    fund_archetype_key: str
    project_type_key: str | None
    period_label: str | None

    amount_cents: int
    cap_cents: int | None
    spent_cents: int | None
    remaining_cents: int | None
    requires_override: bool


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


class IssueDecision(TypedDict):
    allowed: bool
    reason: str | None
    approver_required: str | None  # e.g., "Treasurer" if over cap
    next_eligible_at_iso: str | None  # if denied by cadence
    limit_window_label: str | None  # e.g., "per_year", "per_quarter"


class RestrictionContext(TypedDict):
    customer_ulid: str
    sku_code: str
    classification_key: str
    cost_cents: int
    as_of_iso: str
    project_ulid: str | None = None


class DecisionDTO(TypedDict):
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


class ResourceCapsPolicy:
    note_max: int
    classifications: Dict[str, List[str]]

    @property
    def all_codes(self) -> Set[str]:
        # e.g. {"basic_needs.food_pantry", "housing.rent_assistance", ...}
        out: Set[str] = set()
        for domain, codes in self.classifications.items():
            for code in codes:
                out.add(f"{domain}.{code}")
        return out


# -----------------
# Band Aid
# -----------------


def decide_issue(*args, **kwargs):
    # Lazy import to avoid circular import:
    # governance.services -> logistics_v2 -> issuance_services -> governance_v2 -> governance.services
    from app.slices.governance.services import decide_issue as _decide_issue

    return _decide_issue(*args, **kwargs)


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
# Resource Policy DTO's
# -----------------


def get_resource_capabilities_policy() -> ResourceCapsPolicy:
    """
    Board policy: resource capabilities & taxonomy.
    Backed by policy_resource_capabilities.json (or DB equivalent later).
    """
    data = gov_svc.svc_get_policy_value("resource", "capabilities")
    return ResourceCapsPolicy(
        note_max=int(data["note_max"]),
        classifications={
            k: list(v) for k, v in data["classifications"].items()
        },
    )


def get_resource_lifecycle_policy() -> dict:
    """
    Board policy: resource readiness + MOU status vocab.
    Backed by policy_resource_lifecycle.json.
    """
    return gov_svc.svc_get_policy_value("resource", "lifecycle")


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


def get_sponsor_pledge_policy() -> dict:
    """
    Read-only contract for Sponsor pledge policy.

    This is intentionally thin: it delegates to the Governance services
    helper and returns the raw, PII-free policy dict. Callers (Sponsors
    slice, Admin UI) are responsible for interpreting specific keys.

    Backed by the policy_sponsor_pledge.json family (file or DB), via
    governance.services.svc_get_policy_value("sponsor", "pledge").
    """
    try:
        return gov_svc.svc_get_policy_value("sponsor", "pledge")
    except Exception as e:  # noqa: B902
        # Normalize to ContractError so callers see a single error type
        raise ContractError(
            code="policy_read_error",
            where="governance_v2.get_sponsor_pledge_policy",
            message=str(e),
            http_status=503,
            data={"family": "sponsor", "key": "pledge"},
        ) from e


# -----------------
# Governance Policy
# typed DTOs for
# Admin policy change
# -----------------
"""
Expose pure functions with typed DTOs.
These are the only functions the Admin slice UI and tests should call
for Governance policy editing. They return only DTOs, never internal
models or file paths.
"""
# -----------------
# Typed Policy DTOs
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
# Calls to Policy DTOs
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


# -----------------
# Budget Services
# functions
# -----------------


def evaluate_donation(
    *,
    sponsor_ulid: str,
    amount_cents: int,
    fund_archetype_key: Optional[str] = None,
    period_label: Optional[str] = None,
    source: Optional[str] = None,
    prospect_ulid: Optional[str] = None,
    notes: Optional[str] = None,
) -> DonationClassificationDTO:
    """
    Contract entry point: evaluate an inbound donation against Governance policy.

    This function does **not** write to Finance or Sponsors. It performs
    shape checks, delegates to governance.services_budget.classify_donation_intent,
    and returns a DonationClassificationDTO.

    Arguments:
        sponsor_ulid:
            ULID of the sponsor (from Sponsors slice).
        amount_cents:
            Proposed donation amount in cents (> 0).
        fund_archetype_key:
            Optional fund archetype hint; if omitted, a default such as
            'general_unrestricted' may be applied according to policy.
        period_label:
            Optional period/budget label (e.g. 'FY2025') for future budget
            semantics. Currently unused in MVP.
        source:
            Optional free-text source token (e.g. 'grant:ELKS_FREEDOM').
        prospect_ulid:
            Optional ULID of a Funding Prospect / Pledge in Sponsors slice.
        notes:
            Optional free-text notes for human context.

    Returns:
        DonationClassificationDTO:
            - ok: True if the donation is allowed under current policy.
            - reason: 'ok' or a short denial/explanation string.
            - fund_archetype_key: normalized archetype key.
            - journal_flags: accounting flags to pass into Finance.
            - reporting_tags: tags for grant/reporting purposes.
            - restricted_project_type_keys: hint about allowable project types.

    Raises:
        ContractError:
            - code='bad_argument' when inputs are malformed.
            - code='internal_error' for unexpected failures.
    """
    where = "governance_v2.evaluate_donation"
    try:
        sponsor_ulid = _require_ulid("sponsor_ulid", sponsor_ulid)
        amount_cents = _require_int_ge("amount_cents", amount_cents, minval=1)
        if fund_archetype_key is not None:
            fund_archetype_key = _require_str(
                "fund_archetype_key", fund_archetype_key
            )
        if period_label is not None:
            period_label = _require_str("period_label", period_label)
        if source is not None:
            source = _require_str("source", source)
        if prospect_ulid is not None:
            prospect_ulid = _require_ulid("prospect_ulid", prospect_ulid)
        if notes is not None:
            notes = _require_str("notes", notes)

        intent = svc_budget.DonationIntent(
            sponsor_ulid=sponsor_ulid,
            amount_cents=amount_cents,
            fund_archetype_key=fund_archetype_key,
            period_label=period_label,
            source=source,
            prospect_ulid=prospect_ulid,
            notes=notes,
        )
        classification = svc_budget.classify_donation_intent(intent)

        return DonationClassificationDTO(
            ok=classification.ok,
            reason=classification.reason,
            fund_archetype_key=classification.fund_archetype_key,
            journal_flags=list(classification.journal_flags),
            reporting_tags=list(classification.reporting_tags),
            restricted_project_type_keys=list(
                classification.restricted_project_type_keys
            ),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc)


def get_budget_demands_for_period(
    *, period_label: str
) -> List[ProjectBudgetDemandDTO]:
    """
    Contract entry point: compute planned budget demands for a period.

    This is a *read-only* governance view that aggregates Calendar
    projects and their ProjectFundingPlan rows into project-level
    demand objects. It does not talk to Finance or Sponsors; it is
    purely a planning/forecasting surface.

    Args:
        period_label:
            Period/budget label understood by Calendar and Governance,
            e.g. '2026', 'FY2026', etc.

    Returns:
        List[ProjectBudgetDemandDTO]:
            One entry per project, including total planned amount and
            breakdown by fund_archetype_key.

    Raises:
        ContractError:
            - code='bad_argument' if period_label is blank.
            - code='internal_error' if underlying services fail or if
              Calendar has not yet wired the needed contract functions.
    """
    where = "governance_v2.get_budget_demands_for_period"
    try:
        period_label = _require_str("period_label", period_label)
        demands = svc_budget.compute_budget_demands_for_period(period_label)
        out: List[ProjectBudgetDemandDTO] = []

        for d in demands:
            out.append(
                ProjectBudgetDemandDTO(
                    project_ulid=d.project_ulid,
                    project_title=d.project_title,
                    project_type_key=d.project_type_key,
                    period_label=d.period_label,
                    total_expected_cents=d.total_expected_cents,
                    monetary_expected_cents=d.monetary_expected_cents,
                    in_kind_expected_cents=d.in_kind_expected_cents,
                    by_fund_archetype=dict(d.by_fund_archetype),
                )
            )

        return out
    except Exception as exc:  # noqa: BLE001 - boundary wrapper
        raise _as_contract_error(where, exc)


def get_budget_position(
    *,
    fund_archetype_key: str,
    project_type_key: str | None = None,
    period_label: str | None = None,
    current_spent_cents: int | None = None,
) -> BudgetPositionDTO:
    """
    Contract entry point: summarize the budget position for a specific
    fund / project_type / period combination.

    MVP behaviour:

      * Performs shape checks on the arguments.
      * Delegates to governance.services_budget.compute_budget_position.
      * Returns a BudgetPositionDTO.

    This function is **read-only** and has no side-effects. Callers
    should supply `current_spent_cents` based on their own Finance
    queries; a future revision may compute this using Finance contracts.
    """
    where = "governance_v2.get_budget_position"
    try:
        fund_archetype_key = _require_str(
            "fund_archetype_key", fund_archetype_key
        )
        if project_type_key is not None:
            project_type_key = _require_str(
                "project_type_key", project_type_key
            )
        if period_label is not None:
            period_label = _require_str("period_label", period_label)
        if current_spent_cents is not None:
            current_spent_cents = _require_int_ge(
                "current_spent_cents", current_spent_cents, minval=0
            )

        pos = svc_budget.compute_budget_position(
            fund_archetype_key=fund_archetype_key,
            project_type_key=project_type_key,
            period_label=period_label,
            current_spent_cents=current_spent_cents,
        )

        return BudgetPositionDTO(
            fund_archetype_key=pos.fund_archetype_key,
            project_type_key=pos.project_type_key,
            period_label=pos.period_label,
            cap_cents=pos.cap_cents,
            spent_cents=pos.spent_cents,
            remaining_cents=pos.remaining_cents,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc)


def preview_spend_decision(
    *,
    fund_archetype_key: str,
    project_type_key: str | None,
    amount_cents: int,
    period_label: str | None = None,
    current_spent_cents: int | None = None,
) -> SpendDecisionDTO:
    """
    Contract entry point: ask Governance whether a proposed spend fits
    within budget policy for a given fund/project/period.

    This function is intended to be called *before* any use of
    ``finance_v2.log_expense(...)`` so that policy decisions and Journal
    writes remain cleanly separated.

    MVP behaviour:

      * Validates argument shapes (strings, ULIDs, ints >= 0).
      * Constructs a SpendIntent and delegates to
        governance.services_budget.preview_spend_decision.
      * Returns a SpendDecisionDTO with a simple allow/deny + “requires
        override” signal.

    This function does **not** talk to Finance. Callers (usually the
    Finance slice) are expected to pass `current_spent_cents` based on
    their own view of Journal / balances. Future revisions may compute
    that value internally.
    """
    where = "governance_v2.preview_spend_decision"
    try:
        fund_archetype_key = _require_str(
            "fund_archetype_key", fund_archetype_key
        )
        if project_type_key is not None:
            project_type_key = _require_str(
                "project_type_key", project_type_key
            )
        if period_label is not None:
            period_label = _require_str("period_label", period_label)

        amount_cents = _require_int_ge("amount_cents", amount_cents, minval=1)
        if current_spent_cents is not None:
            current_spent_cents = _require_int_ge(
                "current_spent_cents", current_spent_cents, minval=0
            )

        intent = svc_budget.SpendIntent(
            fund_archetype_key=fund_archetype_key,
            project_type_key=project_type_key,
            period_label=period_label,
            amount_cents=amount_cents,
        )

        decision = svc_budget.preview_spend_decision(
            intent, current_spent_cents=current_spent_cents
        )

        return SpendDecisionDTO(
            ok=decision.ok,
            reason=decision.reason,
            fund_archetype_key=decision.fund_archetype_key,
            project_type_key=decision.project_type_key,
            period_label=decision.period_label,
            amount_cents=decision.amount_cents,
            cap_cents=decision.cap_cents,
            spent_cents=decision.spent_cents,
            remaining_cents=decision.remaining_cents,
            requires_override=decision.requires_override,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc)
