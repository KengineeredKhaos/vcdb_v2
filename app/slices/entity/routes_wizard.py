# app/slices/entity/outes_wizard.py

from __future__ import annotations

from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_required
from sqlalchemy import select

from app.extensions import db
from app.extensions.auth_ctx import current_actor_ulid
from app.extensions.contracts import governance_v2
from app.lib.ids import new_ulid
from app.lib.request_ctx import ensure_request_id, use_request_ctx

from . import services_wizard as wiz
from .errors_wizard import WizardError
from .forms import (
    AddressForm,
    ContactForm,
    OrgCoreForm,
    PersonCoreForm,
    RoleForm,
)
from .models import Entity, EntityRole
from .routes import bp

# -----------------
# Constants & Keys
# -----------------

LABELS = {
    "customer": "Customer (person served)",
    "resource": "Resource (provider/org)",
    "sponsor": "Sponsor (donor/org)",
    "civilian": "Civilian (general person)",
}


_WIZ_ACTIVE_ENTITY_KEY = "wiz_active_entity_ulid"


# -----------------
# Role Code Helper
# -----------------


def _role_choices() -> list[tuple[str, str]]:
    allowed = governance_v2.list_entity_role_codes()
    allowed = [
        r
        for r in allowed
        if r
        in (
            "customer",
            "resource",
            "sponsor",
            "civilian",
        )
    ]
    return [(r, LABELS.get(r, r)) for r in allowed]


# ------------------
# Nonce Helpers
# -----------------


def _wiz_nonce_key(step: str, entity_ulid: str | None) -> str:
    if entity_ulid:
        return f"wiz:{step}:{entity_ulid}"
    return f"wiz:{step}"


def _wiz_issue_nonce(step: str, entity_ulid: str | None) -> str:
    token = new_ulid()
    session[_wiz_nonce_key(step, entity_ulid)] = token
    return token


def _wiz_expect_nonce(step: str, entity_ulid: str | None) -> str | None:
    return session.get(_wiz_nonce_key(step, entity_ulid))


def _wiz_consume_nonce(step: str, entity_ulid: str | None) -> None:
    session.pop(_wiz_nonce_key(step, entity_ulid), None)


def _wiz_active_entity_ulid() -> str | None:
    return session.get(_WIZ_ACTIVE_ENTITY_KEY)


def _wiz_operation_request_id(entity_ulid: str) -> str:
    ent = db.session.get(Entity, entity_ulid)
    if not ent or getattr(ent, "archived_at", None):
        raise LookupError("wizard entity not found")
    return (ent.intake_request_id or "").strip() or ensure_request_id()


def _wiz_next_endpoint(entity_ulid: str) -> str:
    """Return the next endpoint from persisted entity intake truth."""
    ent = db.session.get(Entity, entity_ulid)
    if not ent or getattr(ent, "archived_at", None):
        raise LookupError("wizard entity not found")

    step = (ent.intake_step or "").strip().lower()
    if step == wiz.INTAKE_STEP_CONTACT:
        return "entity.wizard_contact"
    if step == wiz.INTAKE_STEP_ADDRESS:
        return "entity.wizard_address"
    if step == wiz.INTAKE_STEP_ROLE:
        return "entity.wizard_role_get"
    if step == wiz.INTAKE_STEP_HANDOFF:
        return "entity.wizard_next"

    return wiz.wizard_next_step(entity_ulid=entity_ulid)


# -----------------
# Wizard Helpers
# -----------------


def _wiz_clear_active() -> None:
    """Clear wizard active-entity and nonce keys."""
    active = session.pop(_WIZ_ACTIVE_ENTITY_KEY, None)
    if active:
        suffix = f":{active}"
        for k in list(session.keys()):
            if k.startswith("wiz:") and k.endswith(suffix):
                session.pop(k, None)
    for k in ("wiz:person_core", "wiz:org_core"):
        session.pop(k, None)


