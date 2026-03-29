# app/slices/admin/routes.py

"""
VCDB v2 — Admin slice routes
"""

from __future__ import annotations

import json

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
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
    for attr in ("entity_ulid", "ulid"):
        value = getattr(current_user, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise RuntimeError("current_user is missing an operator ULID")


# -----------------
# Dashboard
# -----------------


@bp.get("/")
@login_required
@roles_required("admin")
def index():
    page = svc.get_dashboard()
    return render_template("admin/index.html", page=page)


# -----------------
# Unified Admin Inbox
# -----------------


@bp.get("/inbox/")
@login_required
@roles_required("admin")
def inbox():
    page = svc.get_inbox_page()
    return render_template("admin/inbox.html", page=page)


# -----------------
# Cron & Maint
# -----------------


@bp.get("/cron/")
@login_required
@roles_required("admin")
def cron():
    page = svc.get_cron_page()
    return render_template("admin/cron.html", page=page)


# -----------------
# Policy Workflow
# -----------------


@bp.get("/policy/")
@login_required
@roles_required("admin")
def policy_index():
    page = svc.get_policy_index_page()
    return render_template("admin/policy/index.html", page=page)


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

    try:
        new_policy = json.loads(form.policy_text.data or "{}")
    except json.JSONDecodeError as exc:
        page = svc.build_policy_preview_page_from_parse_error(
            policy_key=policy_key,
            policy_text=form.policy_text.data or "",
            base_hash=form.base_hash.data or "",
            message=str(exc),
        )
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
    return render_template(
        "admin/policy/preview.html",
        page=page,
        form=form,
    )


@bp.post("/policy/<string:policy_key>/commit")
@login_required
@roles_required("admin")
def policy_commit(policy_key: str):
    form = PolicyEditForm()

    if not form.validate_on_submit():
        page = svc.get_policy_detail_page(policy_key)
        return render_template(
            "admin/policy/detail.html",
            page=page,
            form=form,
        )

    reason = (form.reason.data or "").strip()
    if not reason:
        page = svc.build_policy_preview_page_from_parse_error(
            policy_key=policy_key,
            policy_text=form.policy_text.data or "",
            base_hash=form.base_hash.data or "",
            message="A commit reason is required.",
        )
        return render_template(
            "admin/policy/preview.html",
            page=page,
            form=form,
        )

    try:
        new_policy = json.loads(form.policy_text.data or "{}")
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
        flash(str(exc), "error")
        return redirect(url_for("admin.policy_detail", policy_key=policy_key))

    flash(
        f"Policy {policy_key} committed: {result.get('new_hash', '')}",
        "success",
    )
    return redirect(url_for("admin.policy_detail", policy_key=policy_key))


# -----------------
# Auth Surface
# Operator Mngmt
# -----------------


@bp.get("/auth/operators/")
@login_required
@roles_required("admin")
def auth_operators():
    page = svc.get_auth_operators_page()
    return render_template("admin/auth/operators.html", page=page)


# -----------------
# Audit/Reports
# -----------------
