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

from app.extensions import auth_ctx, db
from app.lib import request_ctx

from . import services as svc
from .models import Customer, CustomerEligibility


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
    request_ctx.ensure_request_id()

    # If authenticated, seed actor_ulid into request_ctx.
    actor = auth_ctx.current_actor_ulid()
    request_ctx.set_actor_ulid(actor)


def _ctx_ro() -> str:
    """Read-only routes: ensure request_id exists, return it."""
    return request_ctx.ensure_request_id()


def _ctx_mut() -> tuple[str, str]:
    """Mutating routes: require actor_ulid; return (request_id, actor_ulid)."""
    rid = request_ctx.ensure_request_id()
    actor = request_ctx.get_actor_ulid()
    if not actor:
        abort(403)
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

    For now, keep this simple and conservative:
    - If eligibility looks untouched -> eligibility
    - Else if needs_state is skipped/complete -> review
    - Else -> needs_tier1
    """
    c = db.session.get(Customer, entity_ulid)
    if c is None:
        return STEP_ELIGIBILITY

    e = db.session.get(CustomerEligibility, entity_ulid)
    if e is not None:
        untouched = (
            (e.veteran_status == "unknown")
            and (e.homeless_status == "unknown")
            and (e.veteran_method is None)
            and (e.branch is None)
            and (e.era is None)
        )
        if untouched:
            return STEP_ELIGIBILITY

    if c.needs_state in ("skipped", "complete"):
        return STEP_REVIEW

    return STEP_NEEDS_T1


def _goto_step(entity_ulid: str, step: str) -> Any:
    ep = _STEP_TO_ENDPOINT[step]
    return redirect(url_for(ep, entity_ulid=entity_ulid))


# -----------------
# Entry point
# -----------------


@bp.get("/intake/start/<entity_ulid>")
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


@bp.get("/")
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


@bp.get("/<entity_ulid>")
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


# -----------------
# Dataset #5/#6
# History Timeline
# + Details
# -----------------


@bp.get("/<entity_ulid>/history")
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


@bp.get("/<entity_ulid>/history/<history_ulid>")
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


# -----------------
# Dataset #7
# Admin Inbox
# -----------------


@bp.get("/admin/inbox")
def admin_inbox_get():
    _ctx_mut()  # require actor; add RBAC+domain guard later
    page = _arg_int("page", 1, lo=1, hi=10_000)
    per_page = _arg_int("per_page", 25, lo=5, hi=200)
    p = svc.list_admin_inbox_items(page=page, per_page=per_page)
    return render_template("customers/admin_inbox.html", page=p)


# -----------------
# Eligibility step
# -----------------


@bp.get("/intake/<entity_ulid>/eligibility")
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


@bp.post("/intake/<entity_ulid>/eligibility")
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
            homeless_status=request.form.get("homeless_status", ""),
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
        # Convenience: begin assessment on first needs POST if not started.
        with suppress(Exception):
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


@bp.get("/intake/<entity_ulid>/needs/tier1")
def intake_needs_tier1_get(entity_ulid: str):
    return _needs_get(
        entity_ulid,
        STEP_NEEDS_T1,
        "customers/intake_needs_tier1.html",
    )


@bp.post("/intake/<entity_ulid>/needs/tier1")
def intake_needs_tier1_post(entity_ulid: str):
    ratings = {
        "food": request.form.get("food", "na"),
        "hygiene": request.form.get("hygiene", "na"),
        "health": request.form.get("health", "na"),
        "housing": request.form.get("housing", "na"),
        "clothing": request.form.get("clothing", "na"),
    }
    return _needs_post(
        entity_ulid=entity_ulid,
        step=STEP_NEEDS_T1,
        ratings=ratings,
        next_step=STEP_NEEDS_T2,
    )


@bp.get("/intake/<entity_ulid>/needs/tier2")
def intake_needs_tier2_get(entity_ulid: str):
    return _needs_get(
        entity_ulid,
        STEP_NEEDS_T2,
        "customers/intake_needs_tier2.html",
    )


@bp.post("/intake/<entity_ulid>/needs/tier2")
def intake_needs_tier2_post(entity_ulid: str):
    ratings = {
        "income": request.form.get("income", "na"),
        "employment": request.form.get("employment", "na"),
        "transportation": request.form.get("transportation", "na"),
        "education": request.form.get("education", "na"),
    }
    return _needs_post(
        entity_ulid=entity_ulid,
        step=STEP_NEEDS_T2,
        ratings=ratings,
        next_step=STEP_NEEDS_T3,
    )


@bp.get("/intake/<entity_ulid>/needs/tier3")
def intake_needs_tier3_get(entity_ulid: str):
    return _needs_get(
        entity_ulid,
        STEP_NEEDS_T3,
        "customers/intake_needs_tier3.html",
    )


@bp.post("/intake/<entity_ulid>/needs/tier3")
def intake_needs_tier3_post(entity_ulid: str):
    ratings = {
        "family": request.form.get("family", "na"),
        "peergroup": request.form.get("peergroup", "na"),
        "tech": request.form.get("tech", "na"),
    }
    return _needs_post(
        entity_ulid=entity_ulid,
        step=STEP_NEEDS_T3,
        ratings=ratings,
        next_step=STEP_REVIEW,
    )


@bp.post("/intake/<entity_ulid>/needs/skip")
def intake_needs_skip(entity_ulid: str):
    rid, actor = _ctx_mut()
    dto = svc.needs_skip(
        entity_ulid=entity_ulid,
        request_id=rid,
        actor_ulid=actor,
    )
    db.session.commit()
    step = dto.next_step or STEP_REVIEW
    return _goto_step(entity_ulid, step)


# -----------------
# Review / Complete / Done
# -----------------


@bp.get("/intake/<entity_ulid>/review")
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


@bp.post("/intake/<entity_ulid>/complete")
def intake_complete_post(entity_ulid: str):
    if not _wiz_expect_nonce(
        STEP_REVIEW, entity_ulid, request.form.get("wiz_nonce")
    ):
        flash("Stale page. Resuming current step.", "warning")
        return _goto_step(entity_ulid, wizard_next_step(entity_ulid))

    rid, actor = _ctx_mut()
    try:
        svc.needs_complete(
            entity_ulid=entity_ulid,
            request_id=rid,
            actor_ulid=actor,
        )
        db.session.commit()
        _wiz_consume_nonce(STEP_REVIEW, entity_ulid)
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return _goto_step(entity_ulid, STEP_REVIEW)

    return _goto_step(entity_ulid, STEP_DONE)


@bp.get("/intake/<entity_ulid>/done")
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
