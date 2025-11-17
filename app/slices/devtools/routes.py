# app/slices/devtools/routes.py
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, session
from flask_login import current_user
from sqlalchemy import select, text
from werkzeug.exceptions import BadRequest, Forbidden

from app.extensions import db
from app.lib.chrono import utcnow_naive
from app.lib.security import ASSUME_KEY
from app.slices.auth.decorators import rbac
from app.slices.entity.models import EntityOrg, EntityPerson, EntityRole
from app.slices.entity.services import (
    allowed_role_codes,
    create_org_entity,
    create_person_entity,
    ensure_role,
)


def _json():
    return request.get_json(silent=True) or {}


# -----------------
# RBAC/Domain
# Dev Stub (fake)
# (admin/governor)
# -----------------


# Stub to bypass your existing RBAC decorator
def _require_admin_stub():
    # Simple guard for dev-only write helpers
    stub = request.headers.get("X-Auth-Stub")
    if stub != "admin":
        raise Forbidden("admin stub required")


def _is_admin_stub() -> bool:
    return (request.headers.get("X-Auth-Stub") or "").lower() == "admin"


# -----------------
# Governance catalogs
# Read available roles
# from contract layer
# (contract first, file fallback)
# -----------------

try:
    from app.extensions.contracts.governance_v2 import (
        role_catalogs as _gov_role_catalogs,
    )
except Exception:
    _gov_role_catalogs = None


# -----------------
# Blueprint registration
# There's alot going on in here
# -----------------

bp = Blueprint("devtools", __name__, url_prefix="/dev")

bp_api = Blueprint("devtools_api", __name__, url_prefix="/api/dev")

bp_api_v2 = Blueprint("devtools_api_v2", __name__)

bp_api_public = Blueprint("devtools_api_public", __name__)

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
    from flask import jsonify, session

    return jsonify(
        {
            "assumed_rbac": session.get("assumed_rbac"),
            "assumed_domain_roles": session.get("assumed_domain_roles"),
        }
    )


@bp.get("/debug/user")
def debug_user():
    from flask import jsonify

    u = getattr(g, "current_user", None)
    return jsonify(
        {
            "has_user": bool(u),
            "roles": getattr(u, "roles", None),
            "domain_roles": getattr(u, "domain_roles", None),
            "is_admin": getattr(u, "is_admin", None),
            "is_authenticated": getattr(u, "is_authenticated", None),
        }
    )


@bp.get("/whoami")
def dev_whoami():
    # reflect the stub auth hook (headers or auto-admin)
    roles = getattr(current_user, "roles", []) or []
    domain_roles = getattr(current_user, "domain_roles", []) or []
    is_admin = getattr(current_user, "is_admin", False)
    is_auth = getattr(current_user, "is_authenticated", False)
    return (
        jsonify(
            {
                "has_user": bool(is_auth),
                "roles": roles,
                "domain_roles": domain_roles,
                "is_admin": bool(is_admin),
                "is_authenticated": bool(is_auth),
            }
        ),
        200,
    )


# -----------------
# API routes
# Wellness Checks &
# Helpers/Seeders
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
    from app.slices.customers.models import Customer
    from app.slices.entity.models import Entity
    from app.slices.logistics.models import InventoryItem
    from app.slices.resources.models import Resource
    from app.slices.sponsors.models import Sponsor

    s = db.session
    return jsonify(
        {
            "entities": s.query(Entity).count(),
            "customers": s.query(Customer).count(),
            "resources": s.query(Resource).count(),
            "sponsors": s.query(Sponsor).count(),
            "skus": s.query(InventoryItem).count(),
        }
    )


# -----------------
# API_PUBLIC
# -----------------


