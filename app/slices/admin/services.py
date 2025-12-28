# app/slices/admin/services.py
"""
VCDB v2 — Admin slice services

This module is the home for **admin-grade orchestration** that crosses slices.
In particular, it will own the *user-facing* side of Governance policy editing
and other maintenance tasks that are too dangerous for normal routes.

High-level responsibilities
===========================

* Policy editing façade
  - Accepts “edit this policy family” requests from Admin routes/CLI.
  - Talks to Governance via contracts / services_admin to:
        * preview changes (dry-run),
        * validate against JSON Schemas,
        * commit changes and emit a single Ledger event.
  - Never reaches directly into Governance models; all writes go through
    Governance’s own services / contracts.

* Admin-only maintenance flows
  - Officer / pro-tem assignments (via Governance contracts).
  - Future: ledger sweeps, integrity checks, backfills, diagnostics, etc.
  - Anything that looks like “fix & repair” for production data lives here,
    guarded by RBAC + domain roles.

Separation of concerns
======================

* Governance slice
  - Owns the *meaning* of policies and their storage.
  - ``governance.services`` is the read-only policy map and decision engine. :contentReference[oaicite:2]{index=2}
  - ``governance.services_admin`` owns the low-level write path for policies
    (schema validation, versioning, Ledger emission).

* Admin slice
  - Owns UX and workflows for *humans* changing policy:
        Admin UI / CLI
        -> Admin services (this module)
        -> governance_v2 / services_admin
        -> Policy table / JSON files (during migration)
        -> Ledger

"""
# ---------------------------------------------------------------------------
"""
Admin slice services.

This module centralizes "heavy lifting" for Admin workflows so that
`routes.py` can stay thin and boring. The first consumer is the
Governance/Auth policy editor:

    - load policy JSON for editing
    - validate a JSON payload against the appropriate schema/semantics
    - persist an updated policy and emit a ledger event

The rule of thumb is:
    * routes know about HTTP, forms/JSON, and flashing messages
    * services know about files, DB, event_bus, and other slices

Over time other Admin-only flows (cron dashboards, diagnostics, etc.)
should also live here.
"""

from __future__ import annotations  # noqa: E402, F404

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.extensions import db, event_bus
from app.extensions.policies import (
    AUTH_DATA,
    GOV_DATA,
    load_policy_governance_index,
    reload_policy_catalog,
    save_governance_policy,
)
from app.extensions.validate import validate_json_payload
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.lib.jsonutil import canonical_hash, read_json_file

# Optional semantic validators (safe to import if you added them)
try:  # pragma: no cover - import guard only
    from app.extensions.policy_semantics import (
        validate_issuance_semantics,
        validate_rbac_semantics,
    )
except Exception:  # pragma: no cover

    def validate_issuance_semantics(doc: dict) -> list[str]:
        return []

    def validate_rbac_semantics(doc: dict) -> list[str]:
        return []


# -----------------
# policy mapping helper
# -----------------


def _policy_key_and_schema_for_path(
    policy_path: Path,
) -> tuple[str, Optional[Path], str]:
    """
    Returns (policy_key, schema_path, root) where root is 'governance' or 'auth'.

    Uses the governance_index manifest for governance files.
    """
    p = policy_path.resolve()
    gov_root = GOV_DATA.resolve()
    auth_root = AUTH_DATA.resolve()

    if str(p).startswith(str(gov_root)):
        idx = load_policy_governance_index()
        for entry in idx.get("policies", []):
            if entry.get("filename") == policy_path.name:
                policy_key = entry["policy_key"]
                schema_fn = entry.get("schema_filename")
                schema_path = (GOV_DATA / schema_fn) if schema_fn else None
                return policy_key, schema_path, "governance"
        raise ValueError(
            f"Unknown governance policy filename: {policy_path.name}"
        )

    if str(p).startswith(str(auth_root)):
        if policy_path.name == "policy_rbac.json":
            schema_path = AUTH_DATA / "schemas" / "policy_rbac.schema.json"
            return (
                "rbac",
                schema_path if schema_path.exists() else None,
                "auth",
            )
        raise ValueError(
            f"Unsupported auth policy filename: {policy_path.name}"
        )

    raise FileNotFoundError("Policy not under allowed data roots")


# -----------------
# Policy
# editing services
# -----------------


@dataclass
class PolicyValidationResult:
    ok: bool
    errors: List[str]
    hints: List[str]
    doc: Dict[str, Any] | None


def _ensure_policy_path(policy_path: Path) -> Path:
    """
    Shared guard for policy files.

    - reject obvious traversal ("..")
    - require the file to exist
    - require it to live under one of the canonical data roots
      (governance or auth)
    """
    s = str(policy_path)
    if ".." in s:
        raise ValueError("Invalid policy path")

    if not policy_path.exists():
        raise FileNotFoundError("Policy not found")

    resolved = policy_path.resolve()
    gov_root = GOV_DATA.resolve()
    auth_root = AUTH_DATA.resolve()
    if not (
        str(resolved).startswith(str(gov_root))
        or str(resolved).startswith(str(auth_root))
    ):
        raise FileNotFoundError("Policy not under allowed data roots")

    return policy_path


