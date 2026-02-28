# app/slices/sponsors/onboard_routes.py

from __future__ import annotations

from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.extensions import db
from app.lib.ids import new_ulid
from app.lib.request_ctx import ensure_request_id, get_actor_ulid
from app.lib.security import require_permission  # noqa: F401

from . import onboard_services as wiz
from . import services as sp_svc
from . import taxonomy as tax
from .models import Sponsor
from .routes import bp

_ACTIVE_KEY = "wiz_active_sponsor_entity_ulid"


def _active_entity_ulid() -> str | None:
    return session.get(_ACTIVE_KEY)


def _set_active_entity_ulid(entity_ulid: str) -> None:
    session[_ACTIVE_KEY] = entity_ulid


def _clear_active_entity_ulid() -> None:
    session.pop(_ACTIVE_KEY, None)


def _nonce_key(step: str, entity_ulid: str) -> str:
    return f"sp_onboard:{step}:{entity_ulid}"


def _issue_nonce(step: str, entity_ulid: str) -> str:
    token = new_ulid()
    session[_nonce_key(step, entity_ulid)] = token
    return token


def _expect_nonce(step: str, entity_ulid: str) -> str | None:
    return session.get(_nonce_key(step, entity_ulid))


def _consume_nonce(step: str, entity_ulid: str) -> None:
    session.pop(_nonce_key(step, entity_ulid), None)


def _nav(entity_ulid: str, current_step: str) -> list[dict[str, object]]:
    s = db.session.get(Sponsor, entity_ulid)
    idx_done = wiz.step_index(s.onboard_step if s else None)
    out: list[dict[str, object]] = []
    for i, step in enumerate(wiz.STEPS):
        ep = wiz.STEP_ENDPOINTS[step]
        out.append(
            {
                "step": step,
                "label": wiz.STEP_LABELS.get(step, step),
                "url": url_for(ep, entity_ulid=entity_ulid),
                "done": i <= idx_done,
                "current": step == current_step,
            }
        )
    return out


@bp.route("/onboard/start", methods=["GET", "POST"], endpoint="onboard_start")
# @require_permission("sponsors:write")
def onboard_start():
    if request.method == "POST":
        entity_ulid = (request.form.get("entity_ulid") or "").strip()
        if not entity_ulid:
            flash("Enter an Org Entity ULID.", "error")
            return redirect(url_for("sponsors.onboard_start"))
        return redirect(
            url_for("sponsors.onboard_start", entity_ulid=entity_ulid)
        )

    if (request.args.get("reset") or "").strip() in ("1", "true", "yes"):
        _clear_active_entity_ulid()
        flash("Sponsor onboarding reset.", "warning")

    entity_ulid = (request.args.get("entity_ulid") or "").strip()
    if not entity_ulid:
        entity_ulid = _active_entity_ulid() or ""

    if not entity_ulid:
        return render_template(
            "sponsors/onboard/start.html",
            active_entity_ulid=_active_entity_ulid(),
            entity_ulid="",
            error=None,
        )

    req = ensure_request_id()
    actor = get_actor_ulid()
    try:
        wiz.ensure_sponsor_for_onboard(
            entity_ulid=entity_ulid,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        _set_active_entity_ulid(entity_ulid)
        nxt = wiz.wizard_next_step(entity_ulid=entity_ulid)
        return redirect(url_for(nxt, entity_ulid=entity_ulid))
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "sponsor onboard start failed",
            extra={"request_id": req, "entity_ulid": entity_ulid},
        )
        return render_template(
            "sponsors/onboard/start.html",
            active_entity_ulid=_active_entity_ulid(),
            entity_ulid=entity_ulid,
            error=str(exc),
        )


@bp.route(
    "/onboard/<entity_ulid>/profile",
    methods=["GET", "POST"],
    endpoint="onboard_profile",
)
# @require_permission("sponsors:write")
def onboard_profile(entity_ulid: str):
    step = "profile"
    _set_active_entity_ulid(entity_ulid)
    req = ensure_request_id()
    actor = get_actor_ulid()

    if request.method == "GET":
        hints = sp_svc.get_profile_hints(entity_ulid) or {}
        return render_template(
            "sponsors/onboard/profile.html",
            entity_ulid=entity_ulid,
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            hints=hints,
            error=None,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("sponsors.onboard_profile", entity_ulid=entity_ulid)
        )

    payload = {
        "relationship_note": (
            request.form.get("relationship_note") or ""
        ).strip(),
        "recognition_note": (
            request.form.get("recognition_note") or ""
        ).strip(),
    }

    try:
        sp_svc.set_profile_hints(
            sponsor_entity_ulid=entity_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        wiz.mark_step(entity_ulid=entity_ulid, step=step)
        db.session.commit()
        _consume_nonce(step, entity_ulid)
        return redirect(
            url_for("sponsors.onboard_pocs", entity_ulid=entity_ulid)
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc) or "Unable to save.", "error")
        return render_template(
            "sponsors/onboard/profile.html",
            entity_ulid=entity_ulid,
            nav=_nav(entity_ulid, step),
            wiz_nonce=expected,
            hints=payload,
            error=str(exc),
        )