@bp_api_public.get("/api/ledger/events")
def api_ledger_events():
    """Return a bounded list of recent ledger events (or empty)."""
    limit = request.args.get("limit", type=int) or 10
    limit = max(1, min(limit, 200))
    events = []
    try:
        from app.extensions import db
        from app.slices.ledger.models import LedgerEvent

        q = (
            db.session.query(LedgerEvent)
            .order_by(LedgerEvent.happened_at.asc(), LedgerEvent.ulid.asc())
            .limit(limit)
        )
        for e in q:
            events.append(
                {
                    "ulid": getattr(e, "ulid", None),
                    "domain": getattr(e, "domain", None),
                    "operation": getattr(e, "operation", None),
                    "happened_at": getattr(e, "happened_at", None),
                    "prev_hash_hex": getattr(e, "prev_hash_hex", None),
                    "curr_hash_hex": getattr(e, "curr_hash_hex", None),
                }
            )
    except Exception:
        events = []
    return jsonify({"ok": True, "events": events, "limit": limit})


@bp_api_public.get("/entity/people")
def entity_people_list():
    """
    Read-only list of people (dev/test browse endpoint).
    Returns light DTOs: entity_ulid, first_name, last_name, created_at.
    """
    s = db.session
    q = (
        s.query(EntityPerson)
        .order_by(EntityPerson.created_at_utc.desc())
        .limit(50)
    )
    items = [
        {
            "entity_ulid": p.entity_ulid,
            "first_name": p.first_name,
            "last_name": p.last_name,
            "created_at": (p.created_at_utc or "")[:23] + "Z"
            if p.created_at_utc
            else None,
        }
        for p in q
    ]
    return jsonify({"count": len(items), "items": items}), 200


@bp_api_public.get("/entity/orgs")
def entity_orgs_list():
    """
    Read-only list of orgs. Defaults to role=resource.
    Supports: ?role=all (no filter) or a specific domain role (e.g., sponsor).
    """
    role = (request.args.get("role") or "resource").strip().lower()
    s = db.session
    base = s.query(EntityOrg)

    if role != "all":
        base = base.join(
            EntityRole,
            EntityRole.entity_ulid == EntityOrg.entity_ulid,
        ).filter(EntityRole.role_code == role)

    q = base.order_by(EntityOrg.created_at_utc.desc()).limit(50)
    items = [
        {
            "entity_ulid": o.entity_ulid,
            "legal_name": o.legal_name,
            "ein": o.ein,
            "created_at": (o.created_at_utc or "")[:23] + "Z"
            if o.created_at_utc
            else None,
        }
        for o in q
    ]
    return jsonify({"count": len(items), "role": role, "items": items}), 200


# -----------------
# API V2
# helpers
# (local, read-only)
# -----------------


def _root() -> Path:
    return Path(current_app.root_path)


def _gov_data_dir() -> Path:
    # app root -> app/slices/governance/data
    return _root() / "slices" / "governance" / "data"


def _safe_json_load(p: Path) -> dict:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# -----------------
# v2 contracts:
# sample DTOs
# (read-only shims)
# -----------------


def _sample_entity():
    return {
        "ulid": "01EXAMPLEENTITYULID0000000000",
        "kind": "person",
        "created_at": "2025-01-01T00:00:00.000Z",
        "updated_at": "2025-01-01T00:00:00.000Z",
    }


def _sample_customer():
    return {
        "ulid": "01EXAMPLECUSTOMERULID0000000",
        "entity_ulid": "01EXAMPLEENTITYULID0000000000",
        "created_at": "2025-01-01T00:00:00.000Z",
    }


def _sample_resource():
    return {
        "ulid": "01EXAMPLERESOURCEULID0000000",
        "entity_ulid": "01EXAMPLEENTITYULID0000000000",
        "classifications": ["basic_needs/mobile_shower"],
        "created_at": "2025-01-01T00:00:00.000Z",
    }


def _sample_sponsor():
    return {
        "ulid": "01EXAMPLESponsorULID00000000",
        "entity_ulid": "01EXAMPLEENTITYULID0000000000",
        "status": "active",
        "created_at": "2025-01-01T00:00:00.000Z",
    }


# --- v2 sample DTOs (read-only) ---------------------------------------------


@bp_api_v2.get("/api/v2/customers/sample")
def v2_customers_sample():
    return jsonify(
        {
            "ulid": "01EXAMPLECUSTOMERULID0000000",
            "entity_ulid": "01EXAMPLEENTITYULID0000000000",
            "created_at": "2025-01-01T00:00:00.000Z",
        }
    )


