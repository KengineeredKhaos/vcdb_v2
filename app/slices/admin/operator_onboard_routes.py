from __future__ import annotations

from flask import flash, redirect, render_template, session, url_for
from flask_login import login_required

from app.extensions import db
from app.extensions.contracts import auth_v1
from app.lib.ids import new_ulid
from app.lib.request_ctx import ensure_request_id
from app.lib.security import roles_required

from . import operator_onboard_services as svc
from .operator_onboard_forms import (
    OperatorOnboardCommitForm,
    OperatorOnboardForm,
    OperatorRbacRoleEditForm,
)
from .routes import _actor_ulid, bp

_PREVIEW_SESSION_KEY = "admin_operator_onboard_preview"


def _request_id_value() -> str:
    rid = ensure_request_id()
    if rid:
        return str(rid)
    return new_ulid()


def _bind_role_choices(form: OperatorOnboardForm) -> None:
    form.role_code.choices = auth_v1.list_rbac_role_choices()


def _bind_edit_role_choices(form: OperatorRbacRoleEditForm) -> None:
    form.role_code.choices = auth_v1.list_rbac_role_choices()


def _store_preview(review: svc.OperatorOnboardReviewDTO) -> str:
    token = new_ulid()
    session[_PREVIEW_SESSION_KEY] = {
        "token": token,
        **svc.review_payload_dict(review),
    }
    session.modified = True
    return token


def _get_preview_payload(token: str) -> dict[str, object] | None:
    data = session.get(_PREVIEW_SESSION_KEY)
    if not isinstance(data, dict):
        return None
    if str(data.get("token") or "") != str(token or ""):
        return None
    return dict(data)


def _clear_preview() -> None:
    session.pop(_PREVIEW_SESSION_KEY, None)
    session.modified = True


# VCDB-SEC: ACTIVE entry=admin_only authority=none reason=rbac_surface
@bp.get("/auth/operators/onboard/")
@login_required
@roles_required("admin")
def auth_operator_onboard():
    form = OperatorOnboardForm()
    _bind_role_choices(form)
    return render_template("admin/auth/operator_onboard.html", form=form)


# VCDB-SEC: ACTIVE entry=admin_only authority=none reason=rbac_surface
@bp.post("/auth/operators/onboard/review")
@login_required
@roles_required("admin")
def auth_operator_onboard_review():
    form = OperatorOnboardForm()
    _bind_role_choices(form)
    # temp debug print
    print("ONBOARD REVIEW CHOICES:", form.role_code.choices)
    print("ONBOARD REVIEW VALID:", form.validate_on_submit(), form.errors)

    if not form.validate_on_submit():
        return render_template(
            "admin/auth/operator_onboard.html",
            form=form,
        )

    try:
        review = svc.build_operator_onboard_review(
            first_name=form.first_name.data or "",
            last_name=form.last_name.data or "",
            preferred_name=form.preferred_name.data or "",
            username=form.username.data or "",
            email=form.email.data or "",
            temporary_password=form.temporary_password.data or "",
            role_code=form.role_code.data or "",
        )
    except Exception as exc:
        flash(str(exc), "error")
        return render_template(
            "admin/auth/operator_onboard.html",
            form=form,
        )

    token = _store_preview(review)

    commit_form = OperatorOnboardCommitForm()
    commit_form.preview_token.data = token

    return render_template(
        "admin/auth/operator_onboard_review.html",
        review=review,
        form=commit_form,
    )


# VCDB-SEC: ACTIVE entry=admin_only authority=none reason=rbac_surface
@bp.post("/auth/operators/onboard/commit")
@login_required
@roles_required("admin")
def auth_operator_onboard_commit():
    form = OperatorOnboardCommitForm()

    if not form.validate_on_submit():
        flash("Commit form is incomplete.", "error")
        return redirect(url_for("admin.auth_operator_onboard"))

    token = (form.preview_token.data or "").strip()
    payload = _get_preview_payload(token)
    if not payload:
        flash("Operator onboarding preview is missing or expired.", "error")
        return redirect(url_for("admin.auth_operator_onboard"))

    try:
        result = svc.commit_operator_onboard(
            actor_ulid=_actor_ulid(),
            request_id=_request_id_value(),
            first_name=str(payload.get("first_name") or ""),
            last_name=str(payload.get("last_name") or ""),
            preferred_name=str(payload.get("preferred_name") or ""),
            username=str(payload.get("username") or ""),
            email=(payload.get("email") or None),
            temporary_password=str(payload.get("temporary_password") or ""),
            role_code=str(payload.get("role_code") or ""),
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")

        review = svc.build_operator_onboard_review(
            first_name=str(payload.get("first_name") or ""),
            last_name=str(payload.get("last_name") or ""),
            preferred_name=str(payload.get("preferred_name") or ""),
            username=str(payload.get("username") or ""),
            email=(payload.get("email") or None),
            temporary_password=str(payload.get("temporary_password") or ""),
            role_code=str(payload.get("role_code") or ""),
        )
        commit_form = OperatorOnboardCommitForm()
        commit_form.preview_token.data = token

        return render_template(
            "admin/auth/operator_onboard_review.html",
            review=review,
            form=commit_form,
        )

    _clear_preview()
    flash(
        f"Operator created: {result.display_name} ({result.username})",
        "success",
    )
    return redirect(url_for("admin.auth_operators"))


# VCDB-SEC: ACTIVE entry=admin_only authority=none reason=rbac_surface
@bp.get("/auth/operators/<string:account_ulid>/rbac-role")
@login_required
@roles_required("admin")
def auth_operator_rbac_role_get(account_ulid: str):
    page = svc.build_rbac_maintenance_page(account_ulid=account_ulid)
    form = OperatorRbacRoleEditForm()
    _bind_edit_role_choices(form)
    if page.current_role_code:
        form.role_code.data = page.current_role_code
    return render_template(
        "admin/auth/operator_rbac_role.html",
        page=page,
        form=form,
    )


# VCDB-SEC: ACTIVE entry=admin_only authority=none reason=rbac_surface
@bp.post("/auth/operators/<string:account_ulid>/rbac-role")
@login_required
@roles_required("admin")
def auth_operator_rbac_role_post(account_ulid: str):
    page = svc.build_rbac_maintenance_page(account_ulid=account_ulid)
    form = OperatorRbacRoleEditForm()
    _bind_edit_role_choices(form)

    if not form.validate_on_submit():
        return render_template(
            "admin/auth/operator_rbac_role.html",
            page=page,
            form=form,
        )

    try:
        result = svc.edit_operator_rbac_role(
            account_ulid=account_ulid,
            role_code=form.role_code.data or "",
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return render_template(
            "admin/auth/operator_rbac_role.html",
            page=page,
            form=form,
        )

    flash(
        f"RBAC role updated for {result.display_name}: "
        f"{result.role_label}.",
        "success",
    )
    return redirect(url_for("admin.auth_operators"))
