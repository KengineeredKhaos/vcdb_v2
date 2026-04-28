# app/slices/finance/admin_issue_routes.py

from __future__ import annotations

from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.lib.security import roles_required

from . import admin_issue_services as svc
from .admin_issue_repair_services import (
    balance_projection_rebuild_preview,
    commit_balance_projection_rebuild,
)
from .routes import bp


def _actor_ulid() -> str:
    """Return the current operator ULID for audit/ledger attribution.

    Mirrors the Admin slice helper shape so Finance mutations keep the same
    operator attribution behavior across real and test/stub auth modes.
    """
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


def _current_role_codes() -> set[str]:
    """Best-effort role check for template affordances only.

    Security is enforced by route decorators. This helper only decides
    whether to show mutation buttons to Admin users while keeping future
    Auditor Dashboard views clean and read-only.
    """
    header_role = str(request.headers.get("X-Auth-Stub") or "").strip()
    if header_role:
        return {header_role}

    roles: set[str] = set()
    for attr in ("roles", "rbac_roles", "role_codes"):
        value = getattr(current_user, attr, None)
        if value is None:
            continue
        if isinstance(value, str):
            roles.add(value)
            continue
        try:
            for item in value:
                code = getattr(item, "code", item)
                code = getattr(code, "name", code)
                if isinstance(code, str) and code.strip():
                    roles.add(code.strip())
        except TypeError:
            continue

    return {r.strip().lower() for r in roles if str(r).strip()}


def _can_mutate() -> bool:
    return "admin" in _current_role_codes()


def _issue_view() -> str:
    return str(request.args.get("view") or "active").strip().lower()


def _redirect_issue(issue_ulid: str):
    return redirect(
        url_for("finance.admin_issue_detail", issue_ulid=issue_ulid)
    )


# -----------------
# Finance Admin Issue
# read-only drill-down
# -----------------


# VCDB-SEC: ACTIVE entry=admin|auditor authority=login_required reason=finance_issue_readonly test=finance_admin_issue_route_access
@bp.get("/admin/issues", endpoint="admin_issue_index")
@login_required
@roles_required("admin", "auditor")
def admin_issue_index():
    view = _issue_view()
    issues = svc.list_integrity_admin_issues(view=view)
    return render_template(
        "finance/admin_issue/index.html",
        title="Finance Issues",
        issues=issues,
        current_view=view,
        can_mutate=_can_mutate(),
    )


# VCDB-SEC: ACTIVE entry=admin|auditor authority=login_required reason=finance_issue_readonly test=finance_admin_issue_route_access
@bp.get("/admin/issues/<string:issue_ulid>", endpoint="admin_issue_detail")
@login_required
@roles_required("admin", "auditor")
def admin_issue_detail(issue_ulid: str):
    issue = svc.integrity_review_get(issue_ulid)
    return render_template(
        "finance/admin_issue/detail.html",
        title=issue.title,
        issue=issue,
        can_mutate=_can_mutate(),
    )


# -----------------
# Finance Admin Issue
# mutation controls
# -----------------


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_mutation test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/start-review",
    endpoint="admin_issue_start_review",
)
@login_required
@roles_required("admin")
def admin_issue_start_review(issue_ulid: str):
    try:
        svc.start_integrity_review(
            issue_ulid,
            actor_ulid=_actor_ulid(),
        )
        db.session.commit()
        flash("Finance issue moved to in review.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_mutation test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/close",
    endpoint="admin_issue_close",
)
@login_required
@roles_required("admin")
def admin_issue_close(issue_ulid: str):
    close_reason = str(request.form.get("close_reason") or "").strip()
    issue_status = str(
        request.form.get("issue_status") or svc.ISSUE_STATUS_RESOLVED
    ).strip()

    if not close_reason:
        flash("Close reason is required.", "error")
        return _redirect_issue(issue_ulid)

    try:
        svc.close_integrity_admin_issue(
            issue_ulid,
            actor_ulid=_actor_ulid(),
            close_reason=close_reason,
            issue_status=issue_status,
            resolution={
                "route": "finance.admin_issue_close",
                "note": str(request.form.get("note") or "").strip(),
            },
        )
        db.session.commit()
        flash("Finance issue closed.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)


# -----------------
# Finance Admin Issue
# balance projection repair
# -----------------


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_repair test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/balance-preview",
    endpoint="admin_issue_balance_preview",
)
@login_required
@roles_required("admin")
def admin_issue_balance_preview(issue_ulid: str):
    try:
        preview = balance_projection_rebuild_preview(
            issue_ulid,
            actor_ulid=_actor_ulid(),
        )
        db.session.commit()
        flash(
            (
                "Balance projection rebuild preview created: "
                f"{preview.rows_added} add, "
                f"{preview.rows_updated} update, "
                f"{preview.rows_deleted} delete."
            ),
            "success",
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_repair test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/balance-rebuild",
    endpoint="admin_issue_balance_rebuild",
)
@login_required
@roles_required("admin")
def admin_issue_balance_rebuild(issue_ulid: str):
    try:
        result = commit_balance_projection_rebuild(
            issue_ulid,
            actor_ulid=_actor_ulid(),
        )
        db.session.commit()
        if result.issue_closed:
            flash("Balance projection rebuilt and issue closed.", "success")
        else:
            flash(
                "Balance projection rebuilt but rescan is still dirty.",
                "warning",
            )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)
