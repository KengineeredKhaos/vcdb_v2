# app/slices/sponsors/routes_funding.py

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
from .forms_funding import SponsorFundingIntentForm

bp_funding = Blueprint(
    "sponsors_funding",
    __name__,
    template_folder="templates",
    url_prefix="/sponsors",
)


def _actor_ulid() -> str | None:
    return getattr(current_user, "entity_ulid", None) or getattr(
        current_user, "ulid", None
    )


def _request_id() -> str | None:
    return request.headers.get("X-Request-Id")


def _bind_form_choices(form: SponsorFundingIntentForm) -> None:
    form.sponsor_entity_ulid.choices = funding_svc.list_sponsors_for_form()


def _db_commit() -> None:
    from app.extensions import db

    db.session.commit()


@bp_funding.get("/funding-opportunities")
@login_required
def funding_opportunity_list():
    rows = funding_svc.list_open_funding_opportunities()
    return render_template(
        "sponsors/funding/opportunities_list.html",
        title="Funding Opportunities",
        rows=rows,
    )


@bp_funding.get("/funding-opportunities/<funding_demand_ulid>")
@login_required
def funding_opportunity_detail(funding_demand_ulid: str):
    demand = funding_svc.get_funding_opportunity(funding_demand_ulid)
    intents = funding_svc.list_funding_intents_for_demand(funding_demand_ulid)
    return render_template(
        "sponsors/funding/opportunity_detail.html",
        title=demand.title,
        demand=demand,
        intents=intents,
    )


@bp_funding.get("/funding-intents/new")
@login_required
def funding_intent_new():
    funding_demand_ulid = (
        request.args.get("funding_demand_ulid") or ""
    ).strip()

    form = SponsorFundingIntentForm(
        funding_demand_ulid=funding_demand_ulid,
        status="draft",
        intent_kind="pledge",
        amount_cents=0,
    )
    _bind_form_choices(form)

    demand = None
    if funding_demand_ulid:
        demand = funding_svc.get_funding_opportunity(funding_demand_ulid)

    return render_template(
        "sponsors/funding/intent_new.html",
        title="New Funding Intent",
        form=form,
        demand=demand,
    )


@bp_funding.post("/funding-intents/new")
@login_required
def funding_intent_create():
    form = SponsorFundingIntentForm()
    _bind_form_choices(form)

    demand = None
    funding_demand_ulid = (form.funding_demand_ulid.data or "").strip()
    if funding_demand_ulid:
        try:
            demand = funding_svc.get_funding_opportunity(funding_demand_ulid)
        except Exception:
            demand = None

    if not form.validate_on_submit():
        return (
            render_template(
                "sponsors/funding/intent_new.html",
                title="New Funding Intent",
                form=form,
                demand=demand,
            ),
            400,
        )

    row = funding_svc.create_funding_intent(
        {
            "sponsor_entity_ulid": form.sponsor_entity_ulid.data,
            "funding_demand_ulid": form.funding_demand_ulid.data,
            "intent_kind": form.intent_kind.data,
            "amount_cents": form.amount_cents.data,
            "status": form.status.data,
            "note": form.note.data,
        },
        actor_ulid=_actor_ulid(),
        request_id=_request_id(),
    )
    _db_commit()
    flash("Funding intent created.", "success")
    return redirect(
        url_for(
            "sponsors_funding.funding_opportunity_detail",
            funding_demand_ulid=row.funding_demand_ulid,
        )
    )


@bp_funding.get("/funding-intents/<intent_ulid>/edit")
@login_required
def funding_intent_edit(intent_ulid: str):
    intent = funding_svc.get_funding_intent_view(intent_ulid)
    demand = funding_svc.get_funding_opportunity(intent.funding_demand_ulid)

    form = SponsorFundingIntentForm(
        sponsor_entity_ulid=intent.sponsor_entity_ulid,
        funding_demand_ulid=intent.funding_demand_ulid,
        intent_kind=intent.intent_kind,
        amount_cents=intent.amount_cents,
        status=intent.status,
        note=intent.note,
    )
    _bind_form_choices(form)

    return render_template(
        "sponsors/funding/intent_edit.html",
        title="Edit Funding Intent",
        form=form,
        intent=intent,
        demand=demand,
    )


@bp_funding.post("/funding-intents/<intent_ulid>/edit")
@login_required
def funding_intent_update(intent_ulid: str):
    intent = funding_svc.get_funding_intent_view(intent_ulid)

    form = SponsorFundingIntentForm()
    _bind_form_choices(form)

    demand = None
    funding_demand_ulid = (form.funding_demand_ulid.data or "").strip()
    if funding_demand_ulid:
        try:
            demand = funding_svc.get_funding_opportunity(funding_demand_ulid)
        except Exception:
            demand = None

    if not form.validate_on_submit():
        return (
            render_template(
                "sponsors/funding/intent_edit.html",
                title="Edit Funding Intent",
                form=form,
                intent=intent,
                demand=demand,
            ),
            400,
        )

    row = funding_svc.update_funding_intent(
        intent_ulid,
        {
            "sponsor_entity_ulid": form.sponsor_entity_ulid.data,
            "funding_demand_ulid": form.funding_demand_ulid.data,
            "intent_kind": form.intent_kind.data,
            "amount_cents": form.amount_cents.data,
            "status": form.status.data,
            "note": form.note.data,
        },
        actor_ulid=_actor_ulid(),
        request_id=_request_id(),
    )
    _db_commit()
    flash("Funding intent updated.", "success")
    return redirect(
        url_for(
            "sponsors_funding.funding_opportunity_detail",
            funding_demand_ulid=row.funding_demand_ulid,
        )
    )
