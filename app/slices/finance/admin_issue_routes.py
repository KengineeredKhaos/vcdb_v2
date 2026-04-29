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
from app.lib.security import current_user_roles, roles_required

from . import admin_issue_services as svc
from .admin_issue_repair_services import (
    balance_projection_rebuild_preview,
    commit_balance_projection_rebuild,
    commit_posting_fact_drift_repair,
    posting_fact_drift_repair_preview,
)
from .admin_issue_sweep_services import (
    latest_finance_sweep_run,
    run_finance_integrity_sweep,
)
from .admin_issue_resolution_services import (
    close_journal_integrity_after_clean_rescan,
    confirm_journal_integrity_still_blocked,
    mark_journal_integrity_false_positive_after_clean_rescan,
    mark_journal_integrity_manual_review_required,
    mark_journal_integrity_reversal_required,
)
from .quarantine_services import list_quarantines_for_issue
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


def _can_mutate() -> bool:
    return "admin" in current_user_roles()


def _dashboard_back_target() -> tuple[str, str]:
    """Return the correct dashboard back target for this drill-down surface.

    Finance admin_issue pages are Admin/Auditor control-surface drill-down,
    not staff Finance work-lane pages. Prefer the future Auditor Dashboard
    when it exists; otherwise fall back to Admin Dashboard.
    """
    roles = current_user_roles()
    if "auditor" in roles and "admin" not in roles:
        if "auditor.dashboard" in current_app.view_functions:
            return ("auditor.dashboard", "Back to Auditor Dashboard")
    return ("admin.dashboard", "Back to Admin Dashboard")


def _dashboard_back_target() -> tuple[str, str]:
    """Return the correct dashboard back target for this drill-down surface.

    Finance admin_issue pages are Admin/Auditor control-surface drill-down,
    not staff Finance work-lane pages. Prefer the future Auditor Dashboard
    when it exists; otherwise fall back to Admin Dashboard.
    """
    roles = current_user_roles()
    if "auditor" in roles and "admin" not in roles:
        if "auditor.dashboard" in current_app.view_functions:
            return ("auditor.dashboard", "Back to Auditor Dashboard")
    return ("admin.index", "Back to Admin Dashboard")


def _issue_view() -> str:
    return str(request.args.get("view") or "active").strip().lower()


def _posture_label(posture: str | None) -> str:
    labels = {
        "projection_blocked": "Projection blocked",
        "posting_blocked": "Posting blocked",
        "projection_and_posting_blocked": "Projection and posting blocked",
    }
    return labels.get(str(posture or "").strip(), "No active quarantine")


def _recommended_path_label(path: str | None) -> str:
    labels = {
        "containment_and_review": "Keep blocked and continue review",
        "manual_accounting_review": "Manual accounting review required",
        "reversal_or_adjustment_required": (
            "Reversal/adjustment review required"
        ),
        "resolved_after_external_correction": ("Close after clean rescan"),
        "false_positive": "False positive after clean rescan",
    }
    return labels.get(str(path or "").strip(), "")


