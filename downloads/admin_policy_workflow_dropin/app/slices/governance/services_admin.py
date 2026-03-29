# app/slices/governance/services_admin.py

"""
Implements the actual reading/writing of app/slices/governance/data/*.json.

Responsibilities:
  * Load and JSON-Schema validate Governance policy files.
  * Create backups and perform atomic writes on update.
  * Emit ledger events via event_bus.emit(...) when board policy changes.

This module is internal to the Governance slice. The public entry points
for policy editing live in the governance_v2 contract module.
"""

from __future__ import annotations

import difflib
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

try:
    from jsonschema import Draft202012Validator

    _JSONSCHEMA_AVAILABLE = True
except Exception:
    _JSONSCHEMA_AVAILABLE = False


def _gov_data_dir() -> Path:
    return Path(current_app.root_path) / "slices" / "governance" / "data"


def _schemas_dir() -> Path:
    return _gov_data_dir() / "schemas"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _json_text(doc: dict[str, Any]) -> str:
    return json.dumps(
        doc,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _infer_focus(obj: dict[str, Any], fname_stem: str) -> str:
    if "issuance" in obj or "issuance_rules" in obj:
        return "issuance"
    if "assignment_rules" in obj:
        return "domain_assignment"
    if "calendar" in obj or "blackout_dates" in obj:
        return "calendar"
    return fname_stem.replace("_", "-")


def _extract_domains(obj: dict[str, Any]) -> list[str]:
    if isinstance(obj.get("domain_roles"), list):
        return [str(x) for x in obj["domain_roles"]]
    if isinstance(obj.get("applies_to"), list):
        return [str(x) for x in obj["applies_to"]]
    return []


def _canonicalize(doc: dict[str, Any]) -> dict[str, Any]:
    return json.loads(
        json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _policy_path_for(key: str) -> Path:
    return _gov_data_dir() / f"{key}.json"


def _schema_path_for(key: str) -> Path:
    return _schemas_dir() / f"{key}.schema.json"


def _issue(
    *,
    source: str,
    severity: str,
    message: str,
    path: str = "",
) -> dict[str, str]:
    return {
        "source": source,
        "severity": severity,
        "path": path,
        "message": message,
    }


def _maybe_validate(
    policy_obj: dict[str, Any],
    schema_path: Path | None,
) -> tuple[bool | None, list[dict[str, str]]]:
    """
    Returns (schema_valid, issues).

    - schema_valid is None when jsonschema or the schema file is absent
    - issues contain path-aware schema errors
    """
    if (
        not _JSONSCHEMA_AVAILABLE
        or not schema_path
        or not schema_path.exists()
    ):
        return (
            None,
            (
                [
                    _issue(
                        source="schema",
                        severity="warning",
                        path="",
                        message="Schema file not available for this policy.",
                    )
                ]
                if not schema_path or not schema_path.exists()
                else []
            ),
        )

    try:
        schema = json.loads(schema_path.read_text("utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        errors = sorted(
            validator.iter_errors(policy_obj),
            key=lambda err: list(err.path),
        )
    except Exception as exc:
        return (
            False,
            [
                _issue(
                    source="schema",
                    severity="error",
                    path="",
                    message=f"schema-error: {exc}",
                )
            ],
        )

    if not errors:
        return (True, [])

    issues: list[dict[str, str]] = []
    for err in errors[:25]:
        path = ".".join(str(p) for p in err.path)
        issues.append(
            _issue(
                source="schema",
                severity="error",
                path=path,
                message=err.message,
            )
        )
    if len(errors) > 25:
        issues.append(
            _issue(
                source="schema",
                severity="warning",
                path="",
                message=f"... and {len(errors) - 25} more schema errors",
            )
        )
    return (False, issues)


def _semantic_validate(
    *,
    key: str,
    doc: dict[str, Any],
) -> tuple[bool, list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    expected_key = key.removeprefix("policy_")
    meta = doc.get("meta")

    if not isinstance(doc, dict):
        return (
            False,
            [
                _issue(
                    source="semantic",
                    severity="error",
                    path="",
                    message="Policy document must be a JSON object.",
                )
            ],
        )

    if not isinstance(meta, dict):
        issues.append(
            _issue(
                source="semantic",
                severity="error",
                path="meta",
                message="Missing meta object.",
            )
        )
        return (False, issues)

    required_meta = (
        "policy_key",
        "title",
        "status",
        "version",
        "schema_version",
        "effective_on",
    )
    for field in required_meta:
        value = meta.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(
                _issue(
                    source="semantic",
                    severity="error",
                    path=f"meta.{field}",
                    message="Missing or empty required meta field.",
                )
            )

    actual_policy_key = str(meta.get("policy_key") or "")
    if actual_policy_key and actual_policy_key != expected_key:
        issues.append(
            _issue(
                source="semantic",
                severity="error",
                path="meta.policy_key",
                message=(
                    f"meta.policy_key must equal '{expected_key}' for "
                    f"file {key}.json"
                ),
            )
        )

    notes = meta.get("notes")
    if notes is not None and not isinstance(notes, list):
        issues.append(
            _issue(
                source="semantic",
                severity="warning",
                path="meta.notes",
                message="Expected meta.notes to be a list.",
            )
        )

    if key == "policy_governance_index":
        policies = doc.get("policies")
        if not isinstance(policies, list):
            issues.append(
                _issue(
                    source="semantic",
                    severity="error",
                    path="policies",
                    message="Governance index requires a policies list.",
                )
            )
        else:
            data_dir = _gov_data_dir()
            seen: set[str] = set()
            for idx, entry in enumerate(policies):
                if not isinstance(entry, dict):
                    issues.append(
                        _issue(
                            source="semantic",
                            severity="error",
                            path=f"policies.{idx}",
                            message="Each policy entry must be an object.",
                        )
                    )
                    continue

                policy_key = str(entry.get("policy_key") or "").strip()
                filename = str(entry.get("filename") or "").strip()

                if not policy_key:
                    issues.append(
                        _issue(
                            source="semantic",
                            severity="error",
                            path=f"policies.{idx}.policy_key",
                            message="policy_key is required.",
                        )
                    )
                if not filename:
                    issues.append(
                        _issue(
                            source="semantic",
                            severity="error",
                            path=f"policies.{idx}.filename",
                            message="filename is required.",
                        )
                    )

                if policy_key:
                    if policy_key in seen:
                        issues.append(
                            _issue(
                                source="semantic",
                                severity="error",
                                path=f"policies.{idx}.policy_key",
                                message=f"Duplicate policy_key '{policy_key}'.",
                            )
                        )
                    seen.add(policy_key)

                if filename:
                    target = data_dir / filename
                    if not target.exists():
                        issues.append(
                            _issue(
                                source="semantic",
                                severity="warning",
                                path=f"policies.{idx}.filename",
                                message=(
                                    f"Referenced file '{filename}' "
                                    "does not exist."
                                ),
                            )
                        )

    has_errors = any(i["severity"] == "error" for i in issues)
    return (not has_errors, issues)


def _diff_lines(old_text: str, new_text: str) -> list[str]:
    return list(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile="current",
            tofile="proposed",
            lineterm="",
        )
    )


def _diff_summary(
    old_doc: dict[str, Any],
    new_doc: dict[str, Any],
) -> tuple[dict[str, list[str]], list[str]]:
    old_keys = set(old_doc.keys())
    new_keys = set(new_doc.keys())
    summary = {
        "added_keys": sorted(new_keys - old_keys),
        "removed_keys": sorted(old_keys - new_keys),
        "changed_keys": sorted(
            key
            for key in (old_keys & new_keys)
            if old_doc.get(key) != new_doc.get(key)
        ),
    }
    lines = [
        f"Added top-level keys: {', '.join(summary['added_keys']) or 'none'}",
        (
            "Removed top-level keys: "
            f"{', '.join(summary['removed_keys']) or 'none'}"
        ),
        (
            "Changed top-level keys: "
            f"{', '.join(summary['changed_keys']) or 'none'}"
        ),
    ]
    return (summary, lines)


def _atomic_write_json(dst: Path, doc: dict[str, Any]) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    backups = _gov_data_dir() / "_backups"
    backups.mkdir(parents=True, exist_ok=True)

    ts = now_iso8601_ms().replace(":", "").replace("-", "")
    backup_path = backups / f"{dst.name}.{ts}.bak"

    if dst.exists():
        backup_path.write_bytes(dst.read_bytes())
    else:
        backup_path.write_text("", encoding="utf-8")

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(dst.parent),
    ) as handle:
        handle.write(_json_text(doc))
        tmp_name = handle.name

    os.replace(tmp_name, dst)
    return str(backup_path)


def _policy_payload(
    *,
    key: str,
    doc: dict[str, Any],
    has_schema: bool,
    schema_ok: bool,
    schema_issues: list[dict[str, str]],
    semantic_ok: bool,
    semantic_issues: list[dict[str, str]],
) -> dict[str, Any]:
    normalized_text = _json_text(doc)
    current_hash = _sha256_bytes(normalized_text.encode("utf-8"))
    meta = doc.get("meta") or {}
    issues = [*schema_issues, *semantic_issues]

    return {
        "ok": True,
        "key": key,
        "title": str(meta.get("title") or key),
        "status": str(meta.get("status") or "unknown"),
        "version": str(meta.get("version") or ""),
        "focus": _infer_focus(doc, key),
        "domains": _extract_domains(doc),
        "meta": meta,
        "policy": doc,
        "has_schema": has_schema,
        "schema_ok": bool(schema_ok),
        "schema_error_count": sum(
            1 for issue in schema_issues if issue["severity"] == "error"
        ),
        "schema_warning_count": sum(
            1 for issue in schema_issues if issue["severity"] == "warning"
        ),
        "semantic_ok": bool(semantic_ok),
        "semantic_error_count": sum(
            1 for issue in semantic_issues if issue["severity"] == "error"
        ),
        "semantic_warning_count": sum(
            1 for issue in semantic_issues if issue["severity"] == "warning"
        ),
        "issue_count": len(issues),
        "issues": issues,
        "normalized_text": normalized_text,
        "current_hash": current_hash,
    }


def list_policies_impl(*, validate: bool = False) -> dict[str, Any]:
    data_dir = _gov_data_dir()
    items: list[dict[str, Any]] = []

    for path in sorted(data_dir.glob("policy_*.json")):
        key = path.stem
        doc = _read_json(path)
        schema_path = _schema_path_for(key)
        schema_ok_raw, schema_issues = (
            _maybe_validate(doc, schema_path) if validate else (None, [])
        )
        semantic_ok, semantic_issues = _semantic_validate(key=key, doc=doc)
        item = _policy_payload(
            key=key,
            doc=doc,
            has_schema=schema_path.exists(),
            schema_ok=True if schema_ok_raw is None else bool(schema_ok_raw),
            schema_issues=schema_issues,
            semantic_ok=semantic_ok,
            semantic_issues=semantic_issues,
        )
        items.append(item)

    return {"ok": True, "policies": items}


def get_policy_impl(
    key: str,
    *,
    validate: bool = False,
) -> dict[str, Any]:
    path = _policy_path_for(key)
    if not path.exists():
        return {"ok": False, "error": "not_found"}

    doc = _read_json(path)
    schema_path = _schema_path_for(key)
    schema_ok_raw, schema_issues = (
        _maybe_validate(doc, schema_path) if validate else (None, [])
    )
    semantic_ok, semantic_issues = _semantic_validate(key=key, doc=doc)

    return _policy_payload(
        key=key,
        doc=doc,
        has_schema=schema_path.exists(),
        schema_ok=True if schema_ok_raw is None else bool(schema_ok_raw),
        schema_issues=schema_issues,
        semantic_ok=semantic_ok,
        semantic_issues=semantic_issues,
    )


def preview_update_impl(
    *,
    key: str,
    new_policy: dict[str, Any],
    base_hash: str | None = None,
) -> dict[str, Any]:
    current = get_policy_impl(key=key, validate=True)
    if not current.get("ok"):
        return {"ok": False, "error": "not_found"}

    old_doc = current["policy"]
    new_doc = _canonicalize(new_policy)

    schema_path = _schema_path_for(key)
    schema_ok_raw, schema_issues = _maybe_validate(new_doc, schema_path)
    semantic_ok, semantic_issues = _semantic_validate(key=key, doc=new_doc)

    normalized_text = _json_text(new_doc)
    proposed_hash = _sha256_bytes(normalized_text.encode("utf-8"))
    diff_summary, change_summary = _diff_summary(old_doc, new_doc)
    diff_lines = _diff_lines(
        str(current.get("normalized_text") or "{}\n"),
        normalized_text,
    )

    schema_ok = True if schema_ok_raw is None else bool(schema_ok_raw)
    issues = [*schema_issues, *semantic_issues]
    base_hash_matches = (
        True if not base_hash else base_hash == current["current_hash"]
    )
    commit_allowed = schema_ok and semantic_ok and base_hash_matches

    if not base_hash_matches:
        issues.append(
            _issue(
                source="stale_preview",
                severity="error",
                path="",
                message=(
                    "The current file changed since detail view was loaded. "
                    "Reload the policy and preview again."
                ),
            )
        )

    return {
        "ok": True,
        "dry_run": True,
        "key": key,
        "current_hash": current["current_hash"],
        "proposed_hash": proposed_hash,
        "normalized_text": normalized_text,
        "has_schema": schema_path.exists(),
        "schema_ok": schema_ok,
        "semantic_ok": semantic_ok,
        "issues": issues,
        "issue_count": len(issues),
        "diff_summary": diff_summary,
        "diff_lines": diff_lines,
        "change_summary": change_summary,
        "base_hash_matches": base_hash_matches,
        "commit_allowed": commit_allowed,
    }


def commit_update_impl(
    *,
    key: str,
    new_policy: dict[str, Any],
    actor_ulid: str,
    reason: str,
    base_hash: str | None = None,
    proposed_hash: str | None = None,
) -> dict[str, Any]:
    preview = preview_update_impl(
        key=key,
        new_policy=new_policy,
        base_hash=base_hash,
    )
    if not preview.get("ok"):
        return preview

    if not preview.get("commit_allowed"):
        return {
            "ok": False,
            "error": "preview_not_committable",
            "issues": preview.get("issues") or [],
        }

    normalized_text = str(preview["normalized_text"])
    actual_proposed_hash = _sha256_bytes(normalized_text.encode("utf-8"))
    if proposed_hash and proposed_hash != actual_proposed_hash:
        return {
            "ok": False,
            "error": "stale_preview",
            "issues": [
                _issue(
                    source="stale_preview",
                    severity="error",
                    path="",
                    message=(
                        "The proposed hash no longer matches the previewed "
                        "document. Preview again before commit."
                    ),
                )
            ],
        }

    path = _policy_path_for(key)
    old_hash = str(preview["current_hash"])
    backup_ref = _atomic_write_json(path, _canonicalize(new_policy))
    new_hash = _sha256_bytes(path.read_bytes())

    event_bus.emit(
        domain="governance",
        operation="governance_policy_updated",
        request_id=new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=None,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "key": key,
            "old_sha256": old_hash,
            "new_sha256": new_hash,
            "backup_ref": backup_ref,
            "reason": reason,
        },
    )

    return {
        "ok": True,
        "committed": True,
        "key": key,
        "old_hash": old_hash,
        "new_hash": new_hash,
        "backup_ref": backup_ref,
        "reason": reason,
    }
