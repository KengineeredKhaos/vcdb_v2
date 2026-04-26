# app/slices/sponsors/admin_issue_routes.py

from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import auth_ctx, db
from app.lib.request_ctx import ensure_request_id
from app.lib.security import roles_required

from . import admin_issue_services as issue_svc
from .routes import bp


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.get(
    "/admin-issue/<issue_ulid>",
    endpoint="admin_issue_onboard_get",
)
@login_required
@roles_required("admin")
def admin_issue_onboard_get(issue_ulid: str):
    page = issue_svc.onboard_issue_get(issue_ulid)
    if (request.args.get("format") or "").strip().lower() == "json":
        return {"ok": True, "data": page}, 200

    return render_template(
        "sponsors/admin_issue_onboard.html",
        page=page,
    )


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.post(
    "/admin-issue/<issue_ulid>/approve",
    endpoint="admin_issue_onboard_approve",
)
@login_required
@roles_required("admin")
def admin_issue_onboard_approve(issue_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        issue_svc.resolve_onboard_admin_issue(
            issue_ulid=issue_ulid,
            decision="approve",
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
        flash("Sponsor onboarding approved.", "success")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.post(
    "/admin-issue/<issue_ulid>/reject",
    endpoint="admin_issue_onboard_reject",
)
@login_required
@roles_required("admin")
def admin_issue_onboard_reject(issue_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        issue_svc.resolve_onboard_admin_issue(
            issue_ulid=issue_ulid,
            decision="reject",
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
        flash("Sponsor onboarding rejected.", "warning")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))
