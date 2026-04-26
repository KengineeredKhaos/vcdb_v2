# app/slices/customers/adim_issue_routes.py

from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import auth_ctx, db
from app.lib.request_ctx import ensure_request_id
from app.lib.security import rbac

from . import admin_issue_services as issue_svc
from .routes import bp


def _render_issue_page(
    *,
    page: dict,
    approve_endpoint: str,
    reject_endpoint: str,
):
    if (request.args.get("format") or "").strip().lower() == "json":
        return {"ok": True, "data": page}, 200

    return render_template(
        "customers/admin_issue_detail.html",
        page=page,
        approve_endpoint=approve_endpoint,
        reject_endpoint=reject_endpoint,
    )


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.get(
    "/admin-issue/assessment-completed/<issue_ulid>",
    endpoint="admin_issue_assessment_completed_get",
)
@login_required
@rbac("admin")
def admin_issue_assessment_completed_get(issue_ulid: str):
    page = issue_svc.assessment_completed_issue_get(issue_ulid)
    return _render_issue_page(
        page=page,
        approve_endpoint="customers.admin_issue_assessment_completed_approve",
        reject_endpoint="customers.admin_issue_assessment_completed_reject",
    )


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.post(
    "/admin-issue/assessment-completed/<issue_ulid>/approve",
    endpoint="admin_issue_assessment_completed_approve",
)
@login_required
@rbac("admin")
def admin_issue_assessment_completed_approve(issue_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        issue_svc.resolve_assessment_completed_admin_issue(
            issue_ulid=issue_ulid,
            decision="approve",
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
        flash("Customer assessment issue approved.", "success")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.post(
    "/admin-issue/assessment-completed/<issue_ulid>/reject",
    endpoint="admin_issue_assessment_completed_reject",
)
@login_required
@rbac("admin")
def admin_issue_assessment_completed_reject(issue_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        issue_svc.resolve_assessment_completed_admin_issue(
            issue_ulid=issue_ulid,
            decision="reject",
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
        flash("Customer assessment issue rejected.", "warning")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.get(
    "/admin-issue/watchlist/<issue_ulid>",
    endpoint="admin_issue_watchlist_get",
)
@login_required
@rbac("admin")
def admin_issue_watchlist_get(issue_ulid: str):
    page = issue_svc.watchlist_issue_get(issue_ulid)
    return _render_issue_page(
        page=page,
        approve_endpoint="customers.admin_issue_watchlist_approve",
        reject_endpoint="customers.admin_issue_watchlist_reject",
    )


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.post(
    "/admin-issue/watchlist/<issue_ulid>/approve",
    endpoint="admin_issue_watchlist_approve",
)
@login_required
@rbac("admin")
def admin_issue_watchlist_approve(issue_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        issue_svc.resolve_watchlist_admin_issue(
            issue_ulid=issue_ulid,
            decision="approve",
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
        flash("Customer watchlist issue approved.", "success")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))


# VCDB-SEC: STAGED entry=admin authority=pending reason=admin_only_surface
@bp.post(
    "/admin-issue/watchlist/<issue_ulid>/reject",
    endpoint="admin_issue_watchlist_reject",
)
@login_required
@rbac("admin")
def admin_issue_watchlist_reject(issue_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        issue_svc.resolve_watchlist_admin_issue(
            issue_ulid=issue_ulid,
            decision="reject",
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
        flash("Customer watchlist issue rejected.", "warning")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))
