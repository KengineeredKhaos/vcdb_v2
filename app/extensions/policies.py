"""
Governance/Auth policy loader, cache, and save helpers (v2 policy catalog).

This module is the single point of contact for reading and writing JSON-based
policy files.

Governance policies are catalog-driven (Policy Catalog v2.0):
- `app/slices/governance/data/policy_governance_index.json` is the manifest.
- Callers load governance policies by `policy_key` (not by filename).
- Each policy file is optionally validated against its JSON Schema listed in
  the manifest (relative to governance/data/).

Auth policies remain slice-owned and are loaded by explicit filename for now
(e.g., RBAC), but may be migrated to the manifest model later.

Design goals:
- One stable kwargs surface: `policy_key` everywhere.
- ULID everywhere (policy content must not contain table/column names).
- Cached by mtime so repeated reads are cheap.
- Write path validates + pretty-prints JSON and busts cache.

NOTE: JSON does not support comments. Use `meta.notes[]` in policy files.
"""
# app/extensions/policies.py

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.extensions.validate import validate_json_payload
from app.lib.jsonutil import canonical_hash, read_json_file, write_json_file

# Resolve paths relative to the installed app package, not the process CWD.
_APP_ROOT = Path(__file__).resolve().parents[1]  # .../app

GOV_DATA = _APP_ROOT / "slices" / "governance" / "data"
AUTH_DATA = _APP_ROOT / "slices" / "auth" / "data"

GOV_SCHEMAS = GOV_DATA / "schemas"
GOV_INDEX = GOV_DATA / "policy_governance_index.json"

_MOVED_GOVERNANCE_KEYS: dict[str, str] = {
    "customer": (
        "Moved to Customers slice taxonomy "
        "(app/slices/customers/taxonomy.py)."
    ),
    "lifecycle": (
        "Moved to owning slices (logistics/resources/sponsors taxonomy)."
    ),
    "locations": (
        "Moved to Logistics slice data + taxonomy "
        "(app/slices/logistics/data/locations.json and "
        "app/slices/logistics/taxonomy.py)."
    ),
    "operations": (
        "Moved to Calendar slice taxonomy "
        "(app/slices/calendar/taxonomy.py)."
    ),
    "service_taxonomy": (
        "Decomposed into slice-local taxonomies (resources/sponsors/logistics)."
    ),
}


@dataclass(frozen=True)
class PolicyCatalogEntry:
    policy_key: str
    filename: str
    schema_filename: str | None = None


@dataclass
class _CacheEntry:
    mtime: float
    hash: str
    data: dict


_CACHE: dict[str, _CacheEntry] = {}
# cached manifest map: policy_key -> entry
_CATALOG: dict[str, PolicyCatalogEntry] | None = None


def _cache_key(path: Path) -> str:
    # Use absolute path string for safety (avoid collisions across tests/CWD).
    return str(path.resolve())


def _load_and_cache(path: Path, *, schema_path: Path | None = None) -> dict:
    """
    Load JSON from disk, validate (if schema_path is provided and exists),
    and cache by file mtime.
    """
    key = _cache_key(path)
    st = path.stat()
    ce = _CACHE.get(key)
    if ce and ce.mtime == st.st_mtime:
        return ce.data

    data = read_json_file(path, default=None)
    if data is None:
        raise FileNotFoundError(f"Missing or invalid JSON: {path}")

    if schema_path is not None and schema_path.exists():
        validate_json_payload(data, schema_path)

    _CACHE[key] = _CacheEntry(
        mtime=st.st_mtime, hash=canonical_hash(data), data=data
    )
    return data


def _bust_cache(path: Path) -> None:
    _CACHE.pop(_cache_key(path), None)


