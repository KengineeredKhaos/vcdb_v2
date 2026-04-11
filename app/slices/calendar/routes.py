# app/slices/calendar/routes.py

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import select

from app.extensions import db
from app.extensions.auth_ctx import current_actor_ulid
from app.lib.request_ctx import get_actor_ulid

from . import services_budget as budget_svc
from . import services_drafts as drafts_svc
from . import services_funding as funding_svc
from .forms import (
    BudgetLineForm,
    BudgetSnapshotForm,
    DemandDraftApproveForm,
    DemandDraftForm,
    DemandDraftReturnForm,
)
from .models import Project, Task

bp = Blueprint(
    "calendar",
    __name__,
    template_folder="templates",
    static_folder=None,
    url_prefix="/calendar",
)


def _actor_ulid_or_403() -> str:
    value = (
        get_actor_ulid()
        or current_actor_ulid()
        or getattr(current_user, "entity_ulid", None)
        or getattr(current_user, "ulid", None)
    )
    text = str(value or "").strip()
    if len(text) != 26:
        abort(403)
    return text


def _request_id() -> str | None:
    return request.headers.get("X-Request-Id")


def _date_to_iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _split_csv(text: str | None) -> list[str]:
    return [x.strip() for x in str(text or "").split(",") if x.strip()]


def _project_or_404(project_ulid: str) -> Project:
    row = db.session.execute(
        select(Project).where(Project.ulid == project_ulid)
    ).scalar_one_or_none()
    if row is None:
        abort(404)
    return row


def _bind_task_choices(form: BudgetLineForm, project_ulid: str) -> None:
    project = _project_or_404(project_ulid)
    choices = [("", "Project-common cost")]
    task_rows = sorted(
        list(project.tasks or []),
        key=lambda row: (str(row.task_title or "").lower(), row.ulid),
    )
    for row in task_rows:
        label = row.task_title or row.ulid
        choices.append((row.ulid, label))
    form.task_ulid.choices = choices


def _bind_spending_choices(*forms) -> None:
    choices = [("", "-- optional --")]
    choices.extend(funding_svc.get_spending_class_choices())
    for form in forms:
        if hasattr(form, "spending_class_candidate"):
            form.spending_class_candidate.choices = choices
        if hasattr(form, "spending_class"):
            form.spending_class.choices = choices


def _budget_context(
    *,
    project_ulid: str,
    snapshot_ulid: str | None = None,
    edit_line_ulid: str | None = None,
):
    project = _project_or_404(project_ulid)
    snapshots = budget_svc.list_budget_snapshots(project_ulid)
    snapshot = None
    if snapshot_ulid:
        snapshot = budget_svc.budget_snapshot_view(snapshot_ulid)
    else:
        snapshot = budget_svc.current_budget_snapshot_view(project_ulid)
        if snapshot is None and snapshots:
            snapshot = snapshots[0]
    lines = []
    if snapshot is not None:
        lines = budget_svc.list_budget_lines(snapshot["ulid"])

    edit_line = None
    if edit_line_ulid:
        edit_line = budget_svc.budget_line_view(edit_line_ulid)

    snapshot_form = BudgetSnapshotForm()
    line_form = BudgetLineForm()
    _bind_task_choices(line_form, project_ulid)

    if edit_line is not None:
        line_form = BudgetLineForm(
            task_ulid=edit_line.get("task_ulid") or "",
            line_kind=edit_line.get("line_kind") or "",
            label=edit_line.get("label") or "",
            detail=edit_line.get("detail") or "",
            basis_qty=edit_line.get("basis_qty"),
            basis_unit=edit_line.get("basis_unit") or "",
            unit_cost_cents=edit_line.get("unit_cost_cents"),
            estimated_total_cents=edit_line.get("estimated_total_cents") or 0,
            is_offset=bool(edit_line.get("is_offset")),
            offset_kind=edit_line.get("offset_kind") or "",
            sort_order=edit_line.get("sort_order"),
        )
        _bind_task_choices(line_form, project_ulid)

    drafts = drafts_svc.list_demand_drafts(project_ulid)
    return {
        "project": project,
        "snapshots": snapshots,
        "snapshot": snapshot,
        "lines": lines,
        "edit_line": edit_line,
        "snapshot_form": snapshot_form,
        "line_form": line_form,
        "drafts": drafts,
    }