def _detail_summary(issue, quarantines) -> dict[str, str]:
    """Return plain-English detail summary for Admin/Auditor drill-down.

    This is presentation logic only. It helps the page answer, at a glance:
    what is blocked, what comes next, whether a repair is available, and
    what scope is fenced off.
    """
    active = tuple(q for q in quarantines if q.status == "active")
    first = active[0] if active else None

    if first is None:
        current_posture = "No active quarantine"
        posture_detail = (
            "Finance is not currently blocking projection or posting "
            "for this issue."
        )
        quarantine_scope = "None"
    else:
        current_posture = _posture_label(first.posture)
        posture_detail = first.message
        quarantine_scope = first.scope_label or first.scope_type
        if len(active) > 1:
            quarantine_scope = f"{quarantine_scope} (+{len(active) - 1} more)"

    resolution = dict(issue.resolution or {})
    preview = dict(issue.preview or {})
    recommended_next_step = _recommended_path_label(
        resolution.get("recommended_path")
    )

    if not recommended_next_step:
        if issue.reason_code == "anomaly_finance_balance_projection_drift":
            if preview.get("kind") == "balance_projection_rebuild_preview":
                recommended_next_step = "Review preview and commit rebuild"
            else:
                recommended_next_step = "Run balance rebuild preview"
        elif issue.reason_code == "anomaly_finance_posting_fact_drift":
            if preview.get("kind") == "posting_fact_drift_repair_preview":
                if int(preview.get("repairable_count", 0) or 0) > 0:
                    recommended_next_step = (
                        "Commit deterministic PostingFact repair"
                    )
                else:
                    recommended_next_step = "Manual review remains required"
            else:
                recommended_next_step = "Run PostingFact repair preview"
        elif issue.reason_code == "failure_finance_journal_integrity":
            recommended_next_step = (
                "Classify for manual review or reversal/adjustment"
            )
        else:
            recommended_next_step = "Review evidence and confirm safe path"

    if issue.reason_code == "anomaly_finance_balance_projection_drift":
        if preview.get("kind") == "balance_projection_rebuild_preview":
            delta = (
                int(preview.get("rows_added", 0) or 0)
                + int(preview.get("rows_updated", 0) or 0)
                + int(preview.get("rows_deleted", 0) or 0)
            )
            repair_available = (
                "Yes — commit ready" if delta > 0 else "No change needed"
            )
        else:
            repair_available = "Yes — preview available"
    elif issue.reason_code == "anomaly_finance_posting_fact_drift":
        if preview.get("kind") == "posting_fact_drift_repair_preview":
            repairable = int(preview.get("repairable_count", 0) or 0)
            if repairable > 0:
                repair_available = (
                    f"Yes — {repairable} deterministic repair(s) ready"
                )
            else:
                repair_available = "No — manual review only"
        else:
            repair_available = "Yes — preview available"
    else:
        repair_available = "No — workflow only"

    return {
        "current_posture": current_posture,
        "posture_detail": posture_detail,
        "recommended_next_step": recommended_next_step,
        "repair_available": repair_available,
        "quarantine_scope": quarantine_scope,
    }


def _redirect_issue(issue_ulid: str):
    return redirect(
        url_for("finance.admin_issue_detail", issue_ulid=issue_ulid)
    )


# -----------------
# Finance Admin Issue
# sweep control
# -----------------


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_integrity_sweep test=finance_admin_issue_route_access
@bp.post("/admin/issues/run-sweep", endpoint="admin_issue_run_sweep")
@login_required
@roles_required("admin")
def admin_issue_run_sweep():
    try:
        result = run_finance_integrity_sweep(
            actor_ulid=_actor_ulid(),
        )
        db.session.commit()
        flash(
            (
                "Finance integrity sweep complete: "
                f"{result.scans_run} scans, "
                f"{result.dirty_count} dirty, "
                f"{len(result.issue_ulids)} issues, "
                f"{len(result.quarantine_ulids)} quarantines."
            ),
            "success" if result.dirty_count == 0 else "warning",
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("finance.admin_issue_index"))


def _issue_index_rows(issues) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for issue in issues:
        quarantines = list_quarantines_for_issue(issue.issue_ulid)
        active = tuple(q for q in quarantines if q.status == "active")
        summary = _detail_summary(issue, quarantines)
        rows.append(
            {
                "issue": issue,
                "summary": summary,
                "active_quarantine_count": len(active),
            }
        )
    return rows


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
    issue_rows = _issue_index_rows(issues)
    latest_sweep = latest_finance_sweep_run()
    back_endpoint, back_label = _dashboard_back_target()
    return render_template(
        "finance/admin_issue/index.html",
        title="Finance Issues",
        issues=issues,
        issue_rows=issue_rows,
        current_view=view,
        can_mutate=_can_mutate(),
        latest_sweep=latest_sweep,
        back_dashboard_href=url_for(back_endpoint),
        back_dashboard_label=back_label,
    )