# -----------------
# Wizard Routes
# -----------------


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/wizard/start")
@login_required
def wizard_start():
    if (request.args.get("reset") or "").strip() in ("1", "true", "yes"):
        _wiz_clear_active()
        flash("Wizard reset. Start a new entity.", "warning")
    return render_template("entity/wizard_start.html")


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.post("/wizard/start")
@login_required
def wizard_start_post():
    active = session.get(_WIZ_ACTIVE_ENTITY_KEY)
    if active:
        try:
            flash("Wizard already in progress — resuming.", "warning")
            next_ep = _wiz_next_endpoint(active)
            return redirect(url_for(next_ep, entity_ulid=active))
        except Exception:
            # Common after reseed / DB reset: session points at a dead ULID.
            _wiz_clear_active()
            flash(
                "Previous wizard session was stale. Starting new.", "warning"
            )

    kind = (request.form.get("kind") or "").strip().lower()
    if kind == "person":
        return redirect(url_for("entity.wizard_person_core"))
    if kind == "org":
        return redirect(url_for("entity.wizard_org_core"))
    flash("Pick person or org.", "error")
    return redirect(url_for("entity.wizard_start"))


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/wizard/person", methods=["GET", "POST"], endpoint="wizard_person_core"
)
@login_required
def wizard_person_core():
    form = PersonCoreForm()
    step = "person_core"
    if request.method == "GET":
        # No entity_ulid exists yet for the person/org core creation step.
        # If a wizard is already active, resume instead of starting new one.
        active = session.get(_WIZ_ACTIVE_ENTITY_KEY)
        if active:
            try:
                flash("Wizard already in progress — resuming.", "warning")
                next_ep = _wiz_next_endpoint(active)
                return redirect(url_for(next_ep, entity_ulid=active))
            except Exception:
                _wiz_clear_active()
                flash(
                    "Previous wizard session was stale. Start again.",
                    "warning",
                )

        wiz_nonce = _wiz_issue_nonce(step, None)
        return render_template(
            "entity/wizard_person_core.html",
            form=form,
            wiz_nonce=wiz_nonce,
        )

    # POST: stale-submit guard
    expected = _wiz_expect_nonce(step, None)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Start again.", "warning")
        return redirect(url_for("entity.wizard_start"))

    if not form.validate_on_submit():
        return render_template(
            "entity/wizard_person_core.html",
            form=form,
            wiz_nonce=expected,
        )
    _wiz_consume_nonce(step, None)
    dto = None
    rid = ensure_request_id()
    actor_ulid = current_actor_ulid()
    try:
        with use_request_ctx(rid, actor_ulid):
            dto = wiz.wizard_create_person_core(
                first_name=form.first_name.data or "",
                last_name=form.last_name.data or "",
                preferred_name=form.preferred_name.data,
                dob=form.dob.data,
                last_4=form.last_4.data,
                request_id=rid,
                actor_ulid=actor_ulid,
            )
            db.session.commit()

        # Lock browser session onto the created entity until completion/reset.
        session[_WIZ_ACTIVE_ENTITY_KEY] = dto.entity_ulid
        flash(f"Created: {dto.display_name}", "success")
        return redirect(url_for(dto.next_step, entity_ulid=dto.entity_ulid))
    except WizardError as exc:
        db.session.rollback()

        # Attach field-level errors back onto the form when provided.
        if exc.field_errors:
            for field_name, msg in exc.field_errors.items():
                if hasattr(form, field_name):
                    getattr(form, field_name).errors.append(msg)

        flash(exc.user_message, "error")
        return render_template(
            "entity/wizard_person_core.html",
            form=form,
            wiz_nonce=expected,
        )

    except Exception:
        db.session.rollback()

        # Log with correlation id only; NO PII.
        current_app.logger.exception(
            "wizard_person_core failed",
            extra={
                "request_id": rid,
                "entity_ulid": getattr(dto, "entity_ulid", None),
                "op": "entity_wizard_person_core",
            },
        )

        flash("Unexpected error while saving person core data.", "error")
        # In dev you may prefer `raise` here; in prod, render.
        return render_template(
            "entity/wizard_person_core.html",
            form=form,
            wiz_nonce=expected,
        )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route("/wizard/org", methods=["GET", "POST"], endpoint="wizard_org_core")