@bp.route(
    "/onboard/<entity_ulid>/pocs",
    methods=["GET", "POST"],
    endpoint="onboard_pocs",
)
# @require_permission("sponsors:write")
def onboard_pocs(entity_ulid: str):
    step = "pocs"
    _set_active_entity_ulid(entity_ulid)
    req = ensure_request_id()
    actor = get_actor_ulid()

    if request.method == "GET":
        pocs = sp_svc.sponsor_list_pocs(sponsor_entity_ulid=entity_ulid)
        return render_template(
            "sponsors/onboard/pocs.html",
            entity_ulid=entity_ulid,
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            pocs=pocs,
            scopes=list(tax.POC_SCOPES),
            default_scope=str(tax.DEFAULT_POC_SCOPE),
            error=None,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("sponsors.onboard_pocs", entity_ulid=entity_ulid)
        )

    action = (request.form.get("action") or "").strip().lower() or "add"
    person_ulid = (request.form.get("person_entity_ulid") or "").strip()
    scope = (request.form.get("scope") or "").strip() or None
    org_role = (request.form.get("org_role") or "").strip() or None
    is_primary = (request.form.get("is_primary") or "").strip() in (
        "1",
        "true",
        "yes",
        "on",
    )

    raw_rank = (request.form.get("rank") or "0").strip()
    try:
        rank = int(raw_rank or 0)
    except Exception:
        rank = 0

    try:
        if action == "add":
            if not person_ulid:
                raise ValueError("person_entity_ulid is required")
            sp_svc.sponsor_link_poc(
                sponsor_entity_ulid=entity_ulid,
                person_entity_ulid=person_ulid,
                scope=scope,
                rank=rank,
                is_primary=is_primary,
                org_role=org_role,
                actor_ulid=actor,
                request_id=req,
            )

        wiz.mark_step(entity_ulid=entity_ulid, step=step)
        db.session.commit()
        _consume_nonce(step, entity_ulid)

        if action == "continue":
            return redirect(
                url_for(
                    "sponsors.onboard_funding_rules", entity_ulid=entity_ulid
                )
            )
        return redirect(
            url_for("sponsors.onboard_pocs", entity_ulid=entity_ulid)
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc) or "Unable to save POC.", "error")
        return redirect(
            url_for("sponsors.onboard_pocs", entity_ulid=entity_ulid)
        )


@bp.route(
    "/onboard/<entity_ulid>/funding_rules",
    methods=["GET", "POST"],
    endpoint="onboard_funding_rules",
)
# @require_permission("sponsors:write")
def onboard_funding_rules(entity_ulid: str):
    step = "funding_rules"
    _set_active_entity_ulid(entity_ulid)
    req = ensure_request_id()
    actor = get_actor_ulid()

    if request.method == "GET":
        selected_caps: set[str] = set()
        v = sp_svc.sponsor_view(entity_ulid)
        if v:
            selected_caps = {
                f"{c.domain}.{c.key}" for c in (v.active_capabilities or [])
            }
        restr = sp_svc.get_donation_restrictions(entity_ulid) or {}
        selected_restr = {
            k for k, vv in restr.items() if (vv or {}).get("has")
        }

        return render_template(
            "sponsors/onboard/funding_rules.html",
            entity_ulid=entity_ulid,
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            cap_tree=getattr(tax, "SPONSOR_CAPABILITY_DOMAINS", ()),
            restr_tree=getattr(tax, "SPONSOR_DONATION_RESTRICTIONS", ()),
            selected_caps=selected_caps,
            selected_restr=selected_restr,
            error=None,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("sponsors.onboard_funding_rules", entity_ulid=entity_ulid)
        )

    caps = {
        str(s).strip() for s in request.form.getlist("caps") if str(s).strip()
    }
    restr = {
        str(s).strip()
        for s in request.form.getlist("restr")
        if str(s).strip()
    }

    caps_payload = {k: True for k in sorted(caps)}
    restr_payload = {k: True for k in sorted(restr)}

    try:
        sp_svc.upsert_capabilities(
            sponsor_entity_ulid=entity_ulid,
            payload=caps_payload,
            request_id=req,
            actor_ulid=actor,
        )
        sp_svc.upsert_donation_restrictions(
            sponsor_entity_ulid=entity_ulid,
            payload=restr_payload,
            request_id=req,
            actor_ulid=actor,
        )

        wiz.mark_step(entity_ulid=entity_ulid, step=step)
        db.session.commit()
        _consume_nonce(step, entity_ulid)
        return redirect(
            url_for("sponsors.onboard_mou", entity_ulid=entity_ulid)
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc) or "Unable to save funding rules.", "error")
        return redirect(
            url_for("sponsors.onboard_funding_rules", entity_ulid=entity_ulid)
        )