@bp_api_v2.get("/api/v2/sponsors/sample")
def v2_sponsors_sample():
    return jsonify(
        {
            "ulid": "01EXAMPLESponsorULID00000000",
            "entity_ulid": "01EXAMPLEENTITYULID0000000000",
            "status": "active",
            "created_at": "2025-01-01T00:00:00.000Z",
        }
    )


@bp_api_v2.get("/api/v2/resources/sample")
def v2_resources_sample():
    return jsonify(
        {
            "ulid": "01EXAMPLERESOURCEULID0000000",
            "entity_ulid": "01EXAMPLEENTITYULID0000000000",
            "classifications": ["basic_needs/mobile_shower"],
            "created_at": "2025-01-01T00:00:00.000Z",
        }
    )


@bp_api_v2.get("/api/v2/entity/sample")
def v2_entity_sample():
    return jsonify(
        {
            "ulid": "01EXAMPLEENTITYULID0000000000",
            "kind": "person",
            "created_at": "2025-01-01T00:00:00.000Z",
            "updated_at": "2025-01-01T00:00:00.000Z",
        }
    )


# --- v2 RBAC role catalog (read-only) ---------------------------------------


def _rbac_roles_payload():
    # Keep dev/tests stable and contract-free here.
    # (Auth contract can be introduced later if we want.)
    return {"roles": ["admin", "auditor", "staff", "user"]}


@bp_api_v2.get("/api/v2/auth/roles")
def v2_auth_roles():
    return jsonify(_rbac_roles_payload())


# Optional dev alias (same payload) to preserve older tooling
@bp_api_v2.get("/auth/roles")
def v2_auth_roles_alias():
    return jsonify(_rbac_roles_payload())


@bp_api_v2.get("/api/v2/governance/roles")
def v2_governance_roles():
    from app.extensions.contracts.governance_v2 import (
        ContractError,
        get_role_catalogs,
    )

    try:
        return jsonify(get_role_catalogs()), 200
    except ContractError as e:
        current_app.logger.error(
            {
                "event": "contract_error",
                "where": "governance_v2.get_role_catalogs",
                "error": str(e),
            }
        )
        return jsonify({"error": "internal_error"}), 500


# -----------------
# v2 governance:
# policy index/get
# (read-only;
# optional validate)
# -----------------


@bp_api_v2.get("/governance/policies")
def v2_governance_policies_index():
    validate = request.args.get("validate") in ("1", "true", "yes")
    data_dir = _gov_data_dir()
    items = []
    for p in sorted(data_dir.glob("policy_*.json")):
        obj = _safe_json_load(p)
        has_schema = (data_dir / "schemas" / f"{p.stem}.schema.json").exists()
        item = {
            "key": p.stem,
            "filename": p.name,
            "domains": list(obj.get("domain_roles", [])),
            "focus": (
                "domain_assignment"
                if "assignment_rules" in obj
                else p.stem.replace("_", "-")
            ),
            "has_schema": bool(has_schema),
        }
        if validate and has_schema:
            try:
                import jsonschema
                from jsonschema import Draft202012Validator

                schema = json.loads(
                    (
                        data_dir / "schemas" / f"{p.stem}.schema.json"
                    ).read_text(encoding="utf-8")
                )
                Draft202012Validator.check_schema(schema)
                errs = sorted(
                    Draft202012Validator(schema).iter_errors(obj),
                    key=lambda e: e.path,
                )
                item["schema_valid"] = len(errs) == 0
                item["schema_errors"] = (
                    [
                        f"{'.'.join(map(str, e.path)) or '(root)'}: {e.message}"
                        for e in errs[:10]
                    ]
                    if errs
                    else []
                )
            except Exception as e:
                item["schema_valid"] = False
                item["schema_errors"] = [f"validator-error: {e}"]
        else:
            item["schema_valid"] = None
            item["schema_errors"] = []
        items.append(item)
    return jsonify({"ok": True, "policies": items})


