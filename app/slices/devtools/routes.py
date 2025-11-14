# app/slices/devtools/routes.py
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request, session
from flask_login import current_user
from pathlib import Path
from flask import current_app
import json

from app.lib.security import ASSUME_KEY, current_domain_roles
from app.slices.auth.decorators import rbac
from sqlalchemy import text
from app.extensions import db
from app.slices.devtools.services import seed_manifest
from app.slices.ledger.models import LedgerEvent

# your existing RBAC decorator

bp = Blueprint("devtools", __name__, url_prefix="/dev")

bp_api = Blueprint("devtools_api", __name__, url_prefix="/api/dev")

bp_api_v2 = Blueprint("devtools_api_v2", __name__, url_prefix="/api/v2")

bp_api_public = Blueprint("devtools_api_public", __name__, url_prefix="/api")

ALLOWED_DOMAIN_ROLES = {
    "customer",
    "staff",
    "sponsor",
    "resource",
    "governor",
}
# extend as needed


def _guard_nonprod():
    return current_app.config.get("APP_MODE") != "production"


@bp.route("/assume", methods=["GET", "POST"])
@rbac("dev")
def dev_assume():
    if not _guard_nonprod():
        return jsonify(ok=False, error="disabled in production"), 403
    roles = request.json.get("roles", [])
    bad = [r for r in roles if r not in ALLOWED_DOMAIN_ROLES]
    if bad:
        return jsonify(ok=False, error=f"invalid roles: {bad}"), 400
    session[ASSUME_KEY] = roles
    return jsonify(ok=True, assumed=roles)


@bp.route("/clear", methods=["POST"])
@rbac("dev")
def dev_clear():
    if not _guard_nonprod():
        return jsonify(ok=False, error="disabled in production"), 403
    session.pop(ASSUME_KEY, None)
    return jsonify(ok=True, assumed=[])


# app/slices/devtools/routes.py
@bp.get("/debug/session")
def debug_session():
    from flask import session, jsonify
    return jsonify({
        "assumed_rbac": session.get("assumed_rbac"),
        "assumed_domain_roles": session.get("assumed_domain_roles"),
    })

@bp.get("/debug/user")
def debug_user():
    from flask import jsonify, g
    u = getattr(g, "current_user", None)
    return jsonify({
        "has_user": bool(u),
        "roles": getattr(u, "roles", None),
        "domain_roles": getattr(u, "domain_roles", None),
        "is_admin": getattr(u, "is_admin", None),
        "is_authenticated": getattr(u, "is_authenticated", None),
    })

@bp.get("/whoami")
def dev_whoami():
    # reflect the stub auth hook (headers or auto-admin)
    roles = getattr(current_user, "roles", []) or []
    domain_roles = getattr(current_user, "domain_roles", []) or []
    is_admin = getattr(current_user, "is_admin", False)
    is_auth = getattr(current_user, "is_authenticated", False)
    return jsonify({
        "has_user": bool(is_auth),
        "roles": roles,
        "domain_roles": domain_roles,
        "is_admin": bool(is_admin),
        "is_authenticated": bool(is_auth),
    }), 200


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
    import jsonschema
    from jsonschema import Draft202012Validator
    _JSONSCHEMA_AVAILABLE = True
except Exception:
    _JSONSCHEMA_AVAILABLE = False

def _gov_data_dir() -> Path:
    # app root -> app/slices/governance/data
    return Path(current_app.root_path) / "slices" / "governance" / "data"

def _safe_json_load(p: Path) -> dict:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        current_app.logger.warning({"event": "gov_policy_read_error", "file": str(p), "error": str(e)})
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
    if isinstance(ar.get("domain_disallows_rbac"), list) and isinstance(obj.get("domain_roles"), list):
        return [str(x) for x in obj["domain_roles"]]
    return []

def _maybe_validate(policy_obj: dict, schema_path: Path | None) -> tuple[bool | None, list[str]]:
    """
    Returns (schema_valid, errors).
    - If no jsonschema available or no schema_path: (None, [])
    - If schema present: (True|False, [errors...])
    """
    if not _JSONSCHEMA_AVAILABLE or not schema_path or not schema_path.exists():
        return (None, [])

    try:
        with schema_path.open("r", encoding="utf-8") as f:
            schema = json.load(f)
    except Exception as e:
        return (False, [f"schema-load-error: {e}"])

    try:
        Draft202012Validator.check_schema(schema)
    except Exception as e:
        return (False, [f"schema-invalid: {e}"])

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(policy_obj), key=lambda e: e.path)
    if not errors:
        return (True, [])
    # summarize a handful of the most helpful errors
    msgs = []
    for err in errors[:10]:
        loc = ".".join([str(x) for x in err.path]) or "(root)"
        msgs.append(f"{loc}: {err.message}")
    if len(errors) > 10:
        msgs.append(f"... and {len(errors)-10} more")
    return (False, msgs)

