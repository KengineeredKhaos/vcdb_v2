# app/slices/calendar/routes.py

from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from . import services_funding as funding_svc
from .forms import FundingDemandForm

bp = Blueprint(
    "calendar",
    __name__,
    template_folder="templates",
    static_folder=None,
    url_prefix="/calendar",
)


def _actor_ulid() -> str | None:
    return getattr(current_user, "entity_ulid", None) or getattr(
        current_user, "ulid", None
    )


def _request_id() -> str | None:
    return request.headers.get("X-Request-Id")


def _bind_funding_form_choices(form: FundingDemandForm) -> None:
    project_choices = funding_svc.list_projects_for_form()
    form.project_ulid.choices = project_choices
    form.spending_class.choices = funding_svc.get_spending_class_choices()


@bp.get("/hello")
@login_required
def hello():
    return render_template("calendar/hello.html", title="Calendar • Hello")


@bp.get("/funding-demands/new")
@login_required
def funding_demand_new():
    form = FundingDemandForm()
    _bind_funding_form_choices(form)
    return render_template(
        "calendar/funding/new.html",
        title="New Funding Demand",
        form=form,
    )


@bp.post("/funding-demands/new")
@login_required
def funding_demand_create():
    form = FundingDemandForm()
    _bind_funding_form_choices(form)

    if not form.validate_on_submit():
        return (
            render_template(
                "calendar/funding/new.html",
                title="New Funding Demand",
                form=form,
            ),
            400,
        )

    row = funding_svc.create_funding_demand(
        {
            "project_ulid": form.project_ulid.data,
            "title": form.title.data,
            "goal_cents": form.goal_cents.data,
            "deadline_date": form.deadline_date.data,
            "spending_class": form.spending_class.data or None,
            "tag_any": form.tag_any.data,
        },
        actor_ulid=_actor_ulid(),
        request_id=_request_id(),
    )
    db_commit()
    flash("Funding demand created.", "success")
    return redirect(url_for("calendar.funding_demand_detail", ulid=row.ulid))


@bp.get("/funding-demands/<ulid>")
@login_required
def funding_demand_detail(ulid: str):
    view = funding_svc.get_funding_demand_view(ulid)
    return render_template(
        "calendar/funding/detail.html",
        title=view.title,
        demand=view,
    )


@bp.get("/funding-demands/<ulid>/edit")
@login_required
def funding_demand_edit(ulid: str):
    view = funding_svc.get_funding_demand_view(ulid)

    form = FundingDemandForm(
        project_ulid=view.project_ulid,
        title=view.title,
        goal_cents=view.goal_cents,
        deadline_date=view.deadline_date,
        spending_class=view.spending_class,
        tag_any=", ".join(view.tag_any),
    )
    _bind_funding_form_choices(form)

    return render_template(
        "calendar/funding/edit.html",
        title=f"Edit • {view.title}",
        form=form,
        demand=view,
    )


@bp.post("/funding-demands/<ulid>/edit")
@login_required
def funding_demand_update(ulid: str):
    form = FundingDemandForm()
    _bind_funding_form_choices(form)

    if not form.validate_on_submit():
        view = funding_svc.get_funding_demand_view(ulid)
        return (
            render_template(
                "calendar/funding/edit.html",
                title=f"Edit • {view.title}",
                form=form,
                demand=view,
            ),
            400,
        )

    row = funding_svc.update_funding_demand(
        ulid,
        {
            "project_ulid": form.project_ulid.data,
            "title": form.title.data,
            "goal_cents": form.goal_cents.data,
            "deadline_date": form.deadline_date.data,
            "spending_class": form.spending_class.data or None,
            "tag_any": form.tag_any.data,
        },
        actor_ulid=_actor_ulid(),
        request_id=_request_id(),
    )
    db_commit()
    flash("Funding demand updated.", "success")
    return redirect(url_for("calendar.funding_demand_detail", ulid=row.ulid))


@bp.post("/funding-demands/<ulid>/publish")
@login_required
def funding_demand_publish(ulid: str):
    row = funding_svc.publish_funding_demand(
        ulid,
        actor_ulid=_actor_ulid(),
        request_id=_request_id(),
    )
    db_commit()
    flash("Funding demand published.", "success")
    return redirect(url_for("calendar.funding_demand_detail", ulid=row.ulid))


@bp.post("/funding-demands/<ulid>/unpublish")
@login_required
def funding_demand_unpublish(ulid: str):
    row = funding_svc.unpublish_funding_demand(
        ulid,
        actor_ulid=_actor_ulid(),
        request_id=_request_id(),
    )
    db_commit()
    flash("Funding demand reverted to draft.", "success")
    return redirect(url_for("calendar.funding_demand_detail", ulid=row.ulid))


def db_commit() -> None:
    from app.extensions import db

    db.session.commit()


@bp.get("/funding-demands")
@login_required
def funding_demand_list():
    status = (request.args.get("status") or "").strip() or None
    project_ulid = (request.args.get("project_ulid") or "").strip() or None

    rows = funding_svc.list_funding_demands_view(
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