@bp_api_v2.get("/governance/policies/<string:key>")
def v2_governance_policies_get(key: str):
    validate = request.args.get("validate") in ("1", "true", "yes")
    data_dir = _gov_data_dir()
    p = data_dir / f"{key}.json"
    if not p.exists():
        return jsonify({"ok": False, "error": "not_found"}), 404
    obj = _safe_json_load(p)
    out = {
        "ok": True,
        "key": key,
        "policy": obj,
        "schema_valid": None,
        "schema_errors": [],
    }
    if validate:
        schema_path = data_dir / "schemas" / f"{key}.schema.json"
        if schema_path.exists():
            try:
                import jsonschema
                from jsonschema import Draft202012Validator

                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)
                errs = sorted(
                    Draft202012Validator(schema).iter_errors(obj),
                    key=lambda e: e.path,
                )
                out["schema_valid"] = len(errs) == 0
                out["schema_errors"] = (
                    [
                        f"{'.'.join(map(str, e.path)) or '(root)'}: {e.message}"
                        for e in errs[:10]
                    ]
                    if errs
                    else []
                )
            except Exception as e:
                out["schema_valid"] = False
                out["schema_errors"] = [f"validator-error: {e}"]
    return jsonify(out)


# -----------------
# API V2 Forms
# simulated
# form data
# -----------------


@bp_api_v2.post("/dev/forms/entity.person.create")
def v2_dev_form_entity_person_create():
    """
    Dev-only: fake form POST that exercises the real create_person_entity service
    + emits a canonical ledger event. No policy read here (person create has none).
    """
    if not _is_admin_stub():
        return jsonify({"error": "forbidden"}), 403

    p = _json()
    first = (p.get("first_name") or "").strip()
    last = (p.get("last_name") or "").strip()
    if not first or not last:
        return jsonify({"error": "first_name and last_name required"}), 400

    s = db.session
    try:
        dto = create_person_entity(
            first_name=first, last_name=last, session=s
        )

        s.commit()
        return jsonify({"ok": True, "person": dto}), 201
    except Exception as e:
        s.rollback()
        current_app.logger.exception("dev_form_person_create_error")
        return jsonify({"error": "internal_error"}), 500


@bp_api_v2.post("/dev/forms/entity.org.create")
def v2_dev_form_entity_org_create():
    """
    Dev-only: fake form POST → real ensure_org service (idempotent on EIN).
    """
    if not _is_admin_stub():
        return jsonify({"error": "forbidden"}), 403

    p = _json()
    legal = (p.get("legal_name") or "").strip()
    ein = (p.get("ein") or "").strip() or None
    dba = (p.get("dba_name") or "").strip() or None

    if not legal or not ein:
        return jsonify({"error": "legal_name and ein required"}), 400

    s = db.session
    try:
        from app.slices.entity import services as esvc

        ent_ulid = esvc.ensure_org(
            legal_name=legal,
            dba_name=dba,
            ein=ein,
            request_id="01DEVTOOLSFAKEORG00000000",
            actor_ulid=None,
        )
        s.commit()

        # light DTO for the response
        from app.slices.entity.models import EntityOrg

        org = (
            db.session.query(EntityOrg)
            .filter_by(entity_ulid=ent_ulid)
            .first()
        )
        dto = esvc._org_to_dto(org) if org else {"entity_ulid": ent_ulid}

        return jsonify({"ok": True, "org": dto}), 201
    except ValueError as ve:
        s.rollback()
        return jsonify({"error": "invalid", "detail": str(ve)}), 422
    except Exception:
        s.rollback()
        current_app.logger.exception("dev_form_org_create_error")
        return jsonify({"error": "internal_error"}), 500


@bp_api_v2.post("/dev/forms/entity.role.assign")
def v2_dev_form_entity_role_assign():
    if not _is_admin_stub():
        return jsonify({"error": "forbidden"}), 403

    p = _json()
    entity_ulid = (p.get("entity_ulid") or "").strip()
    role_code = (p.get("role") or "").strip().lower()
    if not entity_ulid or not role_code:
        return jsonify({"error": "entity_ulid and role required"}), 400

    try:
        from app.extensions.contracts.governance_v2 import get_role_catalogs

        cats = get_role_catalogs()  # {"roles": [...], ...}
        allowed = set((cats.get("roles") or []))
        if role_code not in allowed:
            return (
                jsonify(
                    {
                        "error": "invalid_role",
                        "role": role_code,
                        "allowed": sorted(allowed),
                    }
                ),
                422,
            )
    except Exception:
        current_app.logger.exception("gov_role_catalogs_error")
        return jsonify({"error": "policy_read_error"}), 503

    s = db.session
    try:
        ensure_role(
            entity_ulid=entity_ulid,
            role=role_code,
            request_id="01DEVTOOLSFAKEROLE0000000",
            actor_ulid=None,
        )
        s.commit()
        return jsonify({"ok": True}), 201
    except Exception:
        s.rollback()
        current_app.logger.exception("dev_form_role_assign_error")
        return jsonify({"error": "internal_error"}), 500


