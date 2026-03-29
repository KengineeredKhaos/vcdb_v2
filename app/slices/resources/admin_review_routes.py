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

from app.extensions import db
from app.lib.request_ctx import ensure_request_id
from app.slices.auth.services import current_actor_ulid

from . import admin_review_services as review_svc
from .routes import bp


@bp.post(
    "/admin-review/<review_request_ulid>/approve",
    endpoint="admin_review_onboard_approve",
)
# add your RBAC / governor guards here
def admin_review_onboard_approve(review_request_ulid: str):
    req = ensure_request_id()
    actor = current_actor_ulid()

    try:
        review_svc.resolve_onboard_admin_review(
            review_request_ulid=review_request_ulid,
            approved=True,
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
        flash("Resource onboarding approved.", "success")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))


@bp.post(
    "/admin-review/<review_request_ulid>/reject",
    endpoint="admin_review_onboard_reject",
)
# add your RBAC / governor guards here
def admin_review_onboard_reject(review_request_ulid: str):
    req = ensure_request_id()
    actor = current_actor_ulid()

    try:
        review_svc.resolve_onboard_admin_review(
            review_request_ulid=review_request_ulid,
            approved=False,
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
        flash("Resource onboarding rejected.", "warning")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))