def _service_error_redirect(message: str, endpoint: str, **values):
    flash(message, "danger")
    return redirect(url_for(endpoint, **values))


def db_commit() -> None:
    db.session.commit()


@bp.get("/hello")
@login_required
def hello():
    return render_template("calendar/hello.html", title="Calendar • Hello")


@bp.get("/projects/<project_ulid>/budget")
@login_required
def project_budget_workspace(project_ulid: str):
    snapshot_ulid = (request.args.get("snapshot_ulid") or "").strip() or None
    edit_line_ulid = (
        request.args.get("edit_line_ulid") or ""
    ).strip() or None
    ctx = _budget_context(
        project_ulid=project_ulid,
        snapshot_ulid=snapshot_ulid,
        edit_line_ulid=edit_line_ulid,
    )
    return render_template(
        "calendar/budget/workspace.html",
        title=f"Budget • {ctx['project'].project_title}",
        **ctx,
    )


@bp.post("/projects/<project_ulid>/budget/snapshots/new")
@login_required
def budget_snapshot_create(project_ulid: str):
    form = BudgetSnapshotForm()
    if not form.validate_on_submit():
        ctx = _budget_context(project_ulid=project_ulid)
        return (
            render_template(
                "calendar/budget/workspace.html",
                title=f"Budget • {ctx['project'].project_title}",
                **ctx,
            ),
            400,
        )

    try:
        budget_svc.create_working_snapshot(
            project_ulid=project_ulid,
            actor_ulid=_actor_ulid_or_403(),
            snapshot_label=form.snapshot_label.data or None,
            scope_summary=form.scope_summary.data or None,
            assumptions_note=form.assumptions_note.data or None,
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
        )

    flash("Budget snapshot created.", "success")
    return redirect(
        url_for(
            "calendar.project_budget_workspace", project_ulid=project_ulid
        )
    )


@bp.post("/projects/<project_ulid>/budget/snapshots/<snapshot_ulid>/clone")
@login_required
def budget_snapshot_clone(project_ulid: str, snapshot_ulid: str):
    try:
        budget_svc.clone_snapshot(
            snapshot_ulid=snapshot_ulid,
            actor_ulid=_actor_ulid_or_403(),
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
        )

    flash("Budget snapshot cloned.", "success")
    return redirect(
        url_for(
            "calendar.project_budget_workspace", project_ulid=project_ulid
        )
    )


@bp.post(
    "/projects/<project_ulid>/budget/snapshots/<snapshot_ulid>/set-current"
)
@login_required
def budget_snapshot_set_current(project_ulid: str, snapshot_ulid: str):
    try:
        budget_svc.set_current_snapshot(
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
            actor_ulid=_actor_ulid_or_403(),
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
        )

    flash("Current snapshot changed.", "success")
    return redirect(
        url_for(
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
        )
    )


@bp.post("/projects/<project_ulid>/budget/snapshots/<snapshot_ulid>/lock")
@login_required
def budget_snapshot_lock(project_ulid: str, snapshot_ulid: str):
    try:
        budget_svc.lock_snapshot(
            snapshot_ulid=snapshot_ulid,
            actor_ulid=_actor_ulid_or_403(),
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
        )

    flash("Snapshot locked.", "success")
    return redirect(
        url_for(
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
        )
    )


@bp.post(
    "/projects/<project_ulid>/budget/snapshots/<snapshot_ulid>/lines/new"
)
@login_required
def budget_line_create(project_ulid: str, snapshot_ulid: str):
    form = BudgetLineForm()
    _bind_task_choices(form, project_ulid)
    if not form.validate_on_submit():
        ctx = _budget_context(
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
        )
        ctx["line_form"] = form
        return (
            render_template(
                "calendar/budget/workspace.html",
                title=f"Budget • {ctx['project'].project_title}",
                **ctx,
            ),
            400,
        )

    try:
        budget_svc.add_budget_line(
            snapshot_ulid=snapshot_ulid,
            actor_ulid=_actor_ulid_or_403(),
            task_ulid=form.task_ulid.data or None,
            line_kind=form.line_kind.data,
            label=form.label.data,
            detail=form.detail.data or None,
            basis_qty=form.basis_qty.data,
            basis_unit=form.basis_unit.data or None,
            unit_cost_cents=form.unit_cost_cents.data,
            estimated_total_cents=form.estimated_total_cents.data,
            is_offset=bool(form.is_offset.data),
            offset_kind=form.offset_kind.data or None,
            sort_order=form.sort_order.data,
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
        )

    flash("Budget line added.", "success")
    return redirect(
        url_for(
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
        )
    )