@login_required
def wizard_org_core():
    form = OrgCoreForm()
    step = "org_core"
    if request.method == "GET":
        # No entity_ulid exists yet for the person/org core creation step.
        # If a wizard is already active, resume instead of starting new one.
        active = session.get(_WIZ_ACTIVE_ENTITY_KEY)
        if active:
            try:
                flash("Wizard already in progress — resuming.", "warning")
                next_ep = _wiz_next_endpoint(active)
                return redirect(url_for(next_ep, entity_ulid=active))
            except Exception:
                _wiz_clear_active()
                flash(
                    "Previous wizard session was stale. Start again.",
                    "warning",
                )

        wiz_nonce = _wiz_issue_nonce(step, None)
        return render_template(
            "entity/wizard_org_core.html",
            form=form,
            wiz_nonce=wiz_nonce,
        )

    # POST: stale-submit guard
    expected = _wiz_expect_nonce(step, None)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Start again.", "warning")
        return redirect(url_for("entity.wizard_start"))
    if not form.validate_on_submit():
        return render_template(
            "entity/wizard_org_core.html",
            form=form,
            wiz_nonce=expected,
        )
    _wiz_consume_nonce(step, None)
    dto = None
    rid = ensure_request_id()
    actor_ulid = current_actor_ulid()
    try:
        with use_request_ctx(rid, actor_ulid):
            dto = wiz.wizard_create_org_core(
                legal_name=form.legal_name.data or "",
                dba_name=form.dba_name.data,
                ein=form.ein.data,
                request_id=rid,
                actor_ulid=actor_ulid,
            )
            db.session.commit()

        # Lock browser session onto the created entity until completion/reset.
        session[_WIZ_ACTIVE_ENTITY_KEY] = dto.entity_ulid
        flash(f"Created: {dto.display_name}", "success")
        return redirect(url_for(dto.next_step, entity_ulid=dto.entity_ulid))
    except WizardError as exc:
        db.session.rollback()

        # Attach field-level errors back onto the form when provided.
        if exc.field_errors:
            for field_name, msg in exc.field_errors.items():
                if hasattr(form, field_name):
                    getattr(form, field_name).errors.append(msg)

        flash(exc.user_message, "error")
        return render_template(
            "entity/wizard_org_core.html",
            form=form,
            wiz_nonce=expected,
        )

    except Exception:
        db.session.rollback()

        # Log with correlation id only; NO PII.
        current_app.logger.exception(
            "wizard_org_core failed",
            extra={
                "request_id": rid,
                "entity_ulid": getattr(dto, "entity_ulid", None),
                "op": "entity_wizard_org_core",
            },
        )

        flash("Unexpected error while saving org core data.", "error")
        # In dev you may prefer `raise` here; in prod, render.
        return render_template("entity/wizard_org_core.html", form=form)


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/wizard/<entity_ulid>/contact",
    methods=["GET", "POST"],
    endpoint="wizard_contact",
)
@login_required
def wizard_contact(entity_ulid: str):
    form = ContactForm()
    step = "contact"

    if request.method == "GET":
        current = _wiz_next_endpoint(entity_ulid)
        if current != request.endpoint:
            return redirect(url_for(current, entity_ulid=entity_ulid))

        wiz_nonce = _wiz_issue_nonce(step, entity_ulid)
        return render_template(
            "entity/wizard_contact.html",
            form=form,
            entity_ulid=entity_ulid,
            wiz_nonce=wiz_nonce,
        )

    # POST: stale-submit guard (Back button, duplicate tab, etc.)
    expected = _wiz_expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash(
            "That page is stale. Continue from the wizard flow.",
            "warning",
        )
        next_ep = _wiz_next_endpoint(entity_ulid)
        return redirect(url_for(next_ep, entity_ulid=entity_ulid))

    if not form.validate_on_submit():
        # Keep nonce so the user can fix validation errors and re-submit.
        return render_template(
            "entity/wizard_contact.html",
            form=form,
            entity_ulid=entity_ulid,
            wiz_nonce=expected,
        )
    # Consume nonce only on successful mutation path.
    _wiz_consume_nonce(step, entity_ulid)
    dto = None
    rid = _wiz_operation_request_id(entity_ulid)
    actor_ulid = current_actor_ulid()
    try:
        with use_request_ctx(rid, actor_ulid):
            dto = wiz.wizard_contact(
                entity_ulid=entity_ulid,
                email=form.email.data,
                phone=form.phone.data,
                request_id=rid,
                actor_ulid=actor_ulid,
            )
            db.session.commit()

        return redirect(url_for(dto.next_step, entity_ulid=dto.entity_ulid))

    except WizardError as exc:
        db.session.rollback()

        # Attach field-level errors back onto the form when provided.
        if exc.field_errors:
            for field_name, msg in exc.field_errors.items():
                if hasattr(form, field_name):
                    getattr(form, field_name).errors.append(msg)

        flash(exc.user_message, "error")
        return render_template(
            "entity/wizard_contact.html",
            form=form,
            entity_ulid=entity_ulid,
            wiz_nonce=expected,
        )

    except Exception:
        db.session.rollback()

        # Log with correlation id only; NO PII.
        current_app.logger.exception(
            "wizard_contact failed",
            extra={
                "request_id": rid,
                "entity_ulid": entity_ulid,
                "op": "entity_wizard_contact",
            },
        )

        flash("Unexpected error while saving contact data.", "error")
        # In dev you may prefer `raise` here; in prod, render.
        return render_template(
            "entity/wizard_contact.html",
            form=form,
            entity_ulid=entity_ulid,
            wiz_nonce=expected,
        )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/wizard/<entity_ulid>/address",
    methods=["GET", "POST"],
    endpoint="wizard_address",
)
@login_required
def wizard_address(entity_ulid: str):
    form = AddressForm()
    step = "address"

    if request.method == "GET":
        current = _wiz_next_endpoint(entity_ulid)
        if current != request.endpoint:
            return redirect(url_for(current, entity_ulid=entity_ulid))

        wiz_nonce = _wiz_issue_nonce(step, entity_ulid)
        return render_template(
            "entity/wizard_address.html",
            form=form,
            entity_ulid=entity_ulid,
            wiz_nonce=wiz_nonce,
        )

    # POST: stale-submit guard
    expected = _wiz_expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash(
            "That page is stale. Continue from the wizard flow.",
            "warning",
        )
        next_ep = _wiz_next_endpoint(entity_ulid)
        return redirect(url_for(next_ep, entity_ulid=entity_ulid))

    # Explicit operator bypass for "no address available right now".
    if (request.form.get("action") or "").strip().lower() == "skip":
        _wiz_consume_nonce(step, entity_ulid)
        rid = _wiz_operation_request_id(entity_ulid)
        actor_ulid = current_actor_ulid()
        dto = None
        try:
            with use_request_ctx(rid, actor_ulid):
                dto = wiz.wizard_defer_address(
                    entity_ulid=entity_ulid,
                    request_id=rid,
                    actor_ulid=actor_ulid,
                )
                db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "wizard_address_skip failed",
                extra={
                    "request_id": rid,
                    "entity_ulid": entity_ulid,
                    "op": "entity_wizard_address_skip",
                },
            )
            flash(
                "Unexpected error while deferring address data.",
                "error",
            )
            return render_template(
                "entity/wizard_address.html",
                form=form,
                entity_ulid=entity_ulid,
                wiz_nonce=expected,
            )

        flash(
            "Address deferred. You can add it later through Entity edit tools.",
            "warning",
        )
        return redirect(url_for(dto.next_step, entity_ulid=dto.entity_ulid))

    # Normal form validation: keep the same nonce on errors
    if not form.validate_on_submit():
        return render_template(
            "entity/wizard_address.html",
            form=form,
            entity_ulid=entity_ulid,
            wiz_nonce=expected,
        )
    _wiz_consume_nonce(step, entity_ulid)
    dto = None
    rid = _wiz_operation_request_id(entity_ulid)
    actor_ulid = current_actor_ulid()
    try:
        with use_request_ctx(rid, actor_ulid):
            dto = wiz.wizard_address(
                entity_ulid=entity_ulid,
                is_physical=form.is_physical.data,
                is_postal=form.is_postal.data,
                address1=form.address1.data,
                address2=form.address2.data,
                city=form.city.data,
                state=form.state.data,
                postal_code=form.postal_code.data,
                request_id=rid,
                actor_ulid=actor_ulid,
            )
            db.session.commit()
        return redirect(url_for(dto.next_step, entity_ulid=dto.entity_ulid))

    except WizardError as exc:
        db.session.rollback()

        # Attach field-level errors back onto the form when provided.
        if exc.field_errors:
            for field_name, msg in exc.field_errors.items():
                if hasattr(form, field_name):
                    getattr(form, field_name).errors.append(msg)

        flash(exc.user_message, "error")
        return render_template(
            "entity/wizard_address.html",
            form=form,
            entity_ulid=entity_ulid,
            wiz_nonce=expected,
        )

    except Exception:
        db.session.rollback()

        # Log with correlation id only; NO PII.
        current_app.logger.exception(
            "wizard_address failed",
            extra={
                "request_id": rid,
                "entity_ulid": entity_ulid,
                "op": "entity_wizard_address",
            },
        )

        flash("Unexpected error while saving address data.", "error")
        # In dev you may prefer `raise` here; in prod, render.
        return render_template(
            "entity/wizard_address.html",
            form=form,
            entity_ulid=entity_ulid,
            wiz_nonce=expected,
        )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/wizard/<entity_ulid>/role")
