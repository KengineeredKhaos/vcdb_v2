# app/slices/entity/routes.py
from __future__ import annotations

import time

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import (
    allowed_role_codes,
    current_actor_id,
    entity_api,
)
from app.extensions.contracts.entity import v2 as entity_contract
from app.lib.geo import us_states
from app.lib.ids import new_ulid
from app.lib.security import require_permission, require_roles_any

from . import bp
from . import services as svc


@bp.get("/hello")
@login_required
def hello():
    return render_template("entity/hello.html")


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
@require_permission("entity:pii:read")
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
    if role and role not in set(allowed_role_codes()):
        return jsonify({"ok": False, "error": f"invalid role '{role}'"}), 400

    if role:
        rows, total = svc.list_people_with_role(role=role, page=page, per=per)
    else:
        rows, total = svc.list_people(page=page, per=per)

    return (
        jsonify(
            {
                "ok": True,
                "data": rows,
                "page": page,
                "per_page": per,
                "pages": (total + per - 1) // per,
                "total": total,
            }
        ),
        200,
    )


# -------------------------
# Orgs listing
# -------------------------
@bp.get("/orgs")
@require_permission("entity:pii:read")
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

    allowed = set(allowed_role_codes())
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

    rows, total = svc.list_orgs(roles=roles, page=page, per=per)

    return (
        jsonify(
            {
                "ok": True,
                "data": rows,
                "roles": roles,
                "page": page,
                "per_page": per,
                "pages": (total + per - 1) // per,
                "total": total,
            }
        ),
        200,
    )


@bp.get("/create")
@login_required
def create_form():
    """Render the new-entity form with dropdown choices."""
    return render_template(
        "entity/create.html",
        role_codes=allowed_role_codes(),
        states=us_state_choices,
    )


@bp.post("/create")
@login_required
def create():
    """
    Minimal create handler.
    Supports either:
      kind=person: first_name, last_name, email?, phone?, (optional address*)
      kind=org   : legal_name, doing_business_as?, ein?, (optional address*)

    Optional role assignment: role=customer|resource|sponsor|...

    Address fields (optional, for either kind):
      addr_purpose, addr1, addr2, city, state, postal, tz
    """

    req_id = new_ulid()
    actor = current_actor_id()

    env = entity_contract.ContractEnvelope(
        request_id=req_id, actor_id=actor, dry_run=False
    )

    kind = (request.form.get("kind") or "person").strip().lower()
    if kind == "org":
        res = entity_contract.ensure_org(
            env,
            legal_name=(request.form.get("legal_name") or "").strip(),
            dba_name=request.form.get("doing_business_as") or None,
            ein=request.form.get("ein") or None,
        )
        entity_id = res["entity_ulid"]
    else:
        res = entity_contract.ensure_person(
            env,
            first_name=(request.form.get("first_name") or "").strip(),
            last_name=(request.form.get("last_name") or "").strip(),
            email=request.form.get("email") or None,
            phone=request.form.get("phone") or None,
        )
        entity_id = res["entity_ulid"]

    # address (optional) — call your service/contract as appropriate
    # role (optional) — continue to use contract v2
    role_code = (request.form.get("role") or "").strip().lower()
    if role_code:
        entity_contract.add_entity_role(env, entity_id, role_code)

    flash("Entity saved.", "success")
    return redirect(url_for("entity.hello"))