@bp.post("/projects/<project_ulid>/budget/lines/<line_ulid>/edit")
@login_required
def budget_line_update(project_ulid: str, line_ulid: str):
    form = BudgetLineForm()
    _bind_task_choices(form, project_ulid)
    line_view = budget_svc.budget_line_view(line_ulid)
    snapshot_ulid = line_view["budget_snapshot_ulid"]
    if not form.validate_on_submit():
        ctx = _budget_context(
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
            edit_line_ulid=line_ulid,
        )
        ctx["line_form"] = form
        return (
            render_template(
                "calendar/budget/workspace.html",
                title=f"Budget • {ctx['project'].project_title}",
                **ctx,
            ),
            400,
        )

    try:
        budget_svc.update_budget_line(
            line_ulid=line_ulid,
            actor_ulid=_actor_ulid_or_403(),
            task_ulid=form.task_ulid.data or None,
            line_kind=form.line_kind.data,
            label=form.label.data,
            detail=form.detail.data or None,
            basis_qty=form.basis_qty.data,
            basis_unit=form.basis_unit.data or None,
            unit_cost_cents=form.unit_cost_cents.data,
            estimated_total_cents=form.estimated_total_cents.data,
            is_offset=bool(form.is_offset.data),
            offset_kind=form.offset_kind.data or None,
            sort_order=form.sort_order.data,
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
            edit_line_ulid=line_ulid,
        )

    flash("Budget line updated.", "success")
    return redirect(
        url_for(
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
        )
    )


@bp.post("/projects/<project_ulid>/budget/lines/<line_ulid>/delete")
@login_required
def budget_line_delete(project_ulid: str, line_ulid: str):
    try:
        line_view = budget_svc.budget_line_view(line_ulid)
        snapshot_ulid = line_view["budget_snapshot_ulid"]
        budget_svc.delete_budget_line(
            line_ulid=line_ulid,
            actor_ulid=_actor_ulid_or_403(),
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
        )

    flash("Budget line deleted.", "success")
    return redirect(
        url_for(
            "calendar.project_budget_workspace",
            project_ulid=project_ulid,
            snapshot_ulid=snapshot_ulid,
        )
    )


@bp.get("/projects/<project_ulid>/demand-drafts/new")
@login_required
def demand_draft_new(project_ulid: str):
    project = _project_or_404(project_ulid)
    snapshot_ulid = (request.args.get("snapshot_ulid") or "").strip() or ""
    form = DemandDraftForm(snapshot_ulid=snapshot_ulid)
    _bind_spending_choices(form)
    return render_template(
        "calendar/drafts/new.html",
        title=f"New Demand Draft • {project.project_title}",
        project=project,
        form=form,
    )