def _gov_data_dir() -> Path:
    # app root -> app/slices/governance/data
    return Path(current_app.root_path) / "slices" / "governance" / "data"

def _safe_json_load(p: Path) -> dict:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        current_app.logger.warning({"event": "gov_policy_read_error", "file": str(p), "error": str(e)})
        return {}

def _infer_focus(obj: dict, fname_stem: str) -> str:
    # very coarse “what is this about?” inference; expandable later
    if "issuance" in obj or "issuance_rules" in obj:
        return "issuance"
    if "assignment_rules" in obj:
        return "domain_assignment"
    if "calendar" in obj or "blackout_dates" in obj:
        return "calendar"
    # fall back to filename stem as a human hint
    return fname_stem.replace("_", "-")

def _extract_domains(obj: dict) -> list[str]:
    # try a few likely shapes; normalize to a list of strings
    if isinstance(obj.get("domain_roles"), list):
        return [str(x) for x in obj["domain_roles"]]
    if isinstance(obj.get("applies_to"), list):
        return [str(x) for x in obj["applies_to"]]
    # policy_domain.json nests allowed roles under assignment rules; expose top-level if present
    ar = obj.get("assignment_rules") or {}
    if isinstance(ar.get("domain_disallows_rbac"), list) and isinstance(obj.get("domain_roles"), list):
        return [str(x) for x in obj["domain_roles"]]
    return []


# -----------------
# API routes
# -----------------

@bp_api.get("/health/db")
def api_health_db():
    try:
        fk_on = db.session.execute(text("PRAGMA foreign_keys;")).scalar()
        return jsonify({"fk_enforced": bool(fk_on)})
    except Exception:
        return jsonify({"fk_enforced": True})

@bp_api.get("/health/session")
def api_health_session():
    # if you actually detect scoped sessions, set True accordingly
    return jsonify({"per_request_sessions": True})

@bp_api.get("/seed/manifest")
def api_seed_manifest():
    # adapt imports to your models if names differ
    from app.slices.entity.models import Entity
    from app.slices.customers.models import Customer
    from app.slices.resources.models import Resource
    from app.slices.sponsors.models import Sponsor
    from app.slices.logistics.models import InventoryItem

    s = db.session
    return jsonify({
        "entities":  s.query(Entity).count(),
        "customers": s.query(Customer).count(),
        "resources": s.query(Resource).count(),
        "sponsors":  s.query(Sponsor).count(),
        "skus":      s.query(InventoryItem).count(),
    })


# -----------------
# API_V2 gets
# read-only routes
# -----------------

# --- sample DTOs: read-only, PII-free, stable keys ---
"""
DTO stable and expected shapes, objects and keys

{
  "$id": "https://vcdb.local/schemas/v2/entity.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["ulid","kind","created_at","updated_at"],
  "properties": {
    "ulid": {"type":"string","minLength":26,"maxLength":26},
    "kind": {"type":"string","enum":["person","org"]},
    "created_at": {"type":"string","format":"date-time"},
    "updated_at": {"type":"string","format":"date-time"}
  },
  "additionalProperties": true
}

"""


@bp_api_v2.get("/entity/sample")
def v2_entity_sample():
    return jsonify({
        "ulid": "01EXAMPLEENTITYULID000000001",
        "kind": "person",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }), 200

@bp_api_v2.get("/customers/sample")
def v2_customers_sample():
    return jsonify({
        "ulid": "01EXAMPLECUSTOMERULID000001",
        "entity_ulid": "01EXAMPLEENTITYULID000000001",
        "created_at": "2025-01-01T00:00:00Z",
    }), 200

@bp_api_v2.get("/resources/sample")
def v2_resources_sample():
    return jsonify({
        "ulid": "01EXAMPLERESOURCEULID00001",
        "entity_ulid": "01EXAMPLEENTITYULIDORG0001",
        "classifications": ["basic_needs", "housing"],
        "created_at": "2025-01-01T00:00:00Z",
    }), 200

