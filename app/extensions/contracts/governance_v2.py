# app/extensions/contracts/governance_v2.py

"""
VCDB v2 — Governance contract (v2)

"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    NotRequired,
    Required,
    TypedDict,
)

from flask import current_app

from app.extensions import event_bus
from app.extensions.errors import ContractError
from app.extensions.policies import load_governance_policy
from app.lib.chrono import now_iso8601_ms
from app.slices.governance import services as gov_svc
from app.slices.governance import services_budget as svc_budget
from app.slices.governance.services_admin import (
    commit_update_impl,
    get_policy_impl,
    list_policies_impl,
    preview_update_impl,
)
from app.slices.governance.services_finance_taxonomy import (
    apply_fund_defaults as _apply_fund_defaults,
)
from app.slices.governance.services_finance_taxonomy import (
    get_finance_taxonomy as _get_finance_taxonomy,
)
from app.slices.governance.services_finance_taxonomy import (
    get_fund_key as _get_fund_key,
)
from app.slices.governance.services_finance_taxonomy import (
    get_taxonomy_label as _get_taxonomy_label,
)
from app.slices.governance.services_finance_taxonomy import (
    normalize_restriction_keys as _normalize_restriction_keys,
)
from app.slices.governance.services_finance_taxonomy import (
    validate_semantic_keys as _validate_semantic_keys,
)
from app.slices.governance.services_funding_decisions import (
    preview_funding_decision as svc_preview_funding_decision,
)

# Governance slice service (pure evaluator; no DB)
from app.slices.governance.services_funding_decisions import (
    preview_ops_float as svc_preview_ops_float,
)

# bind/expose to live module

__all__ = [
    "IssueDecision",
    "RestrictionContext",
    "decide_issue",
    "get_role_catalogs",
    "list_domain_role_codes",
    "list_entity_role_codes",
    "get_poc_policy",
    "get_customer_veteran_verification_methods",
    "get_sponsor_capability_policy",
    "get_sponsor_pledge_policy",
    # New budget / spend helpers (runtime-safe)
    "get_budget_position",
    "preview_spend_decision",
    # Lifecycle policy
    "get_resource_lifecycle_policy",
    "get_sponsor_lifecycle_policy",
]


def decide_issue(*args, **kwargs):
    raise RuntimeError(
        "DEPRECATED: Issuance decisioning moved to Logistics. "
        "Use app.slices.logistics.issuance_services.decide_issue (local) "
        "or app.extensions.contracts.logistics_v2.decide_issue (cross-slice)."
    )


# -----------------
# Policy Paths
# -----------------

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
DEFAULT_CAP_NOTE_MAX = 120  # belt & suspenders


# -----------------
# ContractError
# -----------------


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    # If we’re already looking at a ContractError, just bubble it up unchanged
    """
    ContractError mapping for governance_v2.

    - ValueError => 400 bad_argument
    - LookupError => 404 not_found
    - PermissionError => 403 permission_denied
    - ContractError passes through
    - everything else => 500 internal
    """
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


def _one(name: str, value: Any) -> dict:
    return {"ok": True, "data": {name: value}}


def _require_str(name: str, value: str | None) -> str:
    if not value or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _require_ulid(name: str, value: str | None) -> str:
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
# new paradigm
# -----------------


@dataclass(frozen=True)
class FundingDecisionDTO:
    allowed: bool

    # Ordered, preferred-to-least list of eligible fund keys
    eligible_fund_keys: tuple[str, ...] = ()

    # If caller already picked a fund_key, Governance can confirm it
    selected_fund_key: str | None = None

    # Approval requirements (role names, e.g. treasurer)
    required_approvals: tuple[str, ...] = ()

    # Stable, machine-friendly reasons for UI/tests/debug
    reason_codes: tuple[str, ...] = ()

    # Debug trace (rule ids that matched)
    matched_rule_ids: tuple[str, ...] = ()

    # Deterministic fingerprint (stable hash of request + matches)
    decision_fingerprint: str = ""


@dataclass(frozen=True)
class FundingDecisionRequestDTO:
    # reserve|encumber|spend|receive|ops_allocate|ops_repay|ops_forgive
    op: str
    amount_cents: int

    # Context (traceability)
    funding_demand_ulid: str | None = None
    project_ulid: str | None = None

    # Semantic keys (Governance taxonomy)
    spending_class: str | None = None
    income_kind: str | None = None
    expense_kind: str | None = None
    source_profile_key: str | None = None
    restriction_keys: tuple[str, ...] = ()

    # Optional constraints/hints from callers
    ops_support_planned: bool | None = None
    demand_eligible_fund_keys: tuple[str, ...] = ()
    tag_any: tuple[str, ...] = ()

    # Optional: caller picks one; Governance confirms eligibility + approvals
    selected_fund_key: str | None = None

    # Actor roles for authority checks
    actor_rbac_roles: tuple[str, ...] = ()
    actor_domain_roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpsFloatDecisionRequestDTO:
    support_mode: str
    amount_cents: int
    fund_key: str
    source_funding_demand_ulid: str
    source_project_ulid: str | None
    dest_funding_demand_ulid: str
    dest_project_ulid: str | None
    action: str = "allocate"
    spending_class: str | None = None
    tag_any: tuple[str, ...] = ()
    dest_eligible_fund_keys: tuple[str, ...] = ()
    ops_support_planned: bool | None = None
    actor_rbac_roles: tuple[str, ...] = ()
    actor_domain_roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeyLabelDTO:
    key: str
    label: str


@dataclass(frozen=True)
class FundKeyDTO:
    key: str
    label: str
    archetype: str
    default_restriction_keys: tuple[str, ...]


@dataclass(frozen=True)
class FinanceTaxonomyDTO:
    version: int
    fund_keys: tuple[FundKeyDTO, ...]
    restriction_keys: tuple[KeyLabelDTO, ...]
    income_kinds: tuple[KeyLabelDTO, ...]
    expense_kinds: tuple[KeyLabelDTO, ...]
    spending_classes: tuple[KeyLabelDTO, ...]


@dataclass(frozen=True)
class SemanticValidationResultDTO:
    ok: bool
    errors: tuple[str, ...]
    unknown_keys: tuple[str, ...]


# -----------------
# Older DTO's
# -----------------


class DonationIntentDTO:
    sponsor_ulid: str
    amount_cents: int
    fund_archetype_key: str | None = None
    period_label: str | None = None
    source: str | None = None
    prospect_ulid: str | None = None
    notes: str | None = None


class DonationClassificationDTO:
    ok: bool
    reason: str
    fund_archetype_key: str
    journal_flags: list[str]
    reporting_tags: list[str]
    restricted_project_type_keys: list[str]


class SpendingLimitsDTO(TypedDict):
    staff_limit_cents: int
    admin_over_cents: int


class ConstraintFlagsDTO(TypedDict):
    veteran_only: bool
    homeless_only: bool


class ProjectBudgetDemandDTO(TypedDict):
    project_ulid: str
    project_title: str
    project_type_key: str | None
    period_label: str | None
    total_expected_cents: int
    monetary_expected_cents: int
    in_kind_expected_cents: int
    by_fund_archetype: dict[str, int]


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


class LifecyclePolicyDTO(TypedDict):
    readiness_allowed: Required[list[str]]
    mou_allowed: Required[list[str]]

    readiness_default: NotRequired[str]
    mou_default: NotRequired[str]
    transitions: NotRequired[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CapabilityPolicyDTO:
    note_max: int
    all_codes: list[str]  # ["domain.key", ...]
    by_domain: dict[str, list[str]]  # {"domain": ["key", ...], ...}


class ResourceCapsPolicy:
    note_max: int
    all_codes: list[str]
    by_domain: dict[str, list[str]]


class SponsorCapsDTO(TypedDict):
    note_max: int
    all_codes: list[str]
    by_domain: dict[str, list[str]]


# -----------------
# Finance Functions
# (new paradigm)
# -----------------
"""
How you’ll actually use these “bones” right away
Calendar: build a Funding Demand form

