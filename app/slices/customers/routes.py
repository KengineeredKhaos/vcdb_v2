# app/slices/customers/routes.py
from __future__ import annotations

import secrets
from contextlib import suppress
from typing import Any

from flask import (
    Blueprint,
    abort,
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
from app.extensions.errors import ContractError
from app.lib.request_ctx import (
    ensure_request_id,
    get_actor_ulid,
    set_actor_ulid,
    set_request_id,
)
from app.lib.security import rbac

from . import admin_review_services as admin_review_svc
from . import services as svc
from .models import Customer, CustomerEligibility
from .taxonomy import (
    NEED_LABELS,
    NEEDS_CATEGORY_KEY,
    REFERRAL_MATCH_BUCKETS,
    REFERRAL_METHODS,
    REFERRAL_OUTCOMES,
)


def _try_entity_card(entity_ulid: str | None):
    """Best-effort entity name card for UI chrome (PII-minimal)."""
    if not entity_ulid:
        return None
    try:
        from app.extensions.contracts import entity_v2

        return entity_v2.get_entity_name_card(entity_ulid)
    except Exception:
        return None


bp = Blueprint(
    "customers",
    __name__,
    template_folder="templates",
    static_folder=None,
    url_prefix="/customers",
)
"""
Dataset Descriptions

1. Customers List (dataset #1)
2. Customer Overview (dataset #2)
3. History Timeline (dataset #5)
4. Eligibility Step (dataset #3)
5. Needs Assessment (dataset #4)
6. History Details (dataset #6)
7. Admin Inbox (dataset #7)
"""

# -----------------
# Context injection
# -----------------


@bp.before_request
def _inject_request_context() -> None:
    # Always mint a request_id for this request.
    ensure_request_id()

    # If authenticated, seed actor_ulid into request_ctx.
    actor = auth_ctx.current_actor_ulid()
    set_actor_ulid(actor)


def _ctx_ro() -> str:
    """Read-only routes: ensure request_id exists, return it."""
    return ensure_request_id()


def _ctx_mut() -> tuple[str, str]:
    """Mutating routes: adopt carried request_id; require actor_ulid."""
    incoming = (request.args.get("request_id") or "").strip() or (
        request.form.get("request_id") or ""
    ).strip()

    rid = incoming or ensure_request_id()

    actor = get_actor_ulid()
    if not actor:
        abort(403)

    set_request_id(rid)
    return rid, actor


def _arg_int(key: str, default: int, *, lo: int = 1, hi: int = 200) -> int:
    with suppress(Exception):
        v = int(request.args.get(key, default))
        if v < lo:
            return lo
        if v > hi:
            return hi
        return v
    return default


# -----------------
# Wizard step keys
# -----------------

STEP_ELIGIBILITY = "eligibility"
STEP_NEEDS_T1 = "needs_tier1"
STEP_NEEDS_T2 = "needs_tier2"
STEP_NEEDS_T3 = "needs_tier3"
STEP_REVIEW = "review"
STEP_DONE = "done"

_STEP_TO_ENDPOINT: dict[str, str] = {
    STEP_ELIGIBILITY: "customers.intake_eligibility_get",
    STEP_NEEDS_T1: "customers.intake_needs_tier1_get",
    STEP_NEEDS_T2: "customers.intake_needs_tier2_get",
    STEP_NEEDS_T3: "customers.intake_needs_tier3_get",
    STEP_REVIEW: "customers.intake_review_get",
    STEP_DONE: "customers.intake_done_get",
}


# -----------------
# Nonce helpers
# -----------------


def _wiz_key(step: str, entity_ulid: str) -> str:
    return f"custwiz:{entity_ulid}:{step}"


def _wiz_issue_nonce(step: str, entity_ulid: str) -> str:
    k = _wiz_key(step, entity_ulid)
    token = secrets.token_urlsafe(16)
    session[k] = token
    return token


def _wiz_expected_nonce(step: str, entity_ulid: str) -> str | None:
    return session.get(_wiz_key(step, entity_ulid))


def _wiz_expect_nonce(
    step: str, entity_ulid: str, posted: str | None
) -> bool:
    exp = _wiz_expected_nonce(step, entity_ulid)
    return bool(exp and posted and secrets.compare_digest(exp, posted))


def _wiz_consume_nonce(step: str, entity_ulid: str) -> None:
    session.pop(_wiz_key(step, entity_ulid), None)


# -----------------
# Wizard resume logic
# -----------------


def wizard_next_step(entity_ulid: str) -> str:
    """
    Deterministic "resume" logic for stale submits / deep links.

    Keep this simple and staged:
    - If eligibility is incomplete -> eligibility
    - Else if Tier 1 is not assessed -> tier1
    - Else if Tier 2 is not assessed -> tier2
    - Else if Tier 3 is not assessed -> tier3
    - Else if intake_step is complete -> done
    - Else -> review
    """
    c = db.session.get(Customer, entity_ulid)
    if c is None:
        return STEP_ELIGIBILITY

    if c.intake_step == "complete":
        return STEP_DONE
    if not c.eligibility_complete:
        return STEP_ELIGIBILITY
    if not c.tier1_assessed:
        return STEP_NEEDS_T1
    if not c.tier2_assessed:
        return STEP_NEEDS_T2
    if not c.tier3_assessed:
        return STEP_NEEDS_T3
    return STEP_REVIEW


def _goto_step(entity_ulid: str, step: str) -> Any:
    ep = _STEP_TO_ENDPOINT[step]
    return redirect(url_for(ep, entity_ulid=entity_ulid))


# -----------------
# Entry point
# -----------------


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/intake/start/<entity_ulid>")
@login_required
def intake_start(entity_ulid: str):
    rid, actor = _ctx_mut()

    dto = svc.ensure_customer_facets(
        entity_ulid=entity_ulid,
        request_id=rid,
        actor_ulid=actor,
    )
    db.session.commit()

    step = dto.next_step or wizard_next_step(entity_ulid)
    return _goto_step(entity_ulid, step)


# -----------------
# Dataset #1
# Customers List
# -----------------


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/")
@login_required
def customers_list_get():
    _ctx_ro()
    page = _arg_int("page", 1, lo=1, hi=10_000)
    per_page = _arg_int("per_page", 25, lo=5, hi=200)
    p, labels = svc.list_customer_summaries_with_labels(
        page=page,
        per_page=per_page,
    )
    return render_template(
        "customers/list.html",
        page=p,
        labels=labels,
    )


# -----------------
# Dataset #2
# Customer Overview
# -----------------


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/<entity_ulid>")
@login_required
def customer_overview_get(entity_ulid: str):
    _ctx_ro()
    vm = svc.get_customer_overview_vm(entity_ulid)
    return render_template(
        "customers/overview.html",
        entity_ulid=entity_ulid,
        entity_card=_try_entity_card(entity_ulid),
        display_name=vm.display_name,
        dash=vm.dash,
        elig=vm.elig,
        ratings=vm.ratings,
        reassess_due=vm.reassess_due,
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/<entity_ulid>/providers")
@login_required
def customer_provider_matches_get(entity_ulid: str):
    _ctx_ro()
    need_key = (request.args.get("need_key") or "").strip().lower()
    try:
        vm = svc.get_provider_match_vm(
            entity_ulid=entity_ulid,
            need_key=need_key or None,
            include_adjacent=True,
        )
    except ValueError:
        abort(400)
    except ContractError as exc:
        abort(exc.http_status)

    return render_template(
        "customers/provider_matches.html",
        entity_ulid=entity_ulid,
        entity_card=_try_entity_card(entity_ulid),
        vm=vm,
    )


# -----------------
# Dataset #5/#6
# History Timeline
#  Details
# -----------------


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/<entity_ulid>/history")
@login_required
def customer_history_timeline_get(entity_ulid: str):
    _ctx_ro()
    display_name = svc.get_entity_display_name(entity_ulid)
    page = _arg_int("page", 1, lo=1, hi=10_000)
    per_page = _arg_int("per_page", 25, lo=5, hi=200)
    p = svc.list_customer_history_items(
        entity_ulid=entity_ulid,
        page=page,
        per_page=per_page,
    )
    return render_template(
        "customers/history_timeline.html",
        entity_ulid=entity_ulid,
        entity_card=_try_entity_card(entity_ulid),
        display_name=display_name,
        page=p,
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/<entity_ulid>/history/<history_ulid>")
@login_required
def customer_history_detail_get(entity_ulid: str, history_ulid: str):
    _ctx_ro()
    display_name = svc.get_entity_display_name(entity_ulid)
    d = svc.get_customer_history_detail_public(
        entity_ulid=entity_ulid,
        history_ulid=history_ulid,
    )
    return render_template(
        "customers/history_detail.html",
        entity_ulid=entity_ulid,
        entity_card=_try_entity_card(entity_ulid),
        display_name=display_name,
        detail=d,
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/<entity_ulid>/referrals/new")
@login_required
def customer_referral_new_get(entity_ulid: str):
    _ctx_ro()
    seed = svc.get_referral_compose_seed(
        entity_ulid=entity_ulid,
        resource_ulid=request.args.get("resource_ulid") or None,
        need_key=request.args.get("need_key") or None,
        match_bucket=request.args.get("match_bucket") or None,
        method=request.args.get("method") or None,
        synopsis=request.args.get("synopsis") or None,
        note=request.args.get("note") or None,
    )
    return render_template(
        "customers/referral_new.html",
        entity_ulid=entity_ulid,
        entity_card=_try_entity_card(entity_ulid),
        display_name=svc.get_entity_display_name(entity_ulid),
        seed=seed,
        need_keys=NEEDS_CATEGORY_KEY,
        need_labels=NEED_LABELS,
        methods=REFERRAL_METHODS,
        match_buckets=REFERRAL_MATCH_BUCKETS,
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.post("/<entity_ulid>/referrals/new")
@login_required
def customer_referral_new_post(entity_ulid: str):
    rid, actor = _ctx_mut()
    try:
        result = svc.record_resource_referral(
            entity_ulid=entity_ulid,
            resource_ulid=request.form.get("resource_ulid", ""),
            need_key=request.form.get("need_key", ""),
            method=request.form.get("method", ""),
            synopsis=request.form.get("synopsis", ""),
            actor_ulid=actor,
            request_id=rid,
            match_bucket=request.form.get("match_bucket") or None,
            note=request.form.get("note") or None,
        )
        db.session.commit()
        flash("Referral recorded in history.", "success")
        return redirect(
            url_for(
                "customers.customer_history_detail_get",
                entity_ulid=entity_ulid,
                history_ulid=result["history_ulid"],
            )
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
        seed = svc.get_referral_compose_seed(
            entity_ulid=entity_ulid,
            resource_ulid=request.form.get("resource_ulid") or None,
            need_key=request.form.get("need_key") or None,
            match_bucket=request.form.get("match_bucket") or None,
            method=request.form.get("method") or None,
            synopsis=request.form.get("synopsis") or None,
            note=request.form.get("note") or None,
        )
        return render_template(
            "customers/referral_new.html",
            entity_ulid=entity_ulid,
            entity_card=_try_entity_card(entity_ulid),
            display_name=svc.get_entity_display_name(entity_ulid),
            seed=seed,
            need_keys=NEEDS_CATEGORY_KEY,
            need_labels=NEED_LABELS,
            methods=REFERRAL_METHODS,
            match_buckets=REFERRAL_MATCH_BUCKETS,
        )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/<entity_ulid>/referrals/outcomes/new")
@login_required
def referral_outcome_new_get(entity_ulid: str):
    _ctx_ro()
    history_ulid = request.args.get("history_ulid") or None
    if history_ulid:
        seed = svc.get_referral_seed_from_history(
            entity_ulid=entity_ulid,
            history_ulid=history_ulid,
        )
    else:
        seed = svc.get_referral_outcome_compose_seed(
            entity_ulid=entity_ulid,
            referral_ulid=request.args.get("referral_ulid") or None,
            resource_ulid=request.args.get("resource_ulid") or None,
            need_key=request.args.get("need_key") or None,
            outcome=request.args.get("outcome") or None,
            synopsis=request.args.get("synopsis") or None,
            note=request.args.get("note") or None,
        )
    return render_template(
        "customers/referral_outcome_new.html",
        entity_ulid=entity_ulid,
        entity_card=_try_entity_card(entity_ulid),
        display_name=svc.get_entity_display_name(entity_ulid),
        seed=seed,
        need_keys=NEEDS_CATEGORY_KEY,
        need_labels=NEED_LABELS,
        outcomes=REFERRAL_OUTCOMES,
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.post("/<entity_ulid>/referrals/outcomes/new")
@login_required
def referral_outcome_new_post(entity_ulid: str):
    rid, actor = _ctx_mut()
    try:
        result = svc.record_referral_outcome(
            entity_ulid=entity_ulid,
            referral_ulid=request.form.get("referral_ulid", ""),
            resource_ulid=request.form.get("resource_ulid", ""),
            need_key=request.form.get("need_key", ""),
            outcome=request.form.get("outcome", ""),
            synopsis=request.form.get("synopsis", ""),
            actor_ulid=actor,
            request_id=rid,
            note=request.form.get("note") or None,
        )
        db.session.commit()
        flash("Referral outcome recorded in history.", "success")
        return redirect(
            url_for(
                "customers.customer_history_detail_get",
                entity_ulid=entity_ulid,
                history_ulid=result["history_ulid"],
            )
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
        seed = svc.get_referral_outcome_compose_seed(
            entity_ulid=entity_ulid,
            referral_ulid=request.form.get("referral_ulid") or None,
            resource_ulid=request.form.get("resource_ulid") or None,
            need_key=request.form.get("need_key") or None,
            outcome=request.form.get("outcome") or None,
            synopsis=request.form.get("synopsis") or None,
            note=request.form.get("note") or None,
        )
        return render_template(
            "customers/referral_outcome_new.html",
            entity_ulid=entity_ulid,
            entity_card=_try_entity_card(entity_ulid),
            display_name=svc.get_entity_display_name(entity_ulid),
            seed=seed,
            need_keys=NEEDS_CATEGORY_KEY,
            need_labels=NEED_LABELS,
            outcomes=REFERRAL_OUTCOMES,
        )


# -----------------
# Eligibility step
# -----------------


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/intake/<entity_ulid>/eligibility")
@login_required
def intake_eligibility_get(entity_ulid: str):
    _ctx_ro()
    snap = svc.get_customer_eligibility(entity_ulid)
    wiz_nonce = _wiz_issue_nonce(STEP_ELIGIBILITY, entity_ulid)

    return render_template(
        "customers/intake_eligibility.html",
        entity_ulid=entity_ulid,
        entity_card=_try_entity_card(entity_ulid),
        snap=snap,
        wiz_nonce=wiz_nonce,
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.post("/intake/<entity_ulid>/eligibility")
@login_required
def intake_eligibility_post(entity_ulid: str):
    if not _wiz_expect_nonce(
        STEP_ELIGIBILITY,
        entity_ulid,
        request.form.get("wiz_nonce"),
    ):
        flash("Stale page. Resuming current step.", "warning")
        return _goto_step(entity_ulid, wizard_next_step(entity_ulid))

    rid, actor = _ctx_mut()

    try:
        dto = svc.set_customer_eligibility(
            entity_ulid=entity_ulid,
            veteran_status=request.form.get("veteran_status", ""),
            housing_status=request.form.get("housing_status", ""),
            veteran_method=request.form.get("veteran_method") or None,
            branch=request.form.get("branch") or None,
            era=request.form.get("era") or None,
            request_id=rid,
            actor_ulid=actor,
        )
        db.session.commit()
        _wiz_consume_nonce(STEP_ELIGIBILITY, entity_ulid)
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(
            url_for(
                "customers.intake_eligibility_get", entity_ulid=entity_ulid
            )
        )

    step = dto.next_step or wizard_next_step(entity_ulid)
    return _goto_step(entity_ulid, step)


# -----------------
# Needs steps
# (Tier 1/2/3)
# -----------------


def _needs_get(entity_ulid: str, step: str, template: str):
    _ctx_ro()
    dash = svc.get_customer_dashboard(entity_ulid)
    wiz_nonce = _wiz_issue_nonce(step, entity_ulid)
    ratings = svc.get_current_needs_ratings(entity_ulid)
    return render_template(
        template,
        entity_ulid=entity_ulid,
        entity_card=_try_entity_card(entity_ulid),
        dash=dash,
        wiz_nonce=wiz_nonce,
        ratings=ratings,
    )


def _needs_post(
    *,
    entity_ulid: str,
    step: str,
    ratings: dict[str, str],
    next_step: str,
):
    if not _wiz_expect_nonce(
        step, entity_ulid, request.form.get("wiz_nonce")
    ):
        flash("Stale page. Resuming current step.", "warning")
        return _goto_step(entity_ulid, wizard_next_step(entity_ulid))

    rid, actor = _ctx_mut()

    try:
        svc.needs_begin(
            entity_ulid=entity_ulid,
            request_id=rid,
            actor_ulid=actor,
        )

        dto = svc.needs_set_block(
            entity_ulid=entity_ulid,
            ratings=ratings,
            request_id=rid,
            actor_ulid=actor,
            next_step=next_step,
        )
        db.session.commit()
        _wiz_consume_nonce(step, entity_ulid)
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return _goto_step(entity_ulid, step)

    step2 = dto.next_step or wizard_next_step(entity_ulid)
    return _goto_step(entity_ulid, step2)


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/intake/<entity_ulid>/needs/tier1")
@login_required
def intake_needs_tier1_get(entity_ulid: str):
    return _needs_get(
        entity_ulid,
        STEP_NEEDS_T1,
        "customers/intake_needs_tier1.html",
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.post("/intake/<entity_ulid>/needs/tier1")
@login_required
def intake_needs_tier1_post(entity_ulid: str):
    ratings = {
        "food": request.form.get("food", "unknown"),
        "hygiene": request.form.get("hygiene", "unknown"),
        "health": request.form.get("health", "unknown"),
        "housing": request.form.get("housing", "unknown"),
        "clothing": request.form.get("clothing", "unknown"),
    }
    return _needs_post(
        entity_ulid=entity_ulid,
        step=STEP_NEEDS_T1,
        ratings=ratings,
        next_step=STEP_NEEDS_T2,
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/intake/<entity_ulid>/needs/tier2")
@login_required
def intake_needs_tier2_get(entity_ulid: str):
    return _needs_get(
        entity_ulid,
        STEP_NEEDS_T2,
        "customers/intake_needs_tier2.html",
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.post("/intake/<entity_ulid>/needs/tier2")
@login_required
def intake_needs_tier2_post(entity_ulid: str):
    ratings = {
        "income": request.form.get("income", "unknown"),
        "employment": request.form.get("employment", "unknown"),
        "transportation": request.form.get("transportation", "unknown"),
        "education": request.form.get("education", "unknown"),
    }
    return _needs_post(
        entity_ulid=entity_ulid,
        step=STEP_NEEDS_T2,
        ratings=ratings,
        next_step=STEP_NEEDS_T3,
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/intake/<entity_ulid>/needs/tier3")
@login_required
def intake_needs_tier3_get(entity_ulid: str):
    return _needs_get(
        entity_ulid,
        STEP_NEEDS_T3,
        "customers/intake_needs_tier3.html",
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.post("/intake/<entity_ulid>/needs/tier3")
@login_required
def intake_needs_tier3_post(entity_ulid: str):
    ratings = {
        "family": request.form.get("family", "unknown"),
        "peergroup": request.form.get("peergroup", "unknown"),
        "tech": request.form.get("tech", "unknown"),
    }
    return _needs_post(
        entity_ulid=entity_ulid,
        step=STEP_NEEDS_T3,
        ratings=ratings,
        next_step=STEP_REVIEW,
    )


# -----------------
# Review / Complete / Done
# -----------------


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/intake/<entity_ulid>/review")
@login_required
def intake_review_get(entity_ulid: str):
    _ctx_ro()
    dash = svc.get_customer_dashboard(entity_ulid)
    wiz_nonce = _wiz_issue_nonce(STEP_REVIEW, entity_ulid)
    ratings = svc.get_current_needs_ratings(entity_ulid)
    return render_template(
        "customers/intake_review.html",
        entity_ulid=entity_ulid,
        entity_card=_try_entity_card(entity_ulid),
        dash=dash,
        wiz_nonce=wiz_nonce,
        ratings=ratings,
    )


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.post("/intake/<entity_ulid>/complete")
@login_required
def intake_complete_post(entity_ulid: str):
    if not _wiz_expect_nonce(
        STEP_REVIEW, entity_ulid, request.form.get("wiz_nonce")
    ):
        flash("Stale page. Resuming current step.", "warning")
        return _goto_step(entity_ulid, wizard_next_step(entity_ulid))

    rid, actor = _ctx_mut()
    try:
        dto = svc.needs_complete(
            entity_ulid=entity_ulid,
            request_id=rid,
            actor_ulid=actor,
        )

        if dto.history_ulid:
            admin_review_svc.publish_assessment_completed_admin_advisory(
                entity_ulid=entity_ulid,
                history_ulid=dto.history_ulid,
                actor_ulid=actor,
                request_id=rid,
            )

        dash = svc.get_customer_dashboard(entity_ulid)
        if dash.watchlist:
            admin_review_svc.publish_watchlist_admin_advisory(
                entity_ulid=entity_ulid,
                actor_ulid=actor,
                request_id=rid,
                source_ref_ulid=entity_ulid,
            )

        db.session.commit()
        _wiz_consume_nonce(STEP_REVIEW, entity_ulid)
    except Exception as exc:
        print("INTAKE COMPLETE ERROR:", repr(exc))
        db.session.rollback()
        flash(str(exc), "error")
        return _goto_step(entity_ulid, STEP_REVIEW)

    return _goto_step(entity_ulid, STEP_DONE)


# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.get("/intake/<entity_ulid>/done")
@login_required
def intake_done_get(entity_ulid: str):
    _ctx_ro()
    dash = svc.get_customer_dashboard(entity_ulid)
    return render_template(
        "customers/intake_done.html",
        entity_ulid=entity_ulid,
        entity_card=_try_entity_card(entity_ulid),
        dash=dash,
    )


__all__ = ["bp"]