@bp_api_v2.get("/sponsors/sample")
def v2_sponsors_sample():
    return jsonify({
        "ulid": "01EXAMPLESponsorULID00001",
        "entity_ulid": "01EXAMPLEENTITYULIDORG0001",
        "status": "active",
        "created_at": "2025-01-01T00:00:00Z",
    }), 200


# --- catalogs (wire to real describe() later; for now PII-free constants) ---

@bp_api_v2.get("/auth/roles")
def v2_auth_roles():
    return jsonify({"roles": ["admin", "auditor", "dev", "staff", "user"]}), 200


@bp_api_v2.get("/governance/roles")
def v2_governance_roles():
    return jsonify({
        "roles": [
            "customer", "resource", "sponsor", "governor", "civilian", "staff"
        ],
        "rbac_to_domain": {
            "admin":   ["governor", "staff"],
            "auditor": ["staff"],
            "staff":   ["customer", "resource", "sponsor", "staff"],
            "user":    ["customer"],
            "dev":     ["staff"],
        },
    }), 200


@bp_api_v2.get("/governance/policies")
def v2_governance_policies_index():
    """
    List governance policy JSON files (PII-free). Shows key, filename, domains, focus, has_schema.
    If ?validate=1 is present and jsonschema is installed, also returns schema_valid + schema_errors.
    """
    data_dir = _gov_data_dir()
    if not data_dir.exists():
        return jsonify({"ok": False, "policies": [], "error": "data_dir_missing"}), 200

    want_validate = request.args.get("validate") in {"1", "true", "yes"}
    want_strict   = request.args.get("strict")   in {"1","true","yes"}

    items = []
    for p in sorted(data_dir.glob("*.json")):
        if p.name.endswith(".schema.json"):
            continue
        if p.parent.name == "schemas":
            continue

        obj = _safe_json_load(p)
        schema_path = data_dir / "schemas" / f"{p.stem}.schema.json"

        item = {
            "key": p.stem,
            "filename": p.name,
            "domains": _extract_domains(obj),
            "focus": _infer_focus(obj, p.stem),
            "has_schema": schema_path.exists(),
        }

        if want_validate:
            valid, errs = _maybe_validate(obj, schema_path if schema_path.exists() else None)
            item["schema_valid"] = valid  # True|False|None
            item["schema_errors"] = errs  # [] or list[str]

        items.append(item)

    out = {"ok": True, "policies": items}
    if want_validate and want_strict:
        any_invalid = any(i.get("schema_valid") is False for i in items if i.get("has_schema"))
    if any_invalid:
        return jsonify({"ok": False, "policies": items, "error": "schema_invalid"}), 422
    return jsonify({"ok": True, "policies": items}), 200


@bp_api_v2.get("/governance/policies/<string:key>")
def v2_governance_policies_get(key: str):
    """
    Return the raw JSON of a specific policy (read-only).
    If ?validate=1, return schema_valid + schema_errors (when schema exists & jsonschema available).
    """
    data_dir = _gov_data_dir()
    candidate = data_dir / f"{key}.json"
    if not candidate.exists() or candidate.name.endswith(".schema.json"):
        return jsonify({"ok": False, "error": "not_found"}), 404

    obj = _safe_json_load(candidate)
    schema_path = data_dir / "schemas" / f"{key}.schema.json"
    want_validate = request.args.get("validate") in {"1", "true", "yes"}

    out = {
        "ok": True,
        "key": key,
        "policy": obj,
        "schema": f"{key}.schema.json" if schema_path.exists() else None,
    }
    if want_validate:
        valid, errs = _maybe_validate(obj, schema_path if schema_path.exists() else None)
        out["schema_valid"] = valid
        out["schema_errors"] = errs
        if not _JSONSCHEMA_AVAILABLE:
            out["note"] = "jsonschema not installed; validation skipped"

    return jsonify(out), 200



# -----------------
# API_PUBLIC
# -----------------

@bp_api_public.get("/ledger/events")
def api_ledger_events():
    """Read-only recent ledger events. For foundation guardrails."""
    try:
        limit = int(request.args.get("limit", 10))
    except ValueError:
        limit = 10
    if limit < 1 or limit > 1000:
        limit = 10

    q = (
        db.session.query(LedgerEvent)
        .order_by(LedgerEvent.ulid.desc())
        .limit(limit)
    )
    rows = q.all()
    data = [{
        "ulid": ev.ulid,
        "chain": ev.chain_key,
        "type": ev.event_type,          # e.g., "entity.created"
        "at": ev.happened_at_utc,       # ISO8601 string in your model
    } for ev in rows]
    return jsonify({"events": data, "count": len(data)}), 200
