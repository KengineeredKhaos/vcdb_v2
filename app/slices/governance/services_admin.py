# app/slices/governance/services_admin.py

"""
Implements the actual reading/writing of app/slices/governance/data/*.json.

Responsibilities:
  * Load and JSON-Schema validate Governance policy files.
  * Create backups and perform atomic writes on update.
  * Emit ledger events via event_bus.emit(...) when board policy changes.

This module is **internal to the Governance slice**. It is not imported
directly by routes or other slices.

The public entry points for policy editing live in the governance_v2
contract module:

    app.extensions.contracts.governance_v2.list_policies(...)
    app.extensions.contracts.governance_v2.get_policy(...)
    app.extensions.contracts.governance_v2.preview_policy_update(...)
    app.extensions.contracts.governance_v2.commit_policy_update(...)

Admin routes (in app/slices/admin/routes.py) call those contract
functions, with RBAC 'admin' and domain-role 'governor' guards.

During development, CLI tools or dev-only endpoints may also call the
same governance_v2 contract functions, but no code outside the Governance
slice should import this provider module directly.
"""

# app/slices/governance/services_admin.py
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from flask import current_app

from app.extensions import event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid

# -----------------
# helper functions
# specifically for
# governance policy
# read-only policy
# check below at
# @bp_api_v2.get("/governance/policies")
# -----------------


try:
    # jsonschema is lightweight; if missing, we’ll degrade gracefully
    from jsonschema import Draft202012Validator

    _JSONSCHEMA_AVAILABLE = True
except Exception:
    _JSONSCHEMA_AVAILABLE = False


# -----------------
# helpers (private)
# -----------------


def _gov_data_dir() -> Path:
    # app root -> app/slices/governance/data
    return Path(current_app.root_path) / "slices" / "governance" / "data"


def _schemas_dir() -> Path:
    return _gov_data_dir() / "schemas"


def _read_json(p: Path) -> dict[str, Any]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        current_app.logger.warning(
            {
                "event": "gov_policy_read_error",
                "file": str(p),
                "error": str(e),
            }
        )
        return {}


def _infer_focus(obj: dict, fname_stem: str) -> str:
    if "issuance" in obj or "issuance_rules" in obj:
        return "issuance"
    if "assignment_rules" in obj:
        return "domain_assignment"
    if "calendar" in obj or "blackout_dates" in obj:
        return "calendar"
    return fname_stem.replace("_", "-")


def _extract_domains(obj: dict) -> list[str]:
    if isinstance(obj.get("domain_roles"), list):
        return [str(x) for x in obj["domain_roles"]]
    if isinstance(obj.get("applies_to"), list):
        return [str(x) for x in obj["applies_to"]]
    ar = obj.get("assignment_rules") or {}
    if isinstance(ar.get("domain_disallows_rbac"), list) and isinstance(
        obj.get("domain_roles"), list
    ):
        return [str(x) for x in obj["domain_roles"]]
    return []


