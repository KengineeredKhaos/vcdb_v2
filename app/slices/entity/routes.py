# app/slices/entity/routes.py
from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required

from app.extensions import db
from app.extensions.auth_ctx import current_actor_ulid
from app.extensions.contracts import entity_v2 as entity_contract
from app.extensions.errors import ContractError
from app.lib.geo import us_states
from app.lib.ids import new_ulid
from app.lib.request_ctx import ensure_request_id
from app.lib.security import require_permission

from . import services as svc
from .forms import PersonCoreForm
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


# -----------------
# Wizard Routes
# -----------------


@bp.get("/wizard/start")
def wizard_start():
    return render_template("entity/wizard_start.html")


@bp.post("/wizard/start")
def wizard_start_post():
    kind = (request.form.get("kind") or "").strip().lower()
    if kind == "person":
        return redirect(url_for("entity.wizard_person_core"))
    if kind == "org":
        return redirect(url_for("entity.wizard_org_core"))
    flash("Pick person or org.", "error")
    return redirect(url_for("entity.wizard_start"))


# -----------------
# Canonical Path
# (USE AS EXAMPLE)
# -----------------


@bp.get("/wizard/person")
def wizard_person_core_get():
    form = PersonCoreForm()
    return render_template("entity/wizard_person_core.html", form=form)


@bp.post("/wizard/person")
def wizard_person_core_post():
    form = PersonCoreForm()
    if not form.validate_on_submit():
        return render_template("entity/wizard_person_core.html", form=form)

    try:
        dto = entity_contract.wizard_create_person_core(
            first_name=form.first_name.data or "",
            last_name=form.last_name.data or "",
            preferred_name=form.preferred_name.data,
            dob=form.dob.data,
            last_4=form.last_4.data,
        )
        db.session.commit()
        flash(f"Created: {dto.display_name}", "success")
        return redirect(url_for(dto.next_step, entity_ulid=dto.entity_ulid))
    except ContractError as exc:
        db.session.rollback()
        flash(exc.message or "Unable to create entity.", "error")
        return render_template("entity/wizard_person_core.html", form=form)


# -----------------
# END EXAMPLE PATH
# -----------------


@bp.get("/wizard/<entity_ulid>/contact")
def wizard_contact(entity_ulid: str):
    return render_template(
        "entity/wizard_contact.html",
        entity_ulid=entity_ulid,
    )


@bp.post("/wizard/<entity_ulid>/contact")
def wizard_contact_post(entity_ulid: str):
    payload = {
        "entity_ulid": entity_ulid,
        "contact": {
            "email": request.form.get("email"),
            "phone": request.form.get("phone"),
        },
    }

    entity_contract.wizard_set_contact_primary(
        payload=payload,
        request_id=ensure_request_id(),
        actor_ulid=current_actor_ulid(),
    )
    db.session.commit()
    return redirect(url_for("entity.wizard_address", entity_ulid=entity_ulid))


@bp.get("/wizard/<entity_ulid>/address")
def wizard_address(entity_ulid: str):
    return render_template(
        "entity/wizard_address.html",
        entity_ulid=entity_ulid,
    )


@bp.post("/wizard/<entity_ulid>/address")
def wizard_address_post(entity_ulid: str):
    payload = {
        "entity_ulid": entity_ulid,
        "address": {
            "is_physical": bool(request.form.get("is_physical")),
            "is_postal": bool(request.form.get("is_postal")),
            "address1": request.form.get("address1"),
            "address2": request.form.get("address2"),
            "city": request.form.get("city"),
            "state": request.form.get("state"),
            "postal_code": request.form.get("postal_code"),
        },
    }

    entity_contract.wizard_set_address_primary(
        payload=payload,
        request_id=ensure_request_id(),
        actor_ulid=current_actor_ulid(),
    )
    db.session.commit()
    return redirect(url_for("entity.wizard_next", entity_ulid=entity_ulid))


@bp.get("/wizard/<entity_ulid>/next")
def wizard_next(entity_ulid: str):
    # simplest for now: role comes from query string set at core step
    role = (request.args.get("role") or "").strip().lower()

    if role == "customer":
        next_url = url_for("customers.intake_start", entity_ulid=entity_ulid)
        label = "Continue to Customer Intake"
    elif role == "resource":
        next_url = url_for("resources.onboard_start", entity_ulid=entity_ulid)
        label = "Continue to Resource Onboarding"
    elif role == "sponsor":
        next_url = url_for("sponsors.onboard_start", entity_ulid=entity_ulid)
        label = "Continue to Sponsor Onboarding"
    else:
        next_url = url_for("entity.view_entity", entity_ulid=entity_ulid)
        label = "Finish (Entity Record)"

    return render_template(
        "entity/wizard_next.html",
        entity_ulid=entity_ulid,
        next_url=next_url,
        label=label,
    )


"""
Then you repeat the exact same pattern for:

/wizard/<entity_ulid>/contact
/wizard/<entity_ulid>/address
/wizard/<entity_ulid>/role
/wizard/<entity_ulid>/next

The only thing that changes is which contract function you call and which URL you
redirect to.
"""


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
    if role and role not in svc.allowed_role_codes():
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
    # derive 2-letter choices list once (if you keep this template var)
    us_state_choices = [s["code"] for s in us_states]
    # or however your helper exposes it
    return render_template(
        "entity/create.html",
        role_codes=sorted(svc.allowed_role_codes()),
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
    actor = current_actor_ulid()

    env = entity_contract.ContractEnvelope(
        request_id=req_id, actor_ulid=actor, dry_run=False
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