@bp.route(
    "/onboard/<entity_ulid>/mou",
    methods=["GET", "POST"],
    endpoint="onboard_mou",
)
# @require_permission("sponsors:write")
def onboard_mou(entity_ulid: str):
    step = "mou"
    _set_active_entity_ulid(entity_ulid)
    req = ensure_request_id()
    actor = get_actor_ulid()

    if request.method == "GET":
        v = sp_svc.sponsor_view(entity_ulid)
        cur = v.mou_status if v else ""
        return render_template(
            "sponsors/onboard/mou.html",
            entity_ulid=entity_ulid,
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            mou_statuses=list(tax.SPONSOR_MOU_STATUSES),
            current_status=cur,
            error=None,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("sponsors.onboard_mou", entity_ulid=entity_ulid)
        )

    status = (request.form.get("mou_status") or "").strip().lower()
    try:
        if status:
            sp_svc.set_mou_status(
                sponsor_entity_ulid=entity_ulid,
                status=status,
                request_id=req,
                actor_ulid=actor,
            )
        wiz.mark_step(entity_ulid=entity_ulid, step=step)
        db.session.commit()
        _consume_nonce(step, entity_ulid)
        return redirect(
            url_for("sponsors.onboard_review", entity_ulid=entity_ulid)
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc) or "Unable to save MOU.", "error")
        return redirect(
            url_for("sponsors.onboard_mou", entity_ulid=entity_ulid)
        )


@bp.route(
    "/onboard/<entity_ulid>/review",
    methods=["GET", "POST"],
    endpoint="onboard_review",
)
# @require_permission("sponsors:read")
def onboard_review(entity_ulid: str):
    step = "review"
    _set_active_entity_ulid(entity_ulid)

    snap = wiz.review_snapshot(entity_ulid=entity_ulid)
    if request.method == "GET":
        return render_template(
            "sponsors/onboard/review.html",
            entity_ulid=entity_ulid,
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            snap=snap,
            error=None,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("sponsors.onboard_review", entity_ulid=entity_ulid)
        )

    try:
        wiz.mark_step(entity_ulid=entity_ulid, step=step)
        db.session.commit()
        _consume_nonce(step, entity_ulid)
        return redirect(
            url_for("sponsors.onboard_complete", entity_ulid=entity_ulid)
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc) or "Unable to continue.", "error")
        return redirect(
            url_for("sponsors.onboard_review", entity_ulid=entity_ulid)
        )


@bp.route(
    "/onboard/<entity_ulid>/complete",
    methods=["GET", "POST"],
    endpoint="onboard_complete",
)
# @require_permission("sponsors:write")
def onboard_complete(entity_ulid: str):
    step = "complete"
    _set_active_entity_ulid(entity_ulid)

    if request.method == "GET":
        return render_template(
            "sponsors/onboard/complete.html",
            entity_ulid=entity_ulid,
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            error=None,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("sponsors.onboard_complete", entity_ulid=entity_ulid)
        )

    try:
        wiz.mark_step(entity_ulid=entity_ulid, step=step)
        db.session.commit()
        _consume_nonce(step, entity_ulid)
        flash("Submitted for Admin review.", "success")
        return redirect(
            url_for(
                "sponsors.search_sponsors_html",
                readiness="draft",
                onboard_step="complete",
            )
        )
    except Exception as exc:
        db.session.rollback()
        flash(str(exc) or "Unable to complete onboarding.", "error")
        return redirect(
            url_for("sponsors.onboard_complete", entity_ulid=entity_ulid)
        )


@bp.get("/search", endpoint="search_sponsors_html")
# @require_permission("sponsors:read")
def search_sponsors_html():
    any_param = (request.args.get("any") or "").strip()
    readiness = [
        p.strip()
        for p in (request.args.get("readiness") or "").split(",")
        if p.strip()
    ] or None
    onboard_step = (
        request.args.get("onboard_step") or ""
    ).strip().lower() or None
    review = request.args.get("review")

    def _pairs(s: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for t in (s or "").split(","):
            t = t.strip()
            if "." in t:
                d, k = t.split(".", 1)
                out.append((d.strip(), k.strip()))
        return out

    any_of = _pairs(any_param)
    rows, total = sp_svc.find_sponsors(
        any_of=any_of or None,
        readiness_in=readiness,
        admin_review_required=(
            None
            if review is None
            else (review.lower() in ("1", "true", "yes"))
        ),
        onboard_step=onboard_step,
        page=request.args.get("page", type=int, default=1),
        per=request.args.get("per", type=int, default=50),
    )

    return render_template(
        "sponsors/search.html",
        rows=rows,
        total=total,
        form={
            "any": any_param,
            "readiness": ",".join(readiness or []),
            "onboard_step": onboard_step or "",
            "review": (review or ""),
        },
    )
