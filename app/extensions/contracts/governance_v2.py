# app/extensions/contracts/governance_v2.py

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, TypedDict

from flask import current_app

from app.extensions import event_bus
from app.extensions.contracts import customers_v2
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
]


class ContractError(RuntimeError):
    pass


# -----------------
# DTO's
# -----------------


class SpendingLimitsDTO(TypedDict):
    staff_limit_cents: int
    admin_over_cents: int


class ConstraintFlagsDTO(TypedDict):
    veteran_only: bool
    homeless_only: bool


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
# Role Code Mechanisms
# contract shape &
# sane defaults used
# primarily for tests
# DISABLE FOR PRODUCTION
# (todo: deal with this)
# -----------------


# Contract shape:
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
    # <app-root> (where Flask's current_app.root_path points to app/)
    return Path(current_app.root_path)


def _policy_path_auth(name: str) -> Path:
    # Auth owns RBAC
    return _app_root() / "slices" / "auth" / "data" / f"{name}.json"


def _policy_path_gov(name: str) -> Path:
    # Governance owns domain roles
    return _app_root() / "slices" / "governance" / "data" / f"{name}.json"


def _load_json_file(p: Path) -> dict:
    if not p.exists():
        raise ContractError(f"policy file missing: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ContractError(f"failed to parse {p}: {e}") from e


def get_role_catalogs() -> Dict[str, object]:
    """
    Read-only contract returning role catalogs from policy files:

      {
        "roles": [... domain role codes ...],
        "rbac_roles": [... rbac role codes ...],
        "rbac_to_domain": { "<rbac>": [<domain role>, ...], ... }
      }

    Sources:
      - RBAC:        app/slices/auth/data/policy_rbac.json
      - Domain roles app/slices/governance/data/policy_domain.json
    """
    rbac = _load_json_file(_policy_path_auth("policy_rbac"))
    dom = _load_json_file(_policy_path_gov("policy_domain"))

    rbac_roles: List[str] = list(map(str, (rbac.get("rbac_roles") or [])))
    domain_roles: List[str] = list(map(str, (dom.get("domain_roles") or [])))

    ar = dom.get("assignment_rules") or {}
    raw_map = ar.get("rbac_to_domain") or {}

    domain_set = set(domain_roles)
    rbac_to_domain = {
        str(k): sorted([str(d) for d in (v or []) if str(d) in domain_set])
        for k, v in raw_map.items()
        if str(k) in rbac_roles
    }
    # ensure every RBAC role is present as a key (even if empty)
    for r in rbac_roles:
        rbac_to_domain.setdefault(r, [])

    return {
        "roles": sorted(domain_roles),
        "rbac_roles": sorted(rbac_roles),
        "rbac_to_domain": rbac_to_domain,
    }


# Optional aliases used by some callers
def rbac_role_codes() -> List[str]:
    return get_role_catalogs()["rbac_roles"]  # type: ignore[index]


def domain_role_codes() -> List[str]:
    return get_role_catalogs()["roles"]  # type: ignore[index]


def _gov_data_dir() -> Path:
    # <app-root>/slices/governance/data
    return Path(current_app.root_path) / "slices" / "governance" / "data"


def _load_json(name: str) -> dict:
    p = _gov_data_dir() / f"{name}.json"
    if not p.exists():
        raise ContractError(f"policy file missing: {p}")
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise ContractError(f"failed to parse {p}: {e}") from e


# -----------------
# Custoner Contract API
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
# Governance Policy
# typed DTOs for
# Admin policy changes
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
    """Discover governance policies (PII-free). Optionally JSON-Schema validate."""
    return list_policies_impl(validate=validate)


def get_policy(*, key: str, validate: bool = False) -> Dict[str, Any]:
    """Fetch one policy’s raw JSON (PII-free). Optionally JSON-Schema validate."""
    return get_policy_impl(key=key, validate=validate)


def preview_policy_update(
    *, key: str, new_policy: Dict[str, Any]
) -> Dict[str, Any]:
    """Dry-run: canonicalize + validate + diff, but do not write or emit."""
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
