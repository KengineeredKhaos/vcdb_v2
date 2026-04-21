# app/slices/admin/routes.py

"""
VCDB v2 — Admin slice routes
"""

from __future__ import annotations

import json

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.lib.security import roles_required

from . import services as svc
from .forms import PolicyEditForm

bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="templates",
)


def _actor_ulid() -> str:
    for attr in ("entity_ulid", "ulid", "account_ulid", "id"):
        value = getattr(current_user, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()

    getter = getattr(current_user, "get_id", None)
    if callable(getter):
        value = getter()
        if isinstance(value, str) and value.strip():
            if (
                current_app.testing
                or current_app.debug
                or current_app.config.get("AUTH_MODE") == "stub"
            ):
                return value.strip()

    raise RuntimeError("current_user is missing an operator ULID")


def _render_policy_preview_from_form(
    *,
    policy_key: str,
    form: PolicyEditForm,
    extra_error: str | None = None,
):
    try:
        new_policy = json.loads(form.policy_text.data or "{}")
    except json.JSONDecodeError as exc:
        page = svc.build_policy_preview_page_from_parse_error(
            policy_key=policy_key,
            policy_text=form.policy_text.data or "",
            base_hash=form.base_hash.data or "",
            message=str(exc),
        )
        if extra_error:
            flash(extra_error, "error")
        return render_template(
            "admin/policy/preview.html",
            page=page,
            form=form,
        )

    page = svc.build_policy_preview_page(
        policy_key=policy_key,
        new_policy=new_policy,
        base_hash=form.base_hash.data or "",
    )
    form.policy_text.data = page.normalized_text
    form.base_hash.data = page.current_hash
    form.proposed_hash.data = page.proposed_hash
    if extra_error:
        flash(extra_error, "error")
    return render_template(
        "admin/policy/preview.html",
        page=page,
        form=form,
    )


# -----------------
# Dashboard
# -----------------


# ad hoc route tests and access for development-only
# VCDB-SEC: ACTIVE entry=admin authority=none reason=admin_only_surface test=admin_route_access
@bp.get("/")
@login_required
@roles_required("admin")
def index():
    page = svc.get_dashboard()
    return render_template("admin/index.html", page=page)


# -----------------
# Unified Admin Inbox
# -----------------


# Admin inbox notifactions of slice admin approval required
# unimplemented at slice-level yet
# VCDB-SEC: ACTIVE entry=admin authority=none reason=admin_only_surface test=admin_route_access
@bp.get("/inbox/")
@login_required
@roles_required("admin")
def inbox():
    page = svc.get_inbox_page()
    return render_template("admin/inbox.html", page=page)


# -----------------
# Cron & Maint
# -----------------


# Cron Job Stack
# VCDB-SEC: ACTIVE entry=admin authority=none reason=admin_only_surface test=admin_route_access
@bp.get("/cron/")
@login_required
@roles_required("admin")
def cron():
    page = svc.get_cron_page()
    return render_template("admin/cron.html", page=page)


# -----------------
# Policy Workflow
# -----------------


# Governance policy edit surface - under development
# VCDB-SEC: ACTIVE entry=admin authority=pending reason=policy_workflow_surface test=admin_policy_route_access
@bp.get("/policy/")
@login_required
@roles_required("admin")
def policy_index():
    page = svc.get_policy_index_page()
    return render_template("admin/policy/index.html", page=page)


# Governance policy edit surface - undeveloped
# VCDB-SEC: ACTIVE entry=admin authority=pending reason=policy_workflow_surface test=admin_policy_route_access
@bp.get("/policy/<string:policy_key>/")
@login_required
@roles_required("admin")
def policy_detail(policy_key: str):
    page = svc.get_policy_detail_page(policy_key)
    form = PolicyEditForm()
    form.policy_text.data = page.current_text
    form.base_hash.data = page.current_hash
    return render_template(
        "admin/policy/detail.html",
        page=page,
        form=form,
    )


# Governance policy edit surface - undeveloped
# VCDB-SEC: ACTIVE entry=admin authority=pending reason=policy_workflow_surface test=admin_policy_route_access
@bp.post("/policy/<string:policy_key>/preview")
@login_required
@roles_required("admin")
def policy_preview(policy_key: str):
    form = PolicyEditForm()
    detail_page = svc.get_policy_detail_page(policy_key)

    if not form.validate_on_submit():
        return render_template(
            "admin/policy/detail.html",
            page=detail_page,
            form=form,
        )

    return _render_policy_preview_from_form(
        policy_key=policy_key,
        form=form,
    )


# Governance policy edit surface - undeveloped
# VCDB-SEC: ACTIVE entry=admin authority=pending reason=policy_workflow_surface test=admin_policy_route_access
@bp.post("/policy/<string:policy_key>/commit")
@login_required
@roles_required("admin")
def policy_commit(policy_key: str):
    form = PolicyEditForm()

    if not form.validate_on_submit():
        return _render_policy_preview_from_form(
            policy_key=policy_key,
            form=form,
            extra_error="Commit form is incomplete.",
        )

    reason = (form.reason.data or "").strip()
    if not reason:
        return _render_policy_preview_from_form(
            policy_key=policy_key,
            form=form,
            extra_error="A commit reason is required.",
        )

    try:
        new_policy = json.loads(form.policy_text.data or "{}")
    except json.JSONDecodeError:
        return _render_policy_preview_from_form(
            policy_key=policy_key,
            form=form,
            extra_error="Commit payload is not valid JSON.",
        )

    try:
        result = svc.commit_policy_update(
            policy_key=policy_key,
            new_policy=new_policy,
            actor_ulid=_actor_ulid(),
            reason=reason,
            base_hash=form.base_hash.data or "",
            proposed_hash=form.proposed_hash.data or "",
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return _render_policy_preview_from_form(
            policy_key=policy_key,
            form=form,
            extra_error=str(exc),
        )

    flash(
        f"Policy {policy_key} committed: {result.get('new_hash', '')}",
        "success",
    )
    return redirect(url_for("admin.policy_detail", policy_key=policy_key))


# -----------------
# Auth Surface
# Operator Mngmt
# -----------------


# Operator list view/edit surface entry - undeveloped
# VCDB-SEC: STAGED entry=admin authority=pending reason=operator_admin_surface test=admin_operator_onboard_route_access
@bp.get("/auth/operators/")
@login_required
@roles_required("admin")
def auth_operators():
    page = svc.get_auth_operators_page()
    return render_template("admin/auth/operators.html", page=page)


# -----------------
# Audit/Reports
# -----------------