def load_policy_text_for_edit(policy_path: Path) -> str:
    """
    Return the raw JSON text for a policy, after path guards.

    This is used by the HTML editor view.
    """
    p = _ensure_policy_path(policy_path)
    return p.read_text(encoding="utf-8")


def validate_policy_raw(
    policy_path: Path, raw: str
) -> PolicyValidationResult:
    try:
        doc = json.loads(raw)
    except Exception as e:
        return PolicyValidationResult(
            ok=False,
            errors=[f"JSON parse error: {e}"],
            hints=[],
            doc=None,
        )

    p = _ensure_policy_path(policy_path)

    errors: List[str] = []
    hints: List[str] = []

    try:
        policy_key, schema_path, root = _policy_key_and_schema_for_path(p)

        # Schema validation (if known)
        if schema_path is not None and schema_path.exists():
            validate_json_payload(doc, schema_path)

        # Semantic hints (optional)
        # Keep these keyed off policy_key, not filename.

        if policy_key == "logistics_issuance":
            hints += validate_issuance_semantics(doc)
        elif policy_key == "rbac":
            hints += validate_rbac_semantics(doc)

    except Exception as e:
        errors.append(f"validation error: {e}")

    return PolicyValidationResult(
        ok=not errors,
        errors=errors,
        hints=hints,
        doc=doc,
    )


def save_policy_raw(
    policy_path: Path, raw: str, *, actor_ulid: str | None
) -> PolicyValidationResult:
    result = validate_policy_raw(policy_path, raw)
    if not result.ok or result.doc is None:
        return result

    p = _ensure_policy_path(policy_path)
    policy_key, schema_path, root = _policy_key_and_schema_for_path(p)

    # capture before/after hashes for the ledger event
    old_doc = read_json_file(p, default=None)
    old_hash = canonical_hash(old_doc) if old_doc else None

    if root == "governance":
        # Uses manifest schema (already validated above, but this re-validates if schema exists)
        save_governance_policy(policy_key, result.doc)
    else:
        # auth/rbac write-path (keep simple for now)
        p.write_text(
            json.dumps(result.doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # hard reload step (your “last step”)
    reload_policy_catalog()

    # emit ledger event (names only)
    event_bus.emit(
        domain="admin",
        operation="policy.saved",
        request_id=new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=None,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "policy_key": policy_key,
            "filename": p.name,
            "old_hash": old_hash,
            "new_hash": canonical_hash(result.doc),
        },
    )
    db.session.commit()

    return result


# -----------------
# Cron
# admin services
# -----------------


def ack_cron_job(job_name: str, *, actor_ulid: str | None) -> None:
    """
    Acknowledge a cron error for the given job:

      - emit an admin:cron.job.acknowledged ledger event
      - clear last_error for the job in admin_cron_status

    The caller is responsible for:
      - ensuring job_name is non-empty
      - RBAC checks
      - flashing messages / redirecting
    """
    if not job_name:
        raise ValueError("job_name is required")

    event_bus.emit(
        domain="admin",
        operation="cron.job.acknowledged",
        request_id=new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=None,
        happened_at_utc=now_iso8601_ms(),
        refs={"job_name": job_name},
    )
    db.session.execute(
        text(
            "UPDATE admin_cron_status "
            "   SET last_error = NULL "
            " WHERE job_name = :job"
        ),
        {"job": job_name},
    )
    db.session.commit()


@dataclass
class CronRunResult:
    ok: bool
    job_name: str
    enqueued: bool


def _enqueue_job(job_name: str) -> bool:
    """
    Scheduler integration point.

    For now this is a stub that always returns False. In the future this
    can be wired to RQ, Celery, APScheduler, systemd timers, etc.
    """
    return False  # plug your scheduler later


def trigger_cron_job(
    job_name: str, *, actor_ulid: str | None
) -> CronRunResult:
    """
    Trigger a cron job "now" from the Admin UI:

      - emit an admin:cron.job.triggered ledger event
      - delegate to a scheduler stub (_enqueue_job)

    Returns a CronRunResult so the caller can decide whether to flash
    "job triggered" or "job not implemented".
    """
    if not job_name:
        raise ValueError("job_name is required")

    event_bus.emit(
        domain="admin",
        operation="cron.job.triggered",
        request_id=new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=None,
        happened_at_utc=now_iso8601_ms(),
        refs={"job_name": job_name},
    )
    enqueued = _enqueue_job(job_name)
    return CronRunResult(ok=enqueued, job_name=job_name, enqueued=enqueued)