def _load_catalog() -> dict[str, PolicyCatalogEntry]:
    """
    Load and validate the Governance policy catalog (manifest), then build
    a policy_key -> entry map.

    Raises:
      - FileNotFoundError if GOV_INDEX missing
      - ValueError on duplicate policy_key entries
    """
    global _CATALOG

    if _CATALOG is not None:
        return _CATALOG

    # Validate manifest if its schema exists (optional during bring-up).
    idx_schema = GOV_SCHEMAS / "policy_governance_index.schema.json"
    idx = _load_and_cache(GOV_INDEX, schema_path=idx_schema)

    policies = idx.get("policies") or []
    if not isinstance(policies, list):
        raise ValueError(
            "policy_governance_index.json: 'policies' must be a list"
        )

    out: dict[str, PolicyCatalogEntry] = {}
    for p in policies:
        if not isinstance(p, dict):
            raise ValueError(
                "policy_governance_index.json: policies[] must be objects"
            )
        key = p.get("policy_key")
        fn = p.get("filename")
        sfn = p.get("schema_filename")
        if not key or not fn:
            raise ValueError(
                "policy_governance_index.json: each entry needs policy_key and filename"
            )
        if key in out:
            raise ValueError(
                f"policy_governance_index.json: duplicate policy_key: {key!r}"
            )
        out[key] = PolicyCatalogEntry(
            policy_key=key, filename=fn, schema_filename=sfn
        )

    _CATALOG = out
    return out


def load_policy_catalog() -> dict[str, PolicyCatalogEntry]:
    """
    Diagnostics/tests: return the cached governance policy catalog map:
    policy_key -> PolicyCatalogEntry.
    """
    return _load_catalog()


def reload_policy_catalog() -> None:
    """Clear cached manifest + any cached policy payloads (next loads reread disk)."""
    global _CATALOG
    _CATALOG = None
    _CACHE.clear()


def _resolve_governance_policy_paths(
    policy_key: str,
) -> tuple[Path, Path | None]:
    cat = _load_catalog()
    if policy_key not in cat:

        hint = _MOVED_GOVERNANCE_KEYS.get(policy_key)
        if hint:
            raise KeyError(
                f"Governance policy_key {policy_key!r} moved out of "
                f"Governance. {hint}"
            )
        raise KeyError(f"Unknown governance policy_key: {policy_key!r}")
    entry = cat[policy_key]
    policy_path = GOV_DATA / entry.filename
    schema_path: Path | None = None
    if entry.schema_filename:
        schema_path = GOV_DATA / entry.schema_filename
    return policy_path, schema_path


def load_governance_policy(policy_key: str) -> dict:
    """
    Load a governance policy by policy_key, validate against its schema
    if listed in the manifest, and return the parsed dict.
    """
    policy_path, schema_path = _resolve_governance_policy_paths(policy_key)
    return _load_and_cache(policy_path, schema_path=schema_path)


def save_governance_policy(
    policy_key: str,
    payload: dict,
    *,
    auditor: Callable[[dict], None] | None = None,
) -> dict:
    """
    Validate (if schema is known), write pretty JSON, bust cache,
    and optionally emit an audit callback (caller decides how to persist).

    NOTE: This function does NOT write to the Ledger. Routes/services must do that.
    """
    policy_path, schema_path = _resolve_governance_policy_paths(policy_key)

    old = read_json_file(policy_path, default=None)
    old_hash = canonical_hash(old) if old else None

    if schema_path is not None and schema_path.exists():
        validate_json_payload(payload, schema_path)

    write_json_file(policy_path, payload, pretty=True)
    _bust_cache(policy_path)

    # bust manifest cache if we updated it
    if policy_path.name == GOV_INDEX.name:
        reload_policy_catalog()

    if auditor:
        auditor(
            {
                "event": "governance.policy.update",
                "policy_key": policy_key,
                "file": str(policy_path),
                "old_hash": old_hash,
                "new_hash": canonical_hash(payload),
                "ts": time.time(),
            }
        )
    return payload


# ------------------
# Governance typed loaders (v2 keys)
# ------------------

def _raise_moved(policy_key: str) -> None:
    hint = _MOVED_GOVERNANCE_KEYS.get(policy_key)
    msg = (
        f"Governance policy_key {policy_key!r} moved out of Governance. "
        f"{hint or ''}"
    )
    raise KeyError(msg)


def load_policy_customer() -> dict:

    _raise_moved("customer")


def load_policy_entity_roles() -> dict:
    return load_governance_policy("entity_roles")


def load_policy_finance_controls() -> dict:
    return load_governance_policy("finance_controls")


def load_policy_finance_taxonomy() -> dict:
    return load_governance_policy("finance_taxonomy")


def load_policy_lifecycle() -> dict:

    _raise_moved("lifecycle")


def load_policy_locations() -> dict:

    _raise_moved("locations")