@login_required
def wizard_role_get(entity_ulid: str):
    current = _wiz_next_endpoint(entity_ulid)
    if current != request.endpoint:
        return redirect(url_for(current, entity_ulid=entity_ulid))
    form = RoleForm()
    step = "role"
    form.role.choices = _role_choices()
    wiz_nonce = _wiz_issue_nonce(step, entity_ulid)

    return render_template(
        "entity/wizard_role.html",
        form=form,
        entity_ulid=entity_ulid,
        wiz_nonce=wiz_nonce,
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.post("/wizard/<entity_ulid>/role")
@login_required
def wizard_role_post(entity_ulid: str):
    form = RoleForm()
    form.role.choices = _role_choices()
    step = "role"

    # POST: stale-submit guard
    expected = _wiz_expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash(
            "That page is stale. Continue from the wizard flow.",
            "warning",
        )
        next_ep = _wiz_next_endpoint(entity_ulid)
        return redirect(url_for(next_ep, entity_ulid=entity_ulid))

    if not form.validate_on_submit():
        return render_template(
            "entity/wizard_role.html",
            form=form,
            entity_ulid=entity_ulid,
            wiz_nonce=expected,
        )

    _wiz_consume_nonce(step, entity_ulid)
    dto = None
    rid = _wiz_operation_request_id(entity_ulid)
    actor_ulid = current_actor_ulid()
    try:
        with use_request_ctx(rid, actor_ulid):
            dto = wiz.wizard_set_single_role(
                entity_ulid=entity_ulid,
                role=form.role.data,
                request_id=rid,
                actor_ulid=actor_ulid,
            )
            db.session.commit()
        return redirect(url_for(dto.next_step, entity_ulid=entity_ulid))
    except WizardError as exc:
        db.session.rollback()

        # Attach field-level errors back onto the form when provided.
        if exc.field_errors:
            for field_name, msg in exc.field_errors.items():
                if hasattr(form, field_name):
                    getattr(form, field_name).errors.append(msg)

        flash(exc.user_message, "error")
        return render_template(
            "entity/wizard_role.html",
            form=form,
            entity_ulid=entity_ulid,
            wiz_nonce=expected,
        )

    except Exception:
        db.session.rollback()

        # Log with correlation id only; NO PII.
        current_app.logger.exception(
            "wizard_role failed",
            extra={
                "request_id": rid,
                "entity_ulid": entity_ulid,
                "op": "entity_wizard_role",
            },
        )
        flash("Unexpected error while saving domain role.", "error")
        return render_template(
            "entity/wizard_role.html",
            form=form,
            entity_ulid=entity_ulid,
            wiz_nonce=expected,
        )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/wizard/<entity_ulid>/next", endpoint="wizard_next")
@login_required
def wizard_next(entity_ulid: str):
    if session.get(_WIZ_ACTIVE_ENTITY_KEY) == entity_ulid:
        _wiz_clear_active()

    ent = db.session.get(Entity, entity_ulid)
    rid = (getattr(ent, "intake_request_id", None) or "").strip()
    if not rid:
        rid = ensure_request_id()

    if not ent:
        # If this happens, something upstream is wrong; but give a graceful exit
        flash("Entity not found.", "error")
        return redirect(url_for("entity.wizard_start"))  # or your index

    # collect ALL active roles
    roles = (
        db.session.execute(
            select(EntityRole.role).where(
                EntityRole.entity_ulid == entity_ulid,
                EntityRole.archived_at.is_(None),
            )
        )
        .scalars()
        .all()
    )

    role_codes = {str(r or "").strip().lower() for r in roles if r}

    kind = (ent.kind or "").strip().lower()

    actions: list[dict[str, str]] = []

    # Primary role-driven handoffs
    if "customer" in role_codes:
        actions.append(
            {
                "label": "Continue to Customer Intake",
                "url": url_for(
                    "customers.intake_start",
                    entity_ulid=entity_ulid,
                    request_id=rid,
                ),
            }
        )
    if "resource" in role_codes:
        actions.append(
            {
                "label": "Continue to Resource Onboarding",
                "url": url_for(
                    "resources.onboard_start",
                    entity_ulid=entity_ulid,
                    request_id=rid,
                ),
            }
        )
    if "sponsor" in role_codes:
        actions.append(
            {
                "label": "Continue to Sponsor Onboarding",
                "url": url_for(
                    "sponsors.onboard_start",
                    entity_ulid=entity_ulid,
                    request_id=rid,
                ),
            }
        )

    # POC “happy ending” for civilian persons:
    is_streamless_person = kind == "person" and not (
        {"customer", "resource", "sponsor"} & role_codes
    )
    if is_streamless_person:
        actions.append(
            {
                "label": "Link as Resource POC",
                "url": url_for(
                    "resources.poc_attach",
                    person_ulid=entity_ulid,
                    request_id=rid,
                ),
            }
        )
        actions.append(
            {
                "label": "Link as Sponsor POC",
                "url": url_for(
                    "sponsors.poc_attach",
                    person_ulid=entity_ulid,
                    request_id=rid,
                ),
            }
        )

    # Always provide a graceful exit
    actions.append(
        {
            "label": "Done (return to Entity)",
            "url": url_for("entity.wizard_start", reset=1),
        }
    )

    view_entity_url = None
    try:
        view_entity_url = url_for(
            "entity.view_entity",
            entity_ulid=entity_ulid,
            request_id=rid,
        )
    except Exception:
        view_entity_url = None

    return render_template(
        "entity/wizard_next.html",
        entity_ulid=entity_ulid,
        actions=actions,
        view_entity_url=view_entity_url,
    )
