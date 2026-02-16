# app/slices/entity/outes_wizard.py

from __future__ import annotations

from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.extensions import db
from app.extensions.auth_ctx import current_actor_ulid
from app.extensions.contracts import governance_v2
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
from .routes import bp

LABELS = {
    "customer": "Customer (person served)",
    "resource": "Resource (provider/org)",
    "sponsor": "Sponsor (donor/org)",
    "civilian": "Civilian (general person)",
}


# -----------------
# Role Code Helper
# -----------------


def _role_choices() -> list[tuple[str, str]]:
    allowed = governance_v2.list_entity_role_codes()
    allowed = [
        r
        for r in allowed
        if r in ("customer", "resource", "sponsor", "civilian")
    ]
    return [(r, LABELS.get(r, r)) for r in allowed]


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


@bp.route(
    "/wizard/person", methods=["GET", "POST"], endpoint="wizard_person_core"
)
def wizard_person_core():
    form = PersonCoreForm()
    if not form.validate_on_submit():
        return render_template("entity/wizard_person_core.html", form=form)

    try:
        dto = wiz.wizard_create_person_core(
            first_name=form.first_name.data or "",
            last_name=form.last_name.data or "",
            preferred_name=form.preferred_name.data,
            dob=form.dob.data,
            last_4=form.last_4.data,
            request_id=ensure_request_id,
            actor_ulid=current_actor_ulid,
        )
        db.session.commit()
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
        return render_template("entity/wizard_person_core.html", form=form)

    except Exception:
        db.session.rollback()

        # Log with correlation id only; NO PII.
        current_app.logger.exception(
            "wizard_person_core failed",
            extra={
                "request_id": ensure_request_id(),
                "entity_ulid": dto.entity_ulid,
                "op": "entity_wizard_person_core",
            },
        )

        flash("Unexpected error while saving person core data.", "error")
        # In dev you may prefer `raise` here; in prod, render.
        return render_template("entity/wizard_person_core.html", form=form)


@bp.route(
    "/wizard/org",
    methods=["GET", "POST"],
    endpoint="wizard_org_core",
)
def wizard_org_core():
    form = OrgCoreForm()
    if not form.validate_on_submit():
        return render_template("entity/wizard_org_core.html", form=form)

    try:
        dto = wiz.wizard_create_org_core(
            legal_name=form.legal_name.data or "",
            dba_name=form.dba_name.data,
            ein=form.ein.data,
            request_id=ensure_request_id,
            actor_ulid=current_actor_ulid,
        )
        db.session.commit()
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
        return render_template("entity/wizard_org_core.html", form=form)

    except Exception:
        db.session.rollback()

        # Log with correlation id only; NO PII.
        current_app.logger.exception(
            "wizard_org_core failed",
            extra={
                "request_id": ensure_request_id(),
                "entity_ulid": dto.entity_ulid,
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
    if not form.validate_on_submit():
        return render_template("entity/wizard_contact.html", form=form)
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
        return render_template("entity/wizard_contact.html", form=form)

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
        return render_template("entity/wizard_contact.html", form=form)


@bp.route(
    "/wizard/<entity_ulid>/address",
    methods=["GET", "POST"],
    endpoint="wizard_address",
)
def wizard_address(entity_ulid: str):
    form = AddressForm()
    if not form.validate_on_submit():
        return render_template("entity/wizard_address.html", form=form)
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
        return redirect(
            url_for("entity.wizard_next", entity_ulid=dto.entity_ulid)
        )
    except WizardError as exc:
        db.session.rollback()

        # Attach field-level errors back onto the form when provided.
        if exc.field_errors:
            for field_name, msg in exc.field_errors.items():
                if hasattr(form, field_name):
                    getattr(form, field_name).errors.append(msg)

        flash(exc.user_message, "error")
        return render_template("entity/wizard_address.html", form=form)

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
        return render_template("entity/wizard_address.html", form=form)


@bp.get("/wizard/<entity_ulid>/role")
def wizard_role_get(entity_ulid: str):
    form = RoleForm()
    form.role.choices = _role_choices()

    return render_template(
        "entity/wizard_role.html", form=form, entity_ulid=entity_ulid
    )


@bp.post("/wizard/<entity_ulid>/role")
def wizard_role_post(entity_ulid: str):
    form = RoleForm()
    form.role.choices = _role_choices()  # MUST set on POST too

    if not form.validate_on_submit():
        return render_template(
            "entity/wizard_role.html", form=form, entity_ulid=entity_ulid
        )

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
        return render_template("entity/wizard_role.html", form=form)

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
        # In dev you may prefer `raise` here; in prod, render.
        return render_template("entity/wizard_role.html", form=form)


@bp.get("/wizard/<entity_ulid>/next")
def wizard_next_intake_or_onboard(entity_ulid: str):
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