# -----------------
# API V2 Entity
# End to End
# CRUD Tests
# -----------------


@bp_api_v2.post("/dev/fake/entity/person")
def v2_dev_fake_create_person():
    _require_admin_stub()
    p = request.get_json(silent=True) or {}
    fn = (p.get("first_name") or "").strip()
    ln = (p.get("last_name") or "").strip()
    pn = (p.get("preferred_name") or None) or None
    if not fn or not ln:
        raise BadRequest("first_name and last_name are required")

    s = db.session
    try:
        from app.slices.entity import services as esvc

        # Use deterministic request_id in dev to make tests predictable
        ent_ulid = esvc.ensure_person(
            first_name=fn,
            last_name=ln,
            email=p.get("email"),
            phone=p.get("phone"),
            request_id="01DEVTOOLSFAKEPERSON0000000",
            actor_ulid=None,
        )
        s.commit()
        # Re-read DTO-ish view (optional; lightweight)
        dto = esvc.person_view(ent_ulid) or {"entity_ulid": ent_ulid}
        return jsonify({"ok": True, "person": dto}), 201
    except Exception:
        s.rollback()
        current_app.logger.exception("dev_fake_create_person_error")
        return jsonify({"error": "internal_error"}), 500


@bp_api_v2.post("/dev/fake/entity/org")
def v2_dev_fake_create_org():
    _require_admin_stub()
    p = request.get_json(silent=True) or {}
    legal = (p.get("legal_name") or "").strip()
    dba = (p.get("dba_name") or None) or None
    ein = (p.get("ein") or "").strip() or None
    if not legal:
        raise BadRequest("legal_name is required")

    s = db.session
    try:
        from app.slices.entity import services as esvc

        ent_ulid = esvc.ensure_org(
            legal_name=legal,
            dba_name=dba,
            ein=ein,
            request_id="01DEVTOOLSFAKEORG00000000",
            actor_ulid=None,
        )
        s.commit()
        # quick DTO
        org = (
            db.session.query(EntityOrg)
            .filter_by(entity_ulid=ent_ulid)
            .first()
        )
        dto = esvc._org_to_dto(org) if org else {"entity_ulid": ent_ulid}
        return jsonify({"ok": True, "org": dto}), 201
    except Exception:
        s.rollback()
        current_app.logger.exception("dev_fake_create_org_error")
        return jsonify({"error": "internal_error"}), 500


@bp_api_v2.post("/dev/fake/entity/role")
def v2_dev_fake_assign_role():
    _require_admin_stub()
    p = request.get_json(silent=True) or {}
    entity_ulid = (p.get("entity_ulid") or "").strip()
    role = (p.get("role") or "").strip().lower()
    if not entity_ulid or not role:
        raise BadRequest("entity_ulid and role are required")

    s = db.session
    try:
        from app.slices.entity import services as esvc

        esvc.ensure_role(
            entity_ulid=entity_ulid,
            role=role,
            request_id="01DEVTOOLSFAKEROLE0000000",
            actor_ulid=None,
        )
        s.commit()
        return (
            jsonify(
                {
                    "ok": True,
                    "assigned": {"entity_ulid": entity_ulid, "role": role},
                }
            ),
            201,
        )
    except ValueError as ve:
        s.rollback()
        # likely "Role 'x' not allowed by policy"
        return jsonify({"error": "invalid", "detail": str(ve)}), 422
    except Exception:
        s.rollback()
        current_app.logger.exception("dev_fake_assign_role_error")
        return jsonify({"error": "internal_error"}), 500