Populate dropdowns:

gov.get_finance_taxonomy().fund_keys

gov.get_finance_taxonomy().spending_classes

Validate:

gov.validate_semantic_keys(...)

When selecting a fund:

show defaults: gov.apply_fund_defaults(fund_key=..., restriction_keys=...)

Sponsors: donation intake form

Income kind dropdown: income_kinds

Restrictions checklist: restriction_keys

Validate on submit.

Finance: posting

Finance consumes the semantic keys (kinds/fund_key/restrictions)

Finance does not call Governance at post time except perhaps to validate keys
(optional).
"""


def preview_funding_decision(
    req: FundingDecisionRequestDTO,
) -> FundingDecisionDTO:
    """
    Read-only governance decision preview.

    Intended usage pattern:
      1) Call WITHOUT selected_fund_key to get eligible_fund_keys.
      2) Caller chooses selected_fund_key.
      3) Call WITH selected_fund_key to get approvals/deny + fingerprint.

    Governance emits no Ledger events here. Caller can store decision_fingerprint
    as a "decision ref" for later encumber/spend calls into Finance.
    """
    where = "governance_v2.preview_funding_decision"
    try:
        raw_req = {
            "op": req.op,
            "amount_cents": req.amount_cents,
            "funding_demand_ulid": req.funding_demand_ulid,
            "project_ulid": req.project_ulid,
            "spending_class": req.spending_class,
            "income_kind": req.income_kind,
            "expense_kind": req.expense_kind,
            "source_profile_key": req.source_profile_key,
            "restriction_keys": req.restriction_keys,
            "ops_support_planned": req.ops_support_planned,
            "demand_eligible_fund_keys": req.demand_eligible_fund_keys,
            "tag_any": req.tag_any,
            "selected_fund_key": req.selected_fund_key,
            "actor_rbac_roles": req.actor_rbac_roles,
            "actor_domain_roles": req.actor_domain_roles,
        }

        raw_out = svc_preview_funding_decision(raw_req)

        return FundingDecisionDTO(
            allowed=bool(raw_out.get("allowed")),
            eligible_fund_keys=tuple(raw_out.get("eligible_fund_keys") or ()),
            selected_fund_key=raw_out.get("selected_fund_key"),
            required_approvals=tuple(raw_out.get("required_approvals") or ()),
            reason_codes=tuple(raw_out.get("reason_codes") or ()),
            matched_rule_ids=tuple(raw_out.get("matched_rule_ids") or ()),
            decision_fingerprint=str(
                raw_out.get("decision_fingerprint") or ""
            ),
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def get_finance_taxonomy() -> FinanceTaxonomyDTO:
    """
    Read-only Governance taxonomy for Finance-related keys.
    Safe for UI dropdowns in any slice.
    """
    where = "governance_v2.get_finance_taxonomy"
    try:
        t = _get_finance_taxonomy()
        return FinanceTaxonomyDTO(
            version=t.version,
            fund_keys=t.fund_keys,
            restriction_keys=t.restriction_keys,
            income_kinds=t.income_kinds,
            expense_kinds=t.expense_kinds,
            spending_classes=t.spending_classes,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def get_fund_key(fund_key: str) -> FundKeyDTO:
    where = "governance_v2.get_fund_key"
    try:
        x = _get_fund_key(fund_key)
        return FundKeyDTO(
            key=x.key,
            label=x.label,
            archetype=x.archetype,
            default_restriction_keys=x.default_restriction_keys,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def get_taxonomy_label(group: str, key: str) -> KeyLabelDTO:
    where = "governance_v2.get_taxonomy_label"
    try:
        x = _get_taxonomy_label(group, key)
        return KeyLabelDTO(key=x.key, label=x.label)
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def validate_semantic_keys(
    *,
    fund_key: str | None = None,
    restriction_keys: tuple[str, ...] = (),
    income_kind: str | None = None,
    expense_kind: str | None = None,
    spending_class: str | None = None,
    demand_eligible_fund_keys: tuple[str, ...] = (),
) -> SemanticValidationResultDTO:
    where = "governance_v2.validate_semantic_keys"
    try:
        r = _validate_semantic_keys(
            fund_key=fund_key,
            restriction_keys=restriction_keys,
            income_kind=income_kind,
            expense_kind=expense_kind,
            spending_classes=spending_class,
            demand_eligible_fund_keys=demand_eligible_fund_keys,
        )
        return SemanticValidationResultDTO(
            ok=r.ok,
            errors=r.errors,
            unknown_keys=r.unknown_keys,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def normalize_restriction_keys(
    restriction_keys: tuple[str, ...] = (),
) -> tuple[str, ...]:
    where = "governance_v2.normalize_restriction_keys"
    try:
        return _normalize_restriction_keys(restriction_keys)
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


def apply_fund_defaults(
    *,
    fund_key: str,
    restriction_keys: tuple[str, ...] = (),
) -> tuple[str, ...]:
    where = "governance_v2.apply_fund_defaults"
    try:
        return _apply_fund_defaults(
            fund_key=fund_key,
            restriction_keys=restriction_keys,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


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
    except FileNotFoundError as e:
        raise ContractError(
            code="policy_missing",
            where=where,
            message=f"policy file missing: {path}",
            http_status=503,
            data={"path": str(path)},
        ) from e
    except Exception as e:
        raise ContractError(
            code="policy_read_error",
            where=where,
            message=str(e),
            http_status=503,
            data={"path": str(path)},
        ) from e


# -----------------
# Role Policy Catalog
# -----------------

# TODO:
"""
current policy_entity_roles.json (or just the
assignment_rules section), to sketch the exact cross-check logic that
should live in your policy-health CLI so this never regresses.
"""


def get_role_catalogs() -> dict:
    """
    Canonical domain role catalog lives in Governance policy: policy_entity_roles.json.

    Returns: {"domain_roles":[...]}
    """
    where = "governance_v2.get_role_catalogs"
    from app.extensions.policies import load_governance_policy

    doc = load_governance_policy("entity_roles")

    domain_roles = sorted({str(x) for x in (doc.get("domain_roles") or [])})
    if not domain_roles:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="entity_roles.domain_roles is empty",
            http_status=503,
            data={},
        )

    return {"domain_roles": domain_roles}


def _roles_dict() -> dict[str, Any]:
    """
    Return the canonical roles structure (domain).

    This is the single internal accessor so other helpers can remain stable
    even if the storage shape changes later.
    """
    return get_role_catalogs()


def list_domain_role_codes() -> list[str]:
    roles = _roles_dict()
    return [str(x) for x in (roles.get("domain_roles") or [])]


def list_entity_role_codes() -> list[str]:
    domain_codes = list_domain_role_codes()
    allow = {"customer", "resource", "sponsor"}
    out = [c for c in domain_codes if c in allow]
    return out or domain_codes


def get_role_assignment_rules() -> dict:
    """
    Returns the governance rules mapping RBAC→assignable domain roles.
    Auth owns the RBAC catalog; governance owns the mapping policy.
    """
    from app.extensions.policies import load_governance_policy

    doc = load_governance_policy("entity_roles")
    rules = doc.get("assignment_rules") or {}
    return rules


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

    # Load via governance policy catalog (policy_governance_index.json).
    # This locates policy_poc.json by policy_key="poc".
    try:
        from app.extensions.policies import load_governance_policy

        obj = load_governance_policy("poc") or {}
    except KeyError as e:
        # policy_key not present in policy_governance_index.json
        raise ContractError(
            code="policy_missing",
            where=where,
            message="Unknown governance policy_key: 'poc' (add to policy_governance_index.json)",
            http_status=503,
            data={"policy_key": "poc"},
        ) from e
    except FileNotFoundError as e:
        # manifest entry exists, but file missing/unreadable/invalid JSON
        raise ContractError(
            code="policy_missing",
            where=where,
            message=str(e),
            http_status=503,
            data={"policy_key": "poc"},
        ) from e
    except Exception as e:
        raise ContractError(
            code="policy_read_error",
            where=where,
            message=str(e),
            http_status=503,
            data={"policy_key": "poc"},
        ) from e

    # 1) Presence check first (avoid KeyError)
    required = ("poc_scopes", "default_scope", "max_rank")
    if any(k not in obj for k in required):
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="POC policy missing required keys",
            http_status=503,
            data={"policy_key": "poc", "required": required},
        )

    # 2) Shape / type checks + normalization
    scopes_raw = obj.get("poc_scopes")
    if not isinstance(scopes_raw, list) or not scopes_raw:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="poc_scopes must be a non-empty list",
            http_status=503,
            data={"policy_key": "poc"},
        )

    # normalize to unique strings (sorted for determinism)
    scopes = sorted({str(s) for s in scopes_raw})

    default_scope = str(obj.get("default_scope"))
    try:
        max_rank = int(obj.get("max_rank"))
    except Exception as e:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="max_rank must be an integer",
            http_status=503,
            data={"policy_key": "poc", "value": obj.get("max_rank")},
        ) from e

    if max_rank < 0 or max_rank > 99:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="max_rank must be between 0 and 99",
            http_status=503,
            data={"policy_key": "poc", "value": max_rank},
        )

    # 3) Invariant: default must be a valid scope
    if default_scope not in scopes:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="default_scope must be one of poc_scopes",
            http_status=503,
            data={
                "policy_key": "poc",
                "default_scope": default_scope,
                "poc_scopes": scopes,
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


def get_customer_veteran_verification_methods() -> list[str]:
    """
    Read-only contract for the allowed customer veteran verification methods.

    Canonical source: governance policy_key="customer" (policy_customer.json):
        customer.veteran_verification.methods: [str, ...]

    Returns:
        Sorted, de-duped list[str] of allowed methods.

    Raises:
        ContractError (503) if the policy is missing or invalid.
    """
    where = "governance_v2.get_customer_veteran_verification_methods"

    # Load via governance policy catalog (policy_governance_index.json).
    try:
        obj = load_governance_policy("customer") or {}
    except KeyError as e:
        raise ContractError(
            code="policy_missing",
            where=where,
            message="Unknown governance policy_key: 'customer' (add to policy_governance_index.json)",
            http_status=503,
            data={"policy_key": "customer"},
        ) from e
    except FileNotFoundError as e:
        raise ContractError(
            code="policy_missing",
            where=where,
            message=str(e),
            http_status=503,
            data={"policy_key": "customer"},
        ) from e
    except Exception as e:
        raise ContractError(
            code="policy_read_error",
            where=where,
            message=str(e),
            http_status=503,
            data={"policy_key": "customer"},
        ) from e

    vv = obj.get("veteran_verification") or {}
    methods_raw = vv.get("methods")

    if not isinstance(methods_raw, list) or not methods_raw:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="customer.veteran_verification.methods must be a non-empty list",
            http_status=503,
            data={"policy_key": "customer"},
        )

    methods = sorted({str(m).strip() for m in methods_raw if str(m).strip()})
    if not methods:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="customer.veteran_verification.methods produced no usable strings",
            http_status=503,
            data={"policy_key": "customer"},
        )

    return methods


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
    from app.extensions.contracts import customers_v2

    cues = customers_v2.get_customer_cues(customer_ulid)

    # Prefer pre-derived cues flags when present.
    attention_required = bool(getattr(cues, "flag_tier1_immediate", False))
    watchlist = bool(getattr(cues, "watchlist", False))
    eligible_veteran_only = bool(getattr(cues, "is_veteran_verified", False))
    eligible_homeless_only = bool(
        getattr(cues, "is_homeless_verified", False)
    )

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
        customer_ulid=cues.customer_ulid,
        is_veteran_verified=cues.is_veteran_verified,
        is_homeless_verified=cues.is_homeless_verified,
        tier1_min=cues.tier1_min,
        tier2_min=cues.tier2_min,
        tier3_min=cues.tier3_min,
        attention_required=attention_required,
        watchlist=watchlist,
        eligible_veteran_only=eligible_veteran_only,
        eligible_homeless_only=eligible_homeless_only,
        as_of_iso=cues.as_of_iso,
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
# normalizer for
# Resource & Sponsor
# capabilities
# so they send uniform
# data package via
# Policy DTO's
# -----------------


def _normalize_by_domain(raw: object, *, where: str) -> dict[str, list[str]]:
    if not isinstance(raw, dict) or not raw:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="by_domain must be a non-empty object",
            http_status=503,
        )

    out: dict[str, list[str]] = {}
    for dom, codes in raw.items():
        dom_s = str(dom or "").strip()
        if not dom_s:
            continue

        if codes is None:
            codes_list: list[object] = []
        elif isinstance(codes, list):
            codes_list = codes
        else:
            raise ContractError(
                code="policy_invalid",
                where=where,
                message=f'by_domain["{dom_s}"] must be a list',
                http_status=503,
                data={"domain": dom_s},
            )

        norm_codes = sorted(
            {str(c).strip() for c in codes_list if str(c).strip()}
        )
        out[dom_s] = norm_codes

    if not out:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="by_domain produced no usable domains/codes",
            http_status=503,
        )
    return out


def _build_all_codes(by_domain: dict[str, list[str]]) -> list[str]:
    # Stable + deterministic: domain then code, de-duped
    out: list[str] = []
    for dom in sorted(by_domain.keys()):
        for code in by_domain[dom]:
            out.append(f"{dom}.{code}")
    return out


# -----------------
# Resource Policy DTO's
# -----------------


def get_resource_capabilities_policy() -> CapabilityPolicyDTO:
    where = "governance_v2.get_resource_capabilities_policy"
    doc = load_governance_policy("service_taxonomy")

    caps = doc.get("classifications", {}).get("resource_capabilities", {})
    raw_by_domain = caps.get("by_domain")

    by_domain = _normalize_by_domain(raw_by_domain, where=where)
    note_max = int(caps.get("note_max", DEFAULT_CAP_NOTE_MAX))

    return CapabilityPolicyDTO(
        note_max=note_max,
        all_codes=_build_all_codes(by_domain),
        by_domain=by_domain,
    )


# -----------------
# Sponsor Policy DTO's
# -----------------


def get_sponsor_capability_policy() -> CapabilityPolicyDTO:
    where = "governance_v2.get_sponsor_capability_policy"
    doc = load_governance_policy("service_taxonomy")

    caps = doc.get("classifications", {}).get("sponsor_capabilities", {})
    domains = caps.get("domains")
    meta = caps.get("meta") or {}

    if not isinstance(domains, list) or not domains:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="sponsor_capabilities.domains must be a non-empty list",
            http_status=503,
            data={"policy_key": "service_taxonomy"},
        )

    by_domain: dict[str, list[str]] = {}

    for d in domains:
        if not isinstance(d, dict):
            continue

        dom = str(d.get("code") or "").strip()
        keys = d.get("keys")

        if not dom:
            raise ContractError(
                code="policy_invalid",
                where=where,
                message="each sponsor domain must have a non-empty code",
                http_status=503,
                data={"policy_key": "service_taxonomy"},
            )
        if not isinstance(keys, list) or not keys:
            raise ContractError(
                code="policy_invalid",
                where=where,
                message=f'sponsor domain "{dom}" must have non-empty keys list',
                http_status=503,
                data={"policy_key": "service_taxonomy", "domain": dom},
            )

        codes: set[str] = set()
        for k in keys:
            if isinstance(k, dict):
                code = str(k.get("code") or "").strip()
                if code:
                    codes.add(code)

        if not codes:
            raise ContractError(
                code="policy_invalid",
                where=where,
                message=f'sponsor domain "{dom}" keys must contain code fields',
                http_status=503,
                data={"policy_key": "service_taxonomy", "domain": dom},
            )

        by_domain[dom] = sorted(codes)

    # Optional: ensure unclassified_key (meta.unclassified) is included
    unclassified = meta.get("unclassified_key")
    if isinstance(unclassified, str) and "." in unclassified:
        u_dom, u_key = unclassified.split(".", 1)
        u_dom = u_dom.strip()
        u_key = u_key.strip()
        if u_dom and u_key:
            by_domain.setdefault(u_dom, [])
            if u_key not in by_domain[u_dom]:
                by_domain[u_dom].append(u_key)
                by_domain[u_dom] = sorted(set(by_domain[u_dom]))

    if not by_domain:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message="sponsor_capabilities produced empty by_domain",
            http_status=503,
            data={"policy_key": "service_taxonomy"},
        )

    note_max = int(caps.get("note_max", DEFAULT_CAP_NOTE_MAX))

    return CapabilityPolicyDTO(
        note_max=note_max,
        all_codes=_build_all_codes(by_domain),
        by_domain=by_domain,
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
    except Exception as e:  # noqa: BLE001
        # Normalize to ContractError so callers see a single error type
        raise ContractError(
            code="policy_read_error",
            where="governance_v2.get_sponsor_pledge_policy",
            message=str(e),
            http_status=503,
            data={"family": "sponsor", "key": "pledge"},
        ) from e


# -----------------
# Lifecycle Policy
# Resource & Sponsor
# -----------------


def _dedupe_preserve_order(items: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        s = str(x)
        if s not in seen:
            out.append(s)
            seen.add(s)
    return out


def _load_lifecycle_doc() -> dict:
    where = "governance_v2._load_lifecycle_doc"
    doc = load_governance_policy("lifecycle")  # <- canonical owner
    machines = doc.get("machines")
    if not isinstance(machines, dict) or not machines:
        raise ContractError(
            code="policy_invalid",
            where=where,
            message='policy "lifecycle" missing required object: machines',
            http_status=503,
            data={"policy_key": "lifecycle"},
        )
    return machines


def _load_lifecycle_policy(kind: str) -> LifecyclePolicyDTO:
    """
    Normalize lifecycle vocab for a given kind ("resource"|"sponsor").

    Canonical source: policy_key="lifecycle" (policy_lifecycle.json).

    Returns (always):
      - readiness_allowed: list[str]
      - mou_allowed: list[str]

    May return (when available in policy):
      - readiness_default: str
      - mou_default: str
      - transitions: {readiness: {...}, mou: {...}, pledge: {...}}
    """
    where = "governance_v2._load_lifecycle_policy"
    machines = _load_lifecycle_doc()
    data = machines.get(kind)

    if not isinstance(data, dict):
        raise ContractError(
            code="policy_missing",
            where=where,
            message=f'policy "lifecycle" missing machine: {kind}',
            http_status=503,
            data={"policy_key": "lifecycle", "kind": kind},
        )

    # -----------------
    # Resource (simple lists)
    # -----------------
    if kind == "resource":
        readiness_raw = data.get("readiness")
        mou_raw = data.get("mou_status_allowed", data.get("mou_allowed"))

        if not isinstance(readiness_raw, list) or not readiness_raw:
            raise ContractError(
                code="policy_invalid",
                where=where,
                message="machines.resource.readiness must be a non-empty list",
                http_status=503,
                data={"policy_key": "lifecycle"},
            )
        if not isinstance(mou_raw, list) or not mou_raw:
            raise ContractError(
                code="policy_invalid",
                where=where,
                message="machines.resource.mou_status_allowed must be a non-empty list",
                http_status=503,
                data={"policy_key": "lifecycle"},
            )

        return {
            "readiness_allowed": _dedupe_preserve_order(readiness_raw),
            "mou_allowed": _dedupe_preserve_order(mou_raw),
        }

    # -----------------
    # Sponsor (status objects + defaults + transitions)
    # -----------------
    if kind == "sponsor":
        readiness_obj = data.get("readiness")
        mou_obj = data.get("mou")

        if not isinstance(readiness_obj, dict) or not isinstance(
            mou_obj, dict
        ):
            raise ContractError(
                code="policy_invalid",
                where=where,
                message="machines.sponsor.readiness and machines.sponsor.mou must be objects",
                http_status=503,
                data={"policy_key": "lifecycle"},
            )

        readiness_statuses = readiness_obj.get("statuses")
        mou_statuses = mou_obj.get("statuses")

        if not isinstance(readiness_statuses, list) or not readiness_statuses:
            raise ContractError(
                code="policy_invalid",
                where=where,
                message="machines.sponsor.readiness.statuses must be a non-empty list",
                http_status=503,
                data={"policy_key": "lifecycle"},
            )
        if not isinstance(mou_statuses, list) or not mou_statuses:
            raise ContractError(
                code="policy_invalid",
                where=where,
                message="machines.sponsor.mou.statuses must be a non-empty list",
                http_status=503,
                data={"policy_key": "lifecycle"},
            )

        readiness_allowed = _dedupe_preserve_order(
            [
                s.get("code")
                for s in readiness_statuses
                if isinstance(s, dict) and s.get("code")
            ]
        )
        mou_allowed = _dedupe_preserve_order(
            [
                s.get("code")
                for s in mou_statuses
                if isinstance(s, dict) and s.get("code")
            ]
        )

        if not readiness_allowed or not mou_allowed:
            raise ContractError(
                code="policy_invalid",
                where=where,
                message="sponsor lifecycle statuses must contain code fields",
                http_status=503,
                data={"policy_key": "lifecycle"},
            )

        out: LifecyclePolicyDTO = {
            "readiness_allowed": readiness_allowed,
            "mou_allowed": mou_allowed,
        }

        readiness_default = readiness_obj.get("default")
        if readiness_default is not None:
            readiness_default = str(readiness_default)
            if readiness_default not in readiness_allowed:
                raise ContractError(
                    code="policy_invalid",
                    where=where,
                    message="machines.sponsor.readiness.default must match readiness.statuses[].code",
                    http_status=503,
                    data={
                        "policy_key": "lifecycle",
                        "default": readiness_default,
                    },
                )
            out["readiness_default"] = readiness_default

        mou_default = mou_obj.get("default")
        if mou_default is not None:
            mou_default = str(mou_default)
            if mou_default not in mou_allowed:
                raise ContractError(
                    code="policy_invalid",
                    where=where,
                    message="machines.sponsor.mou.default must match mou.statuses[].code",
                    http_status=503,
                    data={"policy_key": "lifecycle", "default": mou_default},
                )
            out["mou_default"] = mou_default

        transitions = data.get("transitions")
        if transitions is not None:
            if not isinstance(transitions, dict):
                raise ContractError(
                    code="policy_invalid",
                    where=where,
                    message="machines.sponsor.transitions must be an object when present",
                    http_status=503,
                    data={"policy_key": "lifecycle"},
                )
            out["transitions"] = {
                "readiness": transitions.get("readiness"),
                "mou": transitions.get("mou"),
                "pledge": transitions.get("pledge"),
            }

        return out

    raise ContractError(
        code="bad_argument",
        where=where,
        message='kind must be "resource" or "sponsor"',
        http_status=400,
        data={"kind": kind},
    )


def get_resource_lifecycle_policy() -> LifecyclePolicyDTO:
    """Read-only lifecycle vocab for Resource readiness + MOU."""
    return _load_lifecycle_policy("resource")


def get_sponsor_lifecycle_policy() -> LifecyclePolicyDTO:
    """Read-only lifecycle vocab for Sponsor readiness + MOU."""
    return _load_lifecycle_policy("sponsor")


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
    schema_errors: list[str]
    domains: list[str]
    focus: str


class PolicyIndexDTO(TypedDict):
    ok: bool
    policies: list[PolicyIndexItemDTO]


class PolicyUpdatePreviewDTO(TypedDict):
    ok: bool
    dry_run: bool
    diff_summary: dict[str, list]  # added_keys / removed_keys / changed_keys


class PolicyUpdateCommitDTO(TypedDict):
    ok: bool
    dry_run: bool
    diff_summary: dict[str, list]


# -----------------
# Calls to Policy DTOs
# -----------------


def list_policies(*, validate: bool = False) -> dict[str, Any]:
    """
    Discover governance policies (PII-free).
    Optionally JSON-Schema validate.
    """
    return list_policies_impl(validate=validate)


def get_policy(*, key: str, validate: bool = False) -> dict[str, Any]:
    """
    Fetch one policy’s raw JSON (PII-free).
    Optionally JSON-Schema validate.
    """
    return get_policy_impl(key=key, validate=validate)


def preview_policy_update(
    *, key: str, new_policy: dict[str, Any]
) -> dict[str, Any]:
    """
    Dry-run: canonicalize + validate + diff, but do not write or emit.
    """
    return preview_update_impl(key=key, new_policy=new_policy)


def commit_policy_update(
    *, key: str, new_policy: dict[str, Any], actor_ulid: str
) -> dict[str, Any]:
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
    fund_archetype_key: str | None = None,
    period_label: str | None = None,
    source: str | None = None,
    prospect_ulid: str | None = None,
    notes: str | None = None,
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
        raise _as_contract_error(where, exc) from exc


def preview_ops_float(
    req: OpsFloatDecisionRequestDTO,
) -> FundingDecisionDTO:
    where = "governance_v2.preview_ops_float"
    try:
        raw_req = {
            "action": req.action,
            "support_mode": req.support_mode,
            "amount_cents": req.amount_cents,
            "fund_key": req.fund_key,
            "source_funding_demand_ulid": req.source_funding_demand_ulid,
            "source_project_ulid": req.source_project_ulid,
            "dest_funding_demand_ulid": req.dest_funding_demand_ulid,
            "dest_project_ulid": req.dest_project_ulid,
            "spending_class": req.spending_class,
            "tag_any": req.tag_any,
            "dest_eligible_fund_keys": req.dest_eligible_fund_keys,
            "ops_support_planned": req.ops_support_planned,
            "actor_rbac_roles": req.actor_rbac_roles,
            "actor_domain_roles": req.actor_domain_roles,
        }
        raw_out = svc_preview_ops_float(raw_req)
        return FundingDecisionDTO(
            allowed=bool(raw_out["allowed"]),
            eligible_fund_keys=tuple(raw_out.get("eligible_fund_keys") or ()),
            selected_fund_key=raw_out.get("selected_fund_key"),
            required_approvals=tuple(raw_out.get("required_approvals") or ()),
            reason_codes=tuple(raw_out.get("reason_codes") or ()),
            matched_rule_ids=tuple(raw_out.get("matched_rule_ids") or ()),
            decision_fingerprint=str(
                raw_out.get("decision_fingerprint") or ""
            ),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_budget_demands_for_period(
    *, period_label: str
) -> list[ProjectBudgetDemandDTO]:
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
        out: list[ProjectBudgetDemandDTO] = []

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
        raise _as_contract_error(where, exc) from exc


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
        raise _as_contract_error(where, exc) from exc


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
        raise _as_contract_error(where, exc) from exc