@bp.post("/projects/<project_ulid>/demand-drafts/new")
@login_required
def demand_draft_create(project_ulid: str):
    project = _project_or_404(project_ulid)
    form = DemandDraftForm()
    _bind_spending_choices(form)
    if not form.validate_on_submit():
        return (
            render_template(
                "calendar/drafts/new.html",
                title=f"New Demand Draft • {project.project_title}",
                project=project,
                form=form,
            ),
            400,
        )

    try:
        view = drafts_svc.create_draft_from_snapshot(
            project_ulid=project_ulid,
            snapshot_ulid=form.snapshot_ulid.data,
            actor_ulid=_actor_ulid_or_403(),
            title=form.title.data,
            summary=form.summary.data or None,
            scope_summary=form.scope_summary.data or None,
            requested_amount_cents=form.requested_amount_cents.data,
            deadline_date=_date_to_iso(form.deadline_date.data),
            spending_class_candidate=(
                form.spending_class_candidate.data or None
            ),
            source_profile_key=form.source_profile_key.data or None,
            ops_support_planned=bool(form.ops_support_planned.data),
            tag_any=form.tag_any.data or None,
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return (
            render_template(
                "calendar/drafts/new.html",
                title=f"New Demand Draft • {project.project_title}",
                project=project,
                form=form,
            ),
            400,
        )

    flash("Demand draft created.", "success")
    return redirect(
        url_for("calendar.demand_draft_detail", draft_ulid=view["ulid"])
    )


@bp.get("/demand-drafts/<draft_ulid>")
@login_required
def demand_draft_detail(draft_ulid: str):
    draft = drafts_svc.demand_draft_view(draft_ulid)
    project = _project_or_404(draft["project_ulid"])
    edit_form = DemandDraftForm(
        snapshot_ulid=draft["budget_snapshot_ulid"],
        title=draft["title"],
        summary=draft.get("summary") or "",
        scope_summary=draft.get("scope_summary") or "",
        requested_amount_cents=draft.get("requested_amount_cents"),
        spending_class_candidate=draft.get("spending_class_candidate") or "",
        source_profile_key=draft.get("source_profile_key") or "",
        ops_support_planned=bool(draft.get("ops_support_planned")),
        tag_any=", ".join(draft.get("tag_any") or ()),
        governance_note=draft.get("governance_note") or "",
    )
    _bind_spending_choices(edit_form)
    return_form = DemandDraftReturnForm()
    decision = draft.get("approved_semantics_json") or {}
    approve_form = DemandDraftApproveForm(
        spending_class=(
            decision.get("approved_spending_class")
            or draft.get("spending_class_candidate")
            or ""
        ),
        source_profile_key=(
            decision.get("approved_source_profile_key")
            or draft.get("source_profile_key")
            or ""
        ),
        tag_any=", ".join(
            decision.get("approved_tag_any", []) or draft.get("tag_any") or []
        ),
    )
    _bind_spending_choices(edit_form, approve_form)
    return render_template(
        "calendar/drafts/detail.html",
        title=f"Demand Draft • {draft['title']}",
        project=project,
        draft=draft,
        edit_form=edit_form,
        return_form=return_form,
        approve_form=approve_form,
    )


@bp.post("/demand-drafts/<draft_ulid>/edit")
@login_required
def demand_draft_update(draft_ulid: str):
    draft = drafts_svc.demand_draft_view(draft_ulid)
    form = DemandDraftForm()
    _bind_spending_choices(form)
    if not form.validate_on_submit():
        project = _project_or_404(draft["project_ulid"])
        approve_form = DemandDraftApproveForm()
        return_form = DemandDraftReturnForm()
        _bind_spending_choices(form, approve_form)
        return (
            render_template(
                "calendar/drafts/detail.html",
                title=f"Demand Draft • {draft['title']}",
                project=project,
                draft=draft,
                edit_form=form,
                return_form=return_form,
                approve_form=approve_form,
            ),
            400,
        )

    try:
        drafts_svc.update_draft(
            draft_ulid=draft_ulid,
            actor_ulid=_actor_ulid_or_403(),
            title=form.title.data,
            summary=form.summary.data or None,
            scope_summary=form.scope_summary.data or None,
            requested_amount_cents=form.requested_amount_cents.data,
            deadline_date=_date_to_iso(form.deadline_date.data),
            spending_class_candidate=(
                form.spending_class_candidate.data or None
            ),
            source_profile_key=form.source_profile_key.data or None,
            ops_support_planned=bool(form.ops_support_planned.data),
            tag_any=form.tag_any.data or None,
            governance_note=form.governance_note.data or None,
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.demand_draft_detail",
            draft_ulid=draft_ulid,
        )

    flash("Demand draft updated.", "success")
    return redirect(
        url_for("calendar.demand_draft_detail", draft_ulid=draft_ulid)
    )


@bp.post("/demand-drafts/<draft_ulid>/ready")
@login_required
def demand_draft_mark_ready(draft_ulid: str):
    try:
        drafts_svc.mark_draft_ready_for_review(
            draft_ulid=draft_ulid,
            actor_ulid=_actor_ulid_or_403(),
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.demand_draft_detail",
            draft_ulid=draft_ulid,
        )

    flash("Demand draft marked ready for review.", "success")
    return redirect(
        url_for("calendar.demand_draft_detail", draft_ulid=draft_ulid)
    )


@bp.post("/demand-drafts/<draft_ulid>/submit")
@login_required
def demand_draft_submit(draft_ulid: str):
    try:
        drafts_svc.submit_draft_for_governance_review(
            draft_ulid=draft_ulid,
            actor_ulid=_actor_ulid_or_403(),
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.demand_draft_detail",
            draft_ulid=draft_ulid,
        )

    flash("Demand draft submitted for Governance review.", "success")
    return redirect(
        url_for("calendar.demand_draft_detail", draft_ulid=draft_ulid)
    )


@bp.post("/demand-drafts/<draft_ulid>/return")
@login_required
def demand_draft_return(draft_ulid: str):
    form = DemandDraftReturnForm()
    if not form.validate_on_submit():
        return _service_error_redirect(
            "Return note is required.",
            "calendar.demand_draft_detail",
            draft_ulid=draft_ulid,
        )

    try:
        drafts_svc.return_draft_for_revision(
            draft_ulid=draft_ulid,
            actor_ulid=_actor_ulid_or_403(),
            note=form.note.data,
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.demand_draft_detail",
            draft_ulid=draft_ulid,
        )

    flash("Demand draft returned for revision.", "warning")
    return redirect(
        url_for("calendar.demand_draft_detail", draft_ulid=draft_ulid)
    )


@bp.post("/demand-drafts/<draft_ulid>/approve")
@login_required
def demand_draft_approve(draft_ulid: str):
    form = DemandDraftApproveForm()
    _bind_spending_choices(form)
    if not form.validate_on_submit():
        return _service_error_redirect(
            "Approval form is invalid.",
            "calendar.demand_draft_detail",
            draft_ulid=draft_ulid,
        )

    review_overrides = {
        "spending_class_candidate": form.spending_class.data or None,
        "source_profile_key_candidate": (
            form.source_profile_key.data or None
        ),
        "tag_any": _split_csv(form.tag_any.data),
    }
    try:
        drafts_svc.approve_draft_for_publish(
            draft_ulid=draft_ulid,
            actor_ulid=_actor_ulid_or_403(),
            review_overrides=review_overrides,
            request_id=_request_id(),
        )

        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.demand_draft_detail",
            draft_ulid=draft_ulid,
        )

    flash("Demand draft approved for publish.", "success")
    return redirect(
        url_for("calendar.demand_draft_detail", draft_ulid=draft_ulid)
    )