def load_policy_logistics_issuance() -> dict:
    return load_governance_policy("logistics_issuance")


def load_policy_operations() -> dict:

    _raise_moved("operations")


def load_policy_service_taxonomy() -> dict:

    _raise_moved("service_taxonomy")
def load_policy_governance_index() -> dict:
    # Useful for CLI/admin diagnostics.
    return load_governance_policy("governance_index")


# ------------------
# Auth-owned
# ------------------


def load_policy_rbac() -> dict:
    path = AUTH_DATA / "policy_rbac.json"
    schema_path = AUTH_DATA / "schemas" / "policy_rbac.schema.json"
    return _load_and_cache(
        path, schema_path=schema_path if schema_path.exists() else None
    )


# -----------------
# compatibility shim
# (temporary: keeps legacy imports working while refactor lands)
# -----------------

_LEGACY_ALIASES: dict[str, str] = {
    # v1 -> v2
    "issuance": "logistics_issuance",
    "policy_issuance": "logistics_issuance",
    "policy_issuance.json": "logistics_issuance",
    "sku_constraints": "logistics_issuance",
    "policy_sku_constraints": "logistics_issuance",
    "policy_sku_constraints.json": "logistics_issuance",
    "domain": "entity_roles",
    "policy_domain": "entity_roles",
    "policy_domain.json": "entity_roles",
    "projects": "operations",
    "policy_projects": "operations",
    "policy_projects.json": "operations",
    "calendar": "operations",
    "policy_calendar": "operations",
    "policy_calendar.json": "operations",
    "fund_archetype": "finance_taxonomy",
    "policy_fund_archetype": "finance_taxonomy",
    "policy_fund_archetype.json": "finance_taxonomy",
    "journal_flags": "finance_taxonomy",
    "policy_journal_flags": "finance_taxonomy",
    "policy_journal_flags.json": "finance_taxonomy",
    "budget": "finance_controls",
    "policy_budget": "finance_controls",
    "policy_budget.json": "finance_controls",
    "spending": "finance_controls",
    "policy_spending": "finance_controls",
    "policy_spending.json": "finance_controls",
    "locations": "locations",
    "policy_locations": "locations",
    "policy_locations.json": "locations",
}


_LEGACY_ALIASES.update(
    {
        "rbac": "rbac",  # (handled already, but harmless)
        "policy_rbac": "rbac",
    }
)


def load_policy(name: str) -> dict:
    """
    Backwards-compatible governance policy loader.

    Accepts legacy names like "issuance" or "policy_issuance.json" and
    dispatches to the v2 policy catalog.

    New code should call `load_governance_policy(policy_key)` or the typed
    v2 functions.
    """
    n = (name or "").strip().lower()
    if n in ("rbac", "policy_rbac", "policy_rbac.json"):
        return load_policy_rbac()

    policy_key = _LEGACY_ALIASES.get(n, n)
    return load_governance_policy(policy_key)


# --- compatibility shims (temporary; delete after refactor lands) ---


def load_policy_sku_constraints() -> dict:
    """
    Legacy v1 shim.

    v1 had policy_sku_constraints.json.
    v2 folds that into policy_logistics_issuance.json under the 'sku_constraints' key.
    """
    pol = load_policy_logistics_issuance()
    return pol.get("sku_constraints") or {}


def load_policy_issuance() -> dict:
    """
    Legacy v1 shim.

    v2 folds issuance defaults/rules into policy_logistics_issuance.json under 'issuance'.
    """
    pol = load_policy_logistics_issuance()
    return pol.get("issuance") or {}


__all__ = [
    "GOV_DATA",
    "AUTH_DATA",
    "GOV_INDEX",
    "GOV_SCHEMAS",
    "load_policy_catalog",
    "reload_policy_catalog",
    "load_governance_policy",
    "save_governance_policy",
    # typed governance
    "load_policy_customer",
    "load_policy_entity_roles",
    "load_policy_finance_controls",
    "load_policy_finance_taxonomy",
    "load_policy_lifecycle",
    "load_policy_locations",
    "load_policy_logistics_issuance",
    "load_policy_operations",
    "load_policy_service_taxonomy",
    "load_policy_governance_index",
    # auth
    "load_policy_rbac",
    # compatibility
    "load_policy",
    "load_policy_sku_constraints",
    "load_policy_issuance",
]
