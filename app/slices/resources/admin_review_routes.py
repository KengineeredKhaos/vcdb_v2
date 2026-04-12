# app/slices/resources/admin_review_routes.py

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

from app.extensions import auth_ctx, db
from app.extensions.auth_ctx import current_actor_ulid
from app.lib.request_ctx import ensure_request_id
from app.lib.security import rbac, roles_required

from . import admin_review_services as review_svc
from .routes import bp


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.get(
    "/admin-review/<review_request_ulid>",
    endpoint="admin_review_onboard_get",
)
@login_required
@roles_required("admin")
def admin_review_onboard_get(review_request_ulid: str):
    page = review_svc.onboard_review_get(review_request_ulid)
    if (request.args.get("format") or "").strip().lower() == "json":
        return {"ok": True, "data": page}, 200
    return render_template(
        "resources/admin_review_onboard.html",
        page=page,
    )


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.post(
    "/admin-review/<review_request_ulid>/approve",
    endpoint="admin_review_onboard_approve",
)
@login_required
@roles_required("admin")
def admin_review_onboard_approve(review_request_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        review_svc.resolve_onboard_admin_issue(
            review_request_ulid=review_request_ulid,
            decision="approve",
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
        flash("Resource onboarding approved.", "success")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.post(
    "/admin-review/<review_request_ulid>/reject",
    endpoint="admin_review_onboard_reject",
)
@login_required
@roles_required("admin")
def admin_review_onboard_reject(review_request_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        review_svc.resolve_onboard_admin_issue(
            review_request_ulid=review_request_ulid,
            decision="reject",
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
        flash("Resource onboarding rejected.", "warning")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))
