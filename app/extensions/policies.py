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


@dataclass
class _CacheEntry:
    mtime: float
    hash: str
    data: dict


_CACHE: dict[str, _CacheEntry] = {}


def _load_and_cache(path: Path, key: str, schema_name: Optional[str]) -> dict:
    st = path.stat()
    ce = _CACHE.get(key)
    if ce and ce.mtime == st.st_mtime:
        return ce.data
    data = read_json_file(path, default=None)
    if data is None:
        raise FileNotFoundError(f"Missing or invalid JSON: {path}")
    if schema_name:
        schema_path = SCHEMAS / schema_name
        validate_json_payload(data, schema_path)
    entry = _CacheEntry(st.st_mtime, canonical_hash(data), data)
    _CACHE[key] = entry
    return data


# Governance-owned
def load_policy_issuance() -> dict:
    return _load_and_cache(
        GOV_DATA / "policy_issuance.json",
        "policy_issuance",
        "policy_issuance.schema.json",
    )


def load_policy_domain() -> dict:
    return _load_and_cache(
        GOV_DATA / "policy_domain.json",
        "policy_domain",
        "policy_domain.schema.json",
    )


# ✅ NEW: Calendar policy loader (no schema yet)
def load_policy_calendar() -> dict:
    return _load_and_cache(
        GOV_DATA / "policy_calendar.json",
        "policy_calendar",
        None,  # add a schema path when you define one
    )


# Auth-owned
def load_policy_rbac() -> dict:
    # No schema yet—simple shape; add later if desired.
    return _load_and_cache(
        AUTH_DATA / "policy_rbac.json", "policy_rbac", None
    )


# Optional save (with audit hook)
def save_policy(
    path: Path,
    payload: dict,
    schema_name: Optional[str] = None,
    auditor: Optional[Callable[[dict], None]] = None,
) -> dict:
    old = read_json_file(path, default=None)
    old_hash = canonical_hash(old) if old else None
    if schema_name:
        validate_json_payload(payload, SCHEMAS / schema_name)
    write_json_file(path, payload, pretty=True)
    # bust cache
    _CACHE.pop(path.name.replace(".json", ""), None)
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
    n = (name or "").lower()
    if n in ("issuance", "policy_issuance", "policy_issuance.json"):
        return load_policy_issuance()
    if n in ("domain", "policy_domain", "policy_domain.json"):
        return load_policy_domain()
    if n in ("calendar", "policy_calendar", "policy_calendar.json"):  # ✅ NEW
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
    "save_policy",
    "load_policy",
]