def _maybe_validate(
    policy_obj: dict, schema_path: Path | None
) -> tuple[bool | None, list[str]]:
    """
    Returns (schema_valid, errors).
    - if jsonschema unavailable or schema missing: (None, [])
    """
    if (
        not _JSONSCHEMA_AVAILABLE
        or not schema_path
        or not schema_path.exists()
    ):
        return (None, [])

    try:
        schema = json.loads(schema_path.read_text("utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        errors = sorted(
            validator.iter_errors(policy_obj), key=lambda e: e.path
        )
    except Exception as e:
        return (False, [f"schema-error: {e}"])

    if not errors:
        return (True, [])
    msgs: list[str] = []
    for err in errors[:10]:
        loc = ".".join(map(str, err.path)) or "(root)"
        msgs.append(f"{loc}: {err.message}")
    if len(errors) > 10:
        msgs.append(f"... and {len(errors) - 10} more")
    return (False, msgs)


def _canonicalize(doc: dict[str, Any]) -> dict[str, Any]:
    # simple canonicalization: stable key ordering and no trailing spaces via json dumps/loads
    return json.loads(json.dumps(doc, separators=(",", ":"), sort_keys=True))


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _policy_path_for(key: str) -> Path:
    return _gov_data_dir() / f"{key}.json"


def _schema_path_for(key: str) -> Path:
    return _schemas_dir() / f"{key}.schema.json"


def _atomic_write_json(dst: Path, doc: dict[str, Any]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    # backup
    backups = _gov_data_dir() / "_backups"
    backups.mkdir(parents=True, exist_ok=True)
    ts = now_iso8601_ms().replace(":", "").replace("-", "")
    backup_path = backups / f"{dst.name}.{ts}.bak"
    if dst.exists():
        try:
            backup_path.write_bytes(dst.read_bytes())
        except Exception as e:
            current_app.logger.warning(
                {
                    "event": "gov_policy_backup_warn",
                    "file": str(dst),
                    "error": str(e),
                }
            )

    # atomic temp -> rename
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=str(dst.parent)
    ) as tf:
        json.dump(
            doc, tf, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        tmp_name = tf.name
    os.replace(tmp_name, dst)


# -----------------
# Provider
# (contract target)
# -----------------


def list_policies_impl(*, validate: bool = False) -> dict[str, Any]:
    d, sdir = _gov_data_dir(), _schemas_dir()
    items: list[dict[str, Any]] = []
    for p in sorted(d.glob("policy_*.json")):
        key = p.stem
        obj = _read_json(p)
        schema_p = sdir / f"{key}.schema.json"
        v_ok, v_errs = (
            _maybe_validate(obj, schema_p) if validate else (None, [])
        )
        items.append(
            {
                "key": key,
                "filename": p.name,
                "focus": _infer_focus(obj, key),
                "domains": _extract_domains(obj),
                "has_schema": schema_p.exists(),
                "schema_valid": True if v_ok is None else bool(v_ok),
                "schema_errors": v_errs or [],
            }
        )
    return {"ok": True, "policies": items}


def get_policy_impl(*, key: str, validate: bool = False) -> dict[str, Any]:
    p = _policy_path_for(key)
    if not p.exists():
        return {"ok": False, "error": "not_found"}
    obj = _read_json(p)
    schema_p = _schema_path_for(key)
    v_ok, v_errs = _maybe_validate(obj, schema_p) if validate else (None, [])
    return {
        "ok": True,
        "key": key,
        "focus": _infer_focus(obj, key),
        "domains": _extract_domains(obj),
        "has_schema": schema_p.exists(),
        "schema_valid": True if v_ok is None else bool(v_ok),
        "schema_errors": v_errs or [],
        "policy": obj,
    }


def preview_update_impl(
    *, key: str, new_policy: dict[str, Any]
) -> dict[str, Any]:
    dst = _policy_path_for(key)
    if not dst.exists():
        return {"ok": False, "error": "not_found"}
    old = _read_json(dst)
    new = _canonicalize(new_policy)

    schema_p = _schema_path_for(key)
    v_ok, v_errs = _maybe_validate(new, schema_p)

    # quick & dirty diff summary
    old_keys, new_keys = set(old.keys()), set(new.keys())
    diff = {
        "added_keys": sorted(new_keys - old_keys),
        "removed_keys": sorted(old_keys - new_keys),
        "changed_keys": sorted(
            k for k in (old_keys & new_keys) if old.get(k) != new.get(k)
        ),
    }

    return {
        "ok": bool(v_ok) if v_ok is not None else True,
        "dry_run": True,
        "schema_errors": v_errs or [],
        "diff_summary": diff,
    }


def commit_update_impl(
    *, key: str, new_policy: dict[str, Any], actor_ulid: str
) -> dict[str, Any]:
    dst = _policy_path_for(key)
    if not dst.exists():
        return {"ok": False, "error": "not_found"}

    old_bytes = dst.read_bytes() if dst.exists() else b"{}"
    old_hash = _sha256_bytes(old_bytes)

    new_doc = _canonicalize(new_policy)
    schema_p = _schema_path_for(key)
    v_ok, v_errs = _maybe_validate(new_doc, schema_p)
    if v_ok is False:
        return {
            "ok": False,
            "error": "schema_invalid",
            "schema_errors": v_errs,
        }

    # write atomically
    _atomic_write_json(dst, new_doc)
    new_hash = _sha256_bytes(dst.read_bytes())

    # emit single ledger event (names only; no PII)
    event_bus.emit(
        domain="governance",
        operation="governance_policy_updated",
        request_id=new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=None,
        happened_at_utc=now_iso8601_ms(),
        refs={"key": key, "old_sha256": old_hash, "new_sha256": new_hash},
    )

    return {
        "ok": True,
        "committed": True,
        "key": key,
        "old_sha256": old_hash,
        "new_sha256": new_hash,
    }
