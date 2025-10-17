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

from . import bp
from . import services as svc


@bp.get("/hello")
@login_required
def hello():
    return render_template("entity/hello.html")


# -------------------------
# People listing
# -------------------------
@bp.get("/people")
@login_required
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
@login_required
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
    kind = (request.form.get("kind") or "person").strip().lower()
    actor = current_actor_id()
    req_id = f"req-entity-create-{int(time.time() * 1000)}"

    try:
        if kind == "org":
            legal_name = (request.form.get("legal_name") or "").strip()
            dba = request.form.get("doing_business_as") or None
            ein = request.form.get("ein") or None

            entity_id = entity_api.ensure_org(
                legal_name=legal_name,
                doing_business_as=dba,
                ein=ein,
                request_id=req_id,
                actor_id=actor,
            )

        else:
            # default: person
            first = (request.form.get("first_name") or "").strip()
            last = (request.form.get("last_name") or "").strip()
            email = request.form.get("email") or None
            phone = request.form.get("phone") or None

            entity_id = entity_api.ensure_person(
                first_name=first,
                last_name=last,
                email=email,
                phone=phone,
                request_id=req_id,
                actor_id=actor,
            )

        # Optional address upsert (for either kind)
        addr1 = request.form.get("addr1")
        city = request.form.get("city")
        state = request.form.get("state")
        postal = request.form.get("postal")
        if any([addr1, city, state, postal]):
            if state and state.upper() not in us_state_codes():
                flash(f"Invalid state: {state}", "error")
                return redirect(url_for("entity.create_form"))
            entity_api.upsert_address(
                entity_id=entity_id,
                purpose=(request.form.get("addr_purpose") or "physical"),
                address1=addr1 or "",
                address2=request.form.get("addr2"),
                city=city or "",
                state=state or "",
                postal=postal or "",
                tz=request.form.get("tz") or None,
                request_id=req_id,
                actor_id=actor,
            )

        # Optional role grant
        role_code = (request.form.get("role") or "").strip().lower()
        if role_code:
            entity_api.ensure_role(
                entity_id=entity_id,
                role_code=role_code,
                request_id=req_id,
                actor_id=actor,
            )

        flash("Entity saved.", "success")
        return redirect(url_for("entity.hello"))

    except ValueError as ve:
        flash(str(ve), "error")
        return redirect(url_for("entity.hello"))
