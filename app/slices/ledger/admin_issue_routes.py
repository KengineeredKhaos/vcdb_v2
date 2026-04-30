# app/slices/ledger/admin_issue_routes.py

from __future__ import annotations

from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required

from app.extensions import auth_ctx, db
from app.lib.request_ctx import ensure_request_id
from app.lib.security import current_user_roles, roles_required

from . import admin_issue_services as issue_svc
from .routes import bp


def _can_mutate() -> bool:
    return "admin" in current_user_roles()


def _dashboard_back_target() -> tuple[str, str]:
    roles = current_user_roles()
    if "auditor" in roles and "admin" not in roles:
        if "auditor.dashboard" in current_app.view_functions:
            return ("auditor.dashboard", "Back to Auditor Dashboard")
    return ("admin.index", "Back to Admin Dashboard")


def _issue_view() -> str:
    view = str(request.args.get("view") or "active").strip().lower()
    if view in {"active", "closed", "all"}:
        return view
    return "active"


# VCDB-SEC: ACTIVE entry=admin|auditor authority=login_required reason=infra_readonly_surface test=ledger_admin_issue_routes
@bp.get("/admin/issues", endpoint="admin_issue_index")
@login_required
@roles_required("admin", "auditor")
def admin_issue_index():
    page = issue_svc.ledger_drilldown_index(view=_issue_view())
    if (request.args.get("format") or "").strip().lower() == "json":
        return {"ok": True, "data": page}, 200

    back_endpoint, back_label = _dashboard_back_target()
    return render_template(
        "ledger/admin_issue_index.html",
        page=page,
        can_mutate=_can_mutate(),
        back_dashboard_href=url_for(back_endpoint),
        back_dashboard_label=back_label,
    )


# VCDB-SEC: ACTIVE entry=admin|auditor authority=login_required reason=infra_readonly_surface test=ledger_admin_issue_routes
@bp.get("/admin/issues/<issue_ulid>", endpoint="admin_issue_get")
@login_required
@roles_required("admin", "auditor")
def admin_issue_get(issue_ulid: str):
    page = issue_svc.ledger_issue_get(issue_ulid)
    if (request.args.get("format") or "").strip().lower() == "json":
        return {"ok": True, "data": page}, 200

    back_endpoint, back_label = _dashboard_back_target()
    return render_template(
        "ledger/admin_issue.html",
        page=page,
        can_mutate=_can_mutate(),
        back_dashboard_href=url_for(back_endpoint),
        back_dashboard_label=back_label,
    )


# VCDB-SEC: ACTIVE entry=admin|auditor authority=login_required reason=infra_readonly_surface test=ledger_admin_issue_routes
@bp.get("/admin/checks/<check_ulid>", endpoint="hashchain_check_get")
@login_required
@roles_required("admin", "auditor")
def hashchain_check_get(check_ulid: str):
    page = issue_svc.ledger_check_get(check_ulid)
    if (request.args.get("format") or "").strip().lower() == "json":
        return {"ok": True, "data": page}, 200

    back_endpoint, back_label = _dashboard_back_target()
    return render_template(
        "ledger/hashchain_check_detail.html",
        page=page,
        can_mutate=_can_mutate(),
        back_dashboard_href=url_for(back_endpoint),
        back_dashboard_label=back_label,
    )


# VCDB-SEC: ACTIVE entry=admin|auditor authority=login_required reason=infra_readonly_surface test=ledger_admin_issue_routes
@bp.get("/admin/repairs/<repair_ulid>", endpoint="hashchain_repair_get")
@login_required
@roles_required("admin", "auditor")
def hashchain_repair_get(repair_ulid: str):
    page = issue_svc.ledger_repair_get(repair_ulid)
    if (request.args.get("format") or "").strip().lower() == "json":
        return {"ok": True, "data": page}, 200

    back_endpoint, back_label = _dashboard_back_target()
    return render_template(
        "ledger/hashchain_repair_detail.html",
        page=page,
        can_mutate=_can_mutate(),
        back_dashboard_href=url_for(back_endpoint),
        back_dashboard_label=back_label,
    )


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=admin_only_surface test=ledger_admin_issue_routes
@bp.post("/admin/run-verify", endpoint="admin_issue_run_manual_verify")
@login_required
@roles_required("admin")
def admin_issue_run_manual_verify():
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        result = issue_svc.run_manual_integrity_check(
            actor_ulid=actor,
            request_id=req,
            chain_key=None,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    if result.get("ok"):
        flash(
            "Ledger verification completed cleanly. "
            "Evidence row recorded.",
            "success",
        )
    else:
        flash(
            "Ledger verification found a problem. "
            "Evidence row recorded and Ledger issue refreshed.",
            "warning",
        )
    return redirect(url_for("ledger.admin_issue_index"))


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=admin_only_surface test=ledger_admin_issue_routes
@bp.post(
    "/admin/issues/<issue_ulid>/run-verify",
    endpoint="admin_issue_run_verify",
)
@login_required
@roles_required("admin")
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


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=admin_only_surface test=ledger_admin_issue_routes
@bp.post(
    "/admin/issues/<issue_ulid>/repair-hashchain",
    endpoint="admin_issue_repair_hashchain",
)
@login_required
@roles_required("admin")
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
    else:
        flash(
            "Ledger hash-chain repair ran, but verification still fails.",
            "warning",
        )
    return redirect(url_for("ledger.admin_issue_get", issue_ulid=issue_ulid))


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=admin_only_surface test=ledger_admin_issue_routes
@bp.post(
    "/admin/issues/<issue_ulid>/close-restored",
    endpoint="admin_issue_close_restored",
)
@login_required
@roles_required("admin")
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

    return redirect(url_for("ledger.admin_issue_get", issue_ulid=issue_ulid))


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=admin_only_surface test=ledger_admin_issue_routes
@bp.post(
    "/admin/issues/<issue_ulid>/close-no-repair",
    endpoint="admin_issue_close_no_repair",
)
@login_required
@roles_required("admin")
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

    return redirect(url_for("ledger.admin_issue_get", issue_ulid=issue_ulid))
