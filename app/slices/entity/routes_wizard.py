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
from sqlalchemy import select

from app.extensions import db
from app.extensions.auth_ctx import current_actor_ulid
from app.extensions.contracts import governance_v2
from app.lib.ids import new_ulid
from app.lib.request_ctx import ensure_request_id

from . import services_wizard as wiz
from .errors_wizard import WizardError
from .forms import (
    AddressForm,
    ContactForm,
    OrgCoreForm,
    PersonCoreForm,
    RoleForm,
)
from .models import EntityRole
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


# -----------------
# Wizard Routes
# -----------------


@bp.get("/wizard/start")
def wizard_start():
    if (request.args.get("reset") or "").strip() in ("1", "true", "yes"):
        session.pop(_WIZ_ACTIVE_ENTITY_KEY, None)
        flash("Wizard reset. Start a new entity.", "warning")
    return render_template("entity/wizard_start.html")


@bp.post("/wizard/start")
def wizard_start_post():
    active = session.get(_WIZ_ACTIVE_ENTITY_KEY)
    if active:
        flash("Wizard already in progress — resuming.", "warning")
        next_ep = wiz.wizard_next_step(entity_ulid=active)
        return redirect(url_for(next_ep, entity_ulid=active))
    kind = (request.form.get("kind") or "").strip().lower()
    if kind == "person":
        return redirect(url_for("entity.wizard_person_core"))
    if kind == "org":
        return redirect(url_for("entity.wizard_org_core"))
    flash("Pick person or org.", "error")
    return redirect(url_for("entity.wizard_start"))


@bp.route(
    "/wizard/person", methods=["GET", "POST"], endpoint="wizard_person_core"
)
def wizard_person_core():
    form = PersonCoreForm()
    step = "person_core"
    if request.method == "GET":
        # No entity_ulid exists yet for the person/org core creation step.
        # If a wizard is already active, resume instead of starting new one.
        active = session.get(_WIZ_ACTIVE_ENTITY_KEY)
        if active:
            flash("Wizard already in progress — resuming.", "warning")
            next_ep = wiz.wizard_next_step(entity_ulid=active)
            return redirect(url_for(next_ep, entity_ulid=active))

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
    try:
        dto = wiz.wizard_create_person_core(
            first_name=form.first_name.data or "",
            last_name=form.last_name.data or "",
            preferred_name=form.preferred_name.data,
            dob=form.dob.data,
            last_4=form.last_4.data,
            request_id=ensure_request_id(),
            actor_ulid=current_actor_ulid(),
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
                "request_id": ensure_request_id(),
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


@bp.route("/wizard/org", methods=["GET", "POST"], endpoint="wizard_org_core")
def wizard_org_core():
    form = OrgCoreForm()
    step = "org_core"
    if request.method == "GET":
        # No entity_ulid exists yet for the person/org core creation step.
        # If a wizard is already active, resume instead of starting new one.
        active = session.get(_WIZ_ACTIVE_ENTITY_KEY)
        if active:
            flash("Wizard already in progress — resuming.", "warning")
            next_ep = wiz.wizard_next_step(entity_ulid=active)
            return redirect(url_for(next_ep, entity_ulid=active))

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
            "entity/wizard_org_core.html",
            form=form,
            wiz_nonce=expected,
        )
    _wiz_consume_nonce(step, None)
    dto = None
    try:
        dto = wiz.wizard_create_org_core(
            legal_name=form.legal_name.data or "",
            dba_name=form.dba_name.data,
            ein=form.ein.data,
            request_id=ensure_request_id(),
            actor_ulid=current_actor_ulid(),
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
                "request_id": ensure_request_id(),
                "entity_ulid": getattr(dto, "entity_ulid", None),
                "op": "entity_wizard_org_core",
            },
        )

        flash("Unexpected error while saving org core data.", "error")
        # In dev you may prefer `raise` here; in prod, render.
        return render_template("entity/wizard_org_core.html", form=form)


@bp.route(
    "/wizard/<entity_ulid>/contact",
    methods=["GET", "POST"],
    endpoint="wizard_contact",
)
def wizard_contact(entity_ulid: str):
    form = ContactForm()
    step = "contact"

    if request.method == "GET":
        current = wiz.wizard_next_step(entity_ulid=entity_ulid)
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
        next_ep = wiz.wizard_next_step(entity_ulid=entity_ulid)
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
    try:
        dto = wiz.wizard_contact(
            entity_ulid=entity_ulid,
            email=form.email.data,
            phone=form.phone.data,
            request_id=ensure_request_id(),
            actor_ulid=current_actor_ulid(),
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
                "request_id": ensure_request_id(),
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


@bp.route(
    "/wizard/<entity_ulid>/address",
    methods=["GET", "POST"],
    endpoint="wizard_address",
)
def wizard_address(entity_ulid: str):
    form = AddressForm()
    step = "address"

    if request.method == "GET":
        current = wiz.wizard_next_step(entity_ulid=entity_ulid)
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
        next_ep = wiz.wizard_next_step(entity_ulid=entity_ulid)
        return redirect(url_for(next_ep, entity_ulid=entity_ulid))

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
    try:
        dto = wiz.wizard_address(
            entity_ulid=entity_ulid,
            is_physical=form.is_physical.data,
            is_postal=form.is_postal.data,
            address1=form.address1.data,
            address2=form.address2.data,
            city=form.city.data,
            state=form.state.data,
            postal_code=form.postal_code.data,
            request_id=ensure_request_id(),
            actor_ulid=current_actor_ulid(),
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
                "request_id": ensure_request_id(),
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


@bp.get("/wizard/<entity_ulid>/role")
def wizard_role_get(entity_ulid: str):
    current = wiz.wizard_next_step(entity_ulid=entity_ulid)
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


@bp.post("/wizard/<entity_ulid>/role")
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
        next_ep = wiz.wizard_next_step(entity_ulid=entity_ulid)
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
    try:
        dto = wiz.wizard_set_single_role(
            entity_ulid=entity_ulid,
            role=form.role.data,
            request_id=ensure_request_id(),
            actor_ulid=current_actor_ulid(),
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
                "request_id": ensure_request_id(),
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


@bp.get("/wizard/<entity_ulid>/next", endpoint="wizard_next")
def wizard_next(entity_ulid: str):
    role = db.session.execute(
        select(EntityRole)
        .where(
            EntityRole.entity_ulid == entity_ulid,
            EntityRole.archived_at.is_(None),
        )
        .limit(1)
    ).scalar_one_or_none()

    role_code = (role.role if role else "").strip().lower()

    if role_code == "customer":
        next_url = url_for("customers.intake_start", entity_ulid=entity_ulid)
        label = "Continue to Customer Intake"
    elif role_code == "resource":
        next_url = url_for("resources.onboard_start", entity_ulid=entity_ulid)
        label = "Continue to Resource Onboarding"
    elif role_code == "sponsor":
        next_url = url_for("sponsors.onboard_start", entity_ulid=entity_ulid)
        label = "Continue to Sponsor Onboarding"
    else:
        next_url = url_for("entity.list_people", entity_ulid=entity_ulid)
        label = "Finish (Entity Record)"

    return render_template(
        "entity/wizard_next.html",
        entity_ulid=entity_ulid,
        next_url=next_url,
        label=label,
    )