# VCDB-SEC: ACTIVE entry=admin|auditor authority=login_required reason=finance_issue_readonly test=finance_admin_issue_route_access
@bp.get("/admin/issues/<string:issue_ulid>", endpoint="admin_issue_detail")
@login_required
@roles_required("admin", "auditor")
def admin_issue_detail(issue_ulid: str):
    issue = svc.integrity_review_get(issue_ulid)
    quarantines = list_quarantines_for_issue(issue_ulid)
    return render_template(
        "finance/admin_issue/detail.html",
        title=issue.title,
        issue=issue,
        quarantines=quarantines,
        detail_summary=_detail_summary(issue, quarantines),
        can_mutate=_can_mutate(),
    )


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_note test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/oper-note",
    endpoint="admin_issue_oper_note",
)
@login_required
@roles_required("admin")
def admin_issue_oper_note(issue_ulid: str):
    note = str(request.form.get("oper_note") or "").strip()
    try:
        svc.set_issue_oper_note(
            issue_ulid,
            actor_ulid=_actor_ulid(),
            oper_note=note,
        )
        db.session.commit()
        flash("Operator note updated.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)


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


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_repair test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/posting-fact-preview",
    endpoint="admin_issue_posting_fact_preview",
)
@login_required
@roles_required("admin")
def admin_issue_posting_fact_preview(issue_ulid: str):
    try:
        preview = posting_fact_drift_repair_preview(
            issue_ulid,
            actor_ulid=_actor_ulid(),
        )
        db.session.commit()
        flash(
            (
                "PostingFact repair preview created: "
                f"{preview.repairable_count} repairable, "
                f"{preview.manual_review_count} manual review."
            ),
            "success" if preview.repairable_count else "warning",
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_repair test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/posting-fact-repair",
    endpoint="admin_issue_posting_fact_repair",
)
@login_required
@roles_required("admin")
def admin_issue_posting_fact_repair(issue_ulid: str):
    try:
        result = commit_posting_fact_drift_repair(
            issue_ulid,
            actor_ulid=_actor_ulid(),
        )
        db.session.commit()
        if result.issue_closed:
            flash("PostingFact drift repaired and issue closed.", "success")
        else:
            flash(
                (
                    "PostingFact repair applied, but rescan remains dirty. "
                    "Manual review is still required."
                ),
                "warning",
            )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)


# -----------------
# Finance Admin Issue
# journal integrity workflow
# -----------------


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_resolution test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/journal-confirm-blocked",
    endpoint="admin_issue_journal_confirm_blocked",
)
@login_required
@roles_required("admin")
def admin_issue_journal_confirm_blocked(issue_ulid: str):
    try:
        confirm_journal_integrity_still_blocked(
            issue_ulid,
            actor_ulid=_actor_ulid(),
        )
        db.session.commit()
        flash(
            "Journal integrity issue remains blocked for review.", "warning"
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_resolution test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/journal-manual-review",
    endpoint="admin_issue_journal_manual_review",
)
@login_required
@roles_required("admin")
def admin_issue_journal_manual_review(issue_ulid: str):
    try:
        mark_journal_integrity_manual_review_required(
            issue_ulid,
            actor_ulid=_actor_ulid(),
        )
        db.session.commit()
        flash(
            "Journal integrity issue marked for manual accounting review.",
            "warning",
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_resolution test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/journal-reversal-required",
    endpoint="admin_issue_journal_reversal_required",
)
@login_required
@roles_required("admin")
def admin_issue_journal_reversal_required(issue_ulid: str):
    try:
        mark_journal_integrity_reversal_required(
            issue_ulid,
            actor_ulid=_actor_ulid(),
        )
        db.session.commit()
        flash(
            "Journal integrity issue marked for reversal/adjustment review.",
            "warning",
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_resolution test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/journal-false-positive",
    endpoint="admin_issue_journal_false_positive",
)
@login_required
@roles_required("admin")
def admin_issue_journal_false_positive(issue_ulid: str):
    try:
        mark_journal_integrity_false_positive_after_clean_rescan(
            issue_ulid,
            actor_ulid=_actor_ulid(),
        )
        db.session.commit()
        flash(
            "Journal integrity issue marked false positive after clean rescan.",
            "success",
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=finance_issue_resolution test=finance_admin_issue_route_access
@bp.post(
    "/admin/issues/<string:issue_ulid>/journal-close-clean",
    endpoint="admin_issue_journal_close_clean",
)
@login_required
@roles_required("admin")
def admin_issue_journal_close_clean(issue_ulid: str):
    try:
        close_journal_integrity_after_clean_rescan(
            issue_ulid,
            actor_ulid=_actor_ulid(),
        )
        db.session.commit()
        flash("Journal integrity issue closed after clean rescan.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _redirect_issue(issue_ulid)