@bp.post("/demand-drafts/<draft_ulid>/promote")
@login_required
def demand_draft_promote(draft_ulid: str):
    try:
        view = drafts_svc.promote_draft_to_funding_demand(
            draft_ulid=draft_ulid,
            actor_ulid=_actor_ulid_or_403(),
            request_id=_request_id(),
        )
        db_commit()
    except (LookupError, RuntimeError, ValueError) as exc:
        db.session.rollback()
        return _service_error_redirect(
            str(exc),
            "calendar.demand_draft_detail",
            draft_ulid=draft_ulid,
        )

    flash("Draft promoted to published funding demand.", "success")

    funding_view = dict(view.get("funding_demand") or {})
    funding_ulid = funding_view.get(
        "funding_demand_ulid"
    ) or funding_view.get("ulid")

    if not funding_ulid:
        raise RuntimeError(
            "Promotion succeeded but no funding demand ULID was returned."
        )

    return redirect(
        url_for(
            "calendar.funding_demand_detail",
            ulid=funding_ulid,
        )
    )


@bp.get("/funding-demands/<ulid>")
@login_required
def funding_demand_detail(ulid: str):
    view = funding_svc.get_funding_demand_view(ulid)
    return render_template(
        "calendar/funding/detail.html",
        title=view.title,
        demand=view,
    )


@bp.get("/funding-demands")
@login_required
def funding_demand_list():
    status = (request.args.get("status") or "").strip() or None
    project_ulid = (request.args.get("project_ulid") or "").strip() or None
    rows = funding_svc.list_published_funding_demands(
        project_ulid=project_ulid,
        status=status,
    )
    return render_template(
        "calendar/funding/list.html",
        title="Funding Demands",
        rows=rows,
        selected_status=status or "",
        selected_project_ulid=project_ulid or "",
        status_choices=funding_svc.get_funding_demand_status_choices(),
        project_choices=[("", "All projects")]
        + funding_svc.list_projects_for_form(),
    )
