# app/extensions/policies.py

"""
Governance/Auth policy loader, cache, and save helpers.

This module is the single point of contact for reading and writing
JSON-based policy files, primarily under:

- app/slices/governance/data/...
- app/slices/auth/data/...

Core ideas:

- `load_policy_issuance()`, `load_policy_domain()`,
  `load_policy_calendar()`, `load_policy_rbac()`:
    * Load JSON from disk.
    * Optionally validate against a JSON Schema (via validate_json_payload).
    * Cache by mtime + hash so repeated reads are cheap.

- `save_policy(path, payload, schema_name, auditor)`:
    * Optionally validate before writing.
    * Write pretty JSON.
    * Bust the local cache.
    * Call an optional `auditor` callback with before/after hashes.

- `load_policy(name)`: compatibility shim that preserves older call
  sites that refer to policies by short names like "issuance" or "rbac".

Future Dev:
- When you add new governance policy files, wire them here so the rest
  of the app never reaches directly into app/slices/governance/data.
- Policy validation should live in JSON Schemas + policy_semantics, not
  scattered ad-hoc across slices.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.extensions.validate import validate_json_payload
from app.lib.jsonutil import canonical_hash, read_json_file, write_json_file

GOV_DATA = Path("app/slices/governance/data")
AUTH_DATA = Path("app/slices/auth/data")
SCHEMAS = GOV_DATA / "schemas"

POLICY_SCHEMA_MAP: dict[str, str] = {
    "policy_calendar.json": "policy_calendar.schema.json",
    "policy_classification.json": "policy_classification.schema.json",
    "policy_customer_needs.json": "policy_customer_needs.schema.json",
    "policy_domain.json": "policy_domain.schema.json",
    "policy_eligibility.json": "policy_eligibility.schema.json",
    "policy_funding.json": "policy_funding.schema.json",
    "policy_issuance.json": "policy_issuance.schema.json",
    "policy_poc.json": "policy_poc.schema.json",
    "policy_resource_capabilities.json": "policy_resource_capabilities.schema.json",
    "policy_resource_lifecycle.json": "policy_resource_lifecycle.schema.json",
    "policy_sku_constraints.json": "policy_sku_constraints.schema.json",
    "policy_spending.json": "policy_spending.schema.json",
    "policy_sponsor_capabilities.json": "policy_sponsor_capabilities.schema.json",
    "policy_sponsor_lifecycle.json": "policy_sponsor_lifecycle.schema.json",
    "policy_sponsor_pledge.json": "policy_sponsor_pledge.schema.json",
    "policy_state_machine.json": "policy_state_machine.schema.json",
    "policy_projects.json": "policy_projects.schema.json",
    "policy_journal_flags.json": "policy_journal_flags.schema.json",
    "policy_budget.json": "policy_budget.schema.json",
}


@dataclass
class _CacheEntry:
    mtime: float
    hash: str
    data: dict


_CACHE: dict[str, _CacheEntry] = {}


def _schema_for(basename: str) -> Optional[str]:
    """Return schema filename (not full path) for a policy JSON basename."""
    return POLICY_SCHEMA_MAP.get(basename)


def _load_and_cache(path: Path, *, schema_name: Optional[str] = None) -> dict:
    """
    Load JSON from disk, validate (if schema_name is provided),
    and cache by file mtime.
    """
    key = path.name  # e.g. "policy_issuance.json"
    st = path.stat()
    ce = _CACHE.get(key)

    if ce and ce.mtime == st.st_mtime:
        return ce.data

    data = read_json_file(path, default=None)
    if data is None:
        raise FileNotFoundError(f"Missing or invalid JSON: {path}")

    # Resolve schema if caller didn't override
    if schema_name is None:
        schema_name = _schema_for(key)

    if schema_name:
        validate_json_payload(data, SCHEMAS / schema_name)

    entry = _CacheEntry(
        mtime=st.st_mtime, hash=canonical_hash(data), data=data
    )
    _CACHE[key] = entry
    return data


# -----------------
# Governance-owned
# -----------------


def load_policy_issuance() -> dict:
    basename = "policy_issuance.json"
    return _load_and_cache(GOV_DATA / basename)


def load_policy_domain() -> dict:
    basename = "policy_domain.json"
    return _load_and_cache(GOV_DATA / basename)


def load_policy_calendar() -> dict:
    basename = "policy_calendar.json"
    return _load_and_cache(GOV_DATA / basename)


def load_policy_projects() -> dict:
    basename = "policy_projects.json"
    return _load_and_cache(GOV_DATA / basename)


def load_policy_journal_flags() -> dict:
    basename = "policy_journal_flags.json"
    return _load_and_cache(GOV_DATA / basename)


def load_policy_budget() -> dict:
    basename = "policy_budget.json"
    return _load_and_cache(GOV_DATA / basename)


def load_policy_funding() -> dict:
    basename = "policy_funding.json"
    return _load_and_cache(GOV_DATA / basename)


# -----------------
# Governance-owned
# Logistics Specific
# -----------------


def load_policy_sku_constraints() -> dict:
    """
    Load and validate the SKU constraints policy.

    Returns a dict with keys:
      - version: int
      - rules: list[...]
      - allowed_units: list[str]
      - allowed_sources: list[str]
    """
    policy_path = GOV_DATA / "policy_sku_constraints.json"
    schema_path = SCHEMAS / "policy_sku_constraints.schema.json"

    data = read_json_file(policy_path)
    validate_json_payload(data, schema_path)
    return data


def load_policy_locations() -> dict:
    """
    Load and validate Storage locations policy.
    Returns a dictionary with keys:
    - version: int
    - kinds: list[...]
    - locations: list of dictionaries[ { code: "fixed-names"}
                                       { code: "mobile-names"}
                                       { code: "satellite-names"}]
    - patterns: dictionary: {rackbin: "[regex]"}

    """
    policy_path = GOV_DATA / "policy_locations.json"
    schema_path = SCHEMAS / "policy_locations.schema.json"
    data = read_json_file(policy_path)
    validate_json_payload(data, schema_path)
    return data


# ------------------
# Auth-owned
# -----------------


def load_policy_rbac() -> dict:
    # No schema yet for auth; add mapping when you create one.
    path = AUTH_DATA / "policy_rbac.json"
    return _load_and_cache(path, schema_name=None)


# Optional save (with audit hook)
def save_policy(
    path: Path,
    payload: dict,
    schema_name: Optional[str] = None,
    auditor: Optional[Callable[[dict], None]] = None,
) -> dict:
    """
    Validate (if schema is known), write pretty JSON, and bust cache.

    If schema_name is None, we will look up the schema by path.name via
    POLICY_SCHEMA_MAP. Pass schema_name explicitly to override.
    """
    old = read_json_file(path, default=None)
    old_hash = canonical_hash(old) if old else None

    if schema_name is None:
        schema_name = _schema_for(path.name)

    if schema_name:
        validate_json_payload(payload, SCHEMAS / schema_name)

    write_json_file(path, payload, pretty=True)

    # bust cache for this file
    _CACHE.pop(path.name, None)

    if auditor:
        auditor(
            {
                "event": "governance.policy.update",
                "file": str(path),
                "old_hash": old_hash,
                "new_hash": canonical_hash(payload),
                "ts": time.time(),
            }
        )
    return payload


# -----------------
# compatibility shim
# (keep legacy imports working)
# -----------------


def load_policy(name: str) -> dict:
    """
    Backwards-compatible policy loader.

    Accepts names like "issuance", "policy_issuance",
    "policy_issuance.json", etc., and dispatches to the typed loaders.
    """
    n = (name or "").lower()

    if n in ("issuance", "policy_issuance", "policy_issuance.json"):
        return load_policy_issuance()
    if n in ("domain", "policy_domain", "policy_domain.json"):
        return load_policy_domain()
    if n in ("calendar", "policy_calendar", "policy_calendar.json"):
        return load_policy_calendar()
    if n in ("rbac", "policy_rbac", "policy_rbac.json"):
        return load_policy_rbac()

    raise KeyError(f"Unknown policy name: {name!r}")


__all__ = [
    "GOV_DATA",
    "AUTH_DATA",
    "load_policy_issuance",
    "load_policy_domain",
    "load_policy_calendar",  # ✅ NEW
    "load_policy_rbac",
    "load_policy_sku_constraints",  # logistics.services.
    "load_policy_locations",  # logistics.services.
    "load_policy_projects",
    "load_policy_journal_flags",
    "load_policy_budget",
    "load_policy_funding",
    "save_policy",
    "load_policy",
]
