# app/slices/ledger/admin_issue_routes.py

from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import auth_ctx, db
from app.lib.request_ctx import ensure_request_id
from app.lib.security import rbac

from . import admin_issue_services as issue_svc
from .routes import bp


# VCDB-SEC: ACTIVE entry=admin authority=rbac reason=admin_only_surface
@bp.get("/admin-issue/<issue_ulid>", endpoint="admin_issue_get")
@login_required
@rbac("admin")
def admin_issue_get(issue_ulid: str):
    page = issue_svc.ledger_issue_get(issue_ulid)
    if (request.args.get("format") or "").strip().lower() == "json":
        return {"ok": True, "data": page}, 200

    return render_template("ledger/admin_issue.html", page=page)


# VCDB-SEC: ACTIVE entry=admin authority=rbac reason=admin_only_surface
@bp.post(
    "/admin-issue/<issue_ulid>/run-verify",
    endpoint="admin_issue_run_verify",
)
@login_required
@rbac("admin")
def admin_issue_run_verify(issue_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        result = issue_svc.run_verify_for_issue(
            issue_ulid=issue_ulid,
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    if result.get("ok"):
        flash("Ledger verification completed cleanly.", "success")
    else:
        flash("Ledger verification still reports an issue.", "warning")
    return redirect(url_for("ledger.admin_issue_get", issue_ulid=issue_ulid))


# VCDB-SEC: ACTIVE entry=admin authority=rbac reason=admin_only_surface
@bp.post(
    "/admin-issue/<issue_ulid>/repair-hashchain",
    endpoint="admin_issue_repair_hashchain",
)
@login_required
@rbac("admin")
def admin_issue_repair_hashchain(issue_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        result = issue_svc.repair_hashchain_for_issue(
            issue_ulid=issue_ulid,
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    if result.get("ok"):
        flash("Ledger hash-chain repaired and verified clean.", "success")
        return redirect(url_for("admin.inbox"))

    flash("Ledger hash-chain repair ran, but verification still fails.", "warning")
    return redirect(url_for("ledger.admin_issue_get", issue_ulid=issue_ulid))


# VCDB-SEC: ACTIVE entry=admin authority=rbac reason=admin_only_surface
@bp.post(
    "/admin-issue/<issue_ulid>/close-restored",
    endpoint="admin_issue_close_restored",
)
@login_required
@rbac("admin")
def admin_issue_close_restored(issue_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        issue_svc.close_ledger_admin_issue(
            issue_ulid=issue_ulid,
            actor_ulid=actor,
            request_id=req,
            source_status=issue_svc.SOURCE_STATUS_RESTORED,
            close_reason="restored_in_ledger",
        )
        db.session.commit()
        flash("Ledger issue closed as restored.", "success")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))


# VCDB-SEC: ACTIVE entry=admin authority=rbac reason=admin_only_surface
@bp.post(
    "/admin-issue/<issue_ulid>/close-no-repair",
    endpoint="admin_issue_close_no_repair",
)
@login_required
@rbac("admin")
def admin_issue_close_no_repair(issue_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        issue_svc.close_ledger_admin_issue(
            issue_ulid=issue_ulid,
            actor_ulid=actor,
            request_id=req,
            source_status=issue_svc.SOURCE_STATUS_NO_REPAIR,
            close_reason="false_positive_no_repair",
        )
        db.session.commit()
        flash("Ledger issue closed as false positive / no repair.", "success")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))
