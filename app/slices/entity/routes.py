# app/slices/entity/routes.py
from __future__ import annotations

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
)
from flask_login import login_required

from . import services as svc
from .models import EntityPerson

bp = Blueprint(
    "entity",
    __name__,
    template_folder="templates",
    static_folder=None,
    url_prefix="/entity",
)


@bp.get("/hello")
@login_required
def hello():
    return render_template("entity/hello.html")


# -----------------
# Helper Functions
# -----------------


# -----------------
# DTO (PII scrubbed)
# -----------------


def _person_to_dto(p: EntityPerson) -> dict:
    ent = p.entity
    return {
        "entity_ulid": ent.ulid if ent else None,
        "first_name": p.first_name[0] + "."
        if p.first_name
        else None,  # minimal
        "last_name": p.last_name,  # ok if policy allows; otherwise mask similarly
        "preferred_name": None,  # avoid PII here in lists
        "has_email": bool(
            ent and any(c.is_primary and c.email for c in ent.contacts or [])
        ),
        "has_phone": bool(
            ent and any(c.is_primary and c.phone for c in ent.contacts or [])
        ),
        "created_at_utc": ent.created_at_utc if ent else None,
        "updated_at_utc": ent.updated_at_utc if ent else None,
    }


# -------------------------
# People listing
# -------------------------
@bp.get("/people")
# @require_permission("entity:pii:read")
def list_people():
    """
    List people. Optional ?role=<role_code> to restrict by role.
    Pagination: ?page, ?per
    """
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except Exception:
        page = 1
    try:
        per = min(max(int(request.args.get("per", 20)), 1), 100)
    except Exception:
        per = 20

    role = (request.args.get("role") or "").strip().lower() or None
    if role and role not in svc.allowed_role_codes():
        return jsonify({"ok": False, "error": f"invalid role '{role}'"}), 400

    if role:
        p = svc.list_people_by_role(role=role, page=page, per_page=per)
    else:
        p = svc.list_people(page=page, per_page=per)

    return (
        jsonify(
            {
                "ok": True,
                "data": p.items,
                "page": p.page,
                "per_page": p.per_page,
                "pages": p.pages,
                "total": p.total,
            }
        ),
        200,
    )


# -------------------------
# Orgs listing
# -------------------------
@bp.get("/orgs")
# @require_permission("entity:pii:read")
def list_orgs():
    """
    List orgs. By default shows RESOURCE and SPONSOR orgs.
    Override with:
      - ?role=<single_role>
      - or ?roles=role1,role2
    Pagination: ?page, ?per
    """
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except Exception:
        page = 1
    try:
        per = min(max(int(request.args.get("per", 20)), 1), 100)
    except Exception:
        per = 20

    allowed = svc.allowed_role_codes()
    default_roles = [r for r in ("resource", "sponsor") if r in allowed]

    roles_param = (request.args.get("roles") or "").strip().lower()
    role_param = (request.args.get("role") or "").strip().lower()

    roles = None
    if roles_param:
        roles = [r.strip() for r in roles_param.split(",") if r.strip()]
    elif role_param:
        roles = [role_param]
    else:
        roles = default_roles

    bad = [r for r in roles if r not in allowed]
    if bad:
        return (
            jsonify(
                {"ok": False, "error": f"invalid roles: {', '.join(bad)}"}
            ),
            400,
        )

    p = svc.list_orgs_by_roles(roles=roles, page=page, per_page=per)

    return (
        jsonify(
            {
                "ok": True,
                "data": p.items,
                "roles": roles,
                "page": p.page,
                "per_page": p.per_page,
                "pages": p.pages,
                "total": p.total,
            }
        ),
        200,
    )
