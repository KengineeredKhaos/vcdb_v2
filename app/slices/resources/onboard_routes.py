# app/slices/resources/onboard_routes.py

"""
Resources onboarding wizard HTTP routes.

Naming convention (intentional):
- resources.onboard_routes / resources.onboard_services
  (clear: org onboarding vs customer/person creation flows)

Rules:
- Validate nonce before consuming it.
- Services flush + emit; routes commit.
- Wizard creates draft data only; Admin activates later.
"""

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
from flask_login import login_required

from app.extensions import db, event_bus
from app.extensions.auth_ctx import current_actor_ulid
from app.extensions.contracts import entity_v2
from app.extensions.errors import ContractError
from app.lib.ids import new_ulid
from app.lib.request_ctx import ensure_request_id

from . import onboard_services as wiz
from . import services as res_svc
from . import taxonomy as tax
from .models import Resource
from .routes import bp

_ACTIVE_KEY = "wiz_active_resource_entity_ulid"


def _try_entity_name_card(entity_ulid: str | None):
    if not entity_ulid:
        return None
    try:
        return entity_v2.get_entity_name_card(entity_ulid)
    except ContractError as exc:
        current_app.logger.warning(
            "entity name card lookup failed: code=%s ulid=%s",
            exc.code,
            entity_ulid,
        )
        return None


def _active_entity_ulid() -> str | None:
    return session.get(_ACTIVE_KEY)


def _set_active_entity_ulid(entity_ulid: str) -> None:
    session[_ACTIVE_KEY] = entity_ulid


def _clear_active_entity_ulid() -> None:
    session.pop(_ACTIVE_KEY, None)


def _nonce_key(step: str, entity_ulid: str) -> str:
    return f"res_onboard:{step}:{entity_ulid}"


def _issue_nonce(step: str, entity_ulid: str) -> str:
    token = new_ulid()
    session[_nonce_key(step, entity_ulid)] = token
    return token


def _expect_nonce(step: str, entity_ulid: str) -> str | None:
    return session.get(_nonce_key(step, entity_ulid))


def _consume_nonce(step: str, entity_ulid: str) -> None:
    session.pop(_nonce_key(step, entity_ulid), None)


def _nav(entity_ulid: str, current_step: str) -> list[dict[str, object]]:
    r = db.session.get(Resource, entity_ulid)
    idx_done = wiz.step_index(r.onboard_step if r else None)

    out: list[dict[str, object]] = []
    for i, step in enumerate(wiz.STEPS):
        ep = wiz.STEP_ENDPOINTS[step]
        out.append(
            {
                "step": step,
                "label": wiz.step_label(step),
                "url": url_for(ep, entity_ulid=entity_ulid),
                "done": i <= idx_done,
                "current": step == current_step,
            }
        )
    return out

# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/poc/attach/<person_ulid>",
    methods=["GET", "POST"],
    endpoint="poc_attach",
)
@login_required
def poc_attach(person_ulid: str):
    req = ensure_request_id()

    from app.extensions.contracts import entity_v2
    from app.extensions.errors import ContractError

    def _card(u: str):
        try:
            return entity_v2.get_entity_name_card(u)
        except ContractError:
            return None

    person_card = _card(person_ulid)

    if request.method == "GET":
        return render_template(
            "resources/onboard/poc_attach.html",
            person_ulid=person_ulid,
            person_card=person_card,
            scopes=list(tax.POC_SCOPES),
            default_scope=str(tax.DEFAULT_POC_SCOPE),
        )

    org_ulid = (request.form.get("org_entity_ulid") or "").strip()
    scope = (request.form.get("scope") or "").strip() or None
    org_role = (request.form.get("org_role") or "").strip() or None
    is_primary = (request.form.get("is_primary") or "") in ("1", "true", "on")

    org_card = _card(org_ulid)
    if not org_card:
        flash("Org ULID not found.", "error")
        return redirect(
            url_for("resources.poc_attach", person_ulid=person_ulid)
        )
    if org_card.kind != "org":
        flash("That ULID is not an organization.", "error")
        return redirect(
            url_for("resources.poc_attach", person_ulid=person_ulid)
        )

    return render_template(
        "resources/onboard/poc_attach_confirm.html",
        person_ulid=person_ulid,
        person_card=person_card,
        org_ulid=org_ulid,
        org_card=org_card,
        scope=scope,
        org_role=org_role,
        is_primary=is_primary,
        request_id=req,
    )

# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.post("/poc/attach/confirm", endpoint="poc_attach_confirm")
@login_required
def poc_attach_confirm():
    req = ensure_request_id()
    actor = current_actor_ulid()

    person_ulid = (request.form.get("person_ulid") or "").strip()
    org_ulid = (request.form.get("org_ulid") or "").strip()
    scope = (request.form.get("scope") or "").strip() or None
    org_role = (request.form.get("org_role") or "").strip() or None
    is_primary = (request.form.get("is_primary") or "") in ("1", "true", "on")

    try:
        # Ensure resource facet exists (if that’s your desired behavior)
        res_svc.ensure_resource(
            resource_entity_ulid=org_ulid,
            actor_ulid=actor,
            request_id=req,
        )

        res_svc.resource_link_poc(
            resource_entity_ulid=org_ulid,
            person_entity_ulid=person_ulid,
            scope=scope,
            is_primary=is_primary,
            org_role=org_role,
            actor_ulid=actor,
            request_id=req,
        )
        # service flushes; route emits + commits
        event_bus.emit(
            domain="resources",
            operation="contact_upserted",
            request_id=req,
            actor_ulid=actor,
            target_ulid=org_ulid,
            ref=person_ulid,
            changed={"fields": [person_ulid, org_ulid]},
        )
        db.session.commit()
        flash("POC linked to Resource.", "success")
        return redirect(
            url_for("resources.onboard_pocs", entity_ulid=org_ulid)
        )

    except Exception as exc:
        db.session.rollback()
        flash(str(exc) or "Unable to link POC.", "error")
        return redirect(
            url_for("resources.poc_attach", person_ulid=person_ulid)
        )

# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/onboard/start",
    methods=["GET", "POST"],
    endpoint="onboard_start",
)
@login_required
def onboard_start():
    """
    Entry point.

    - If entity_ulid is provided, ensure facet exists and redirect to next step.
    - Otherwise show a small start/resume form.
    """

    if request.method == "POST":
        entity_ulid = (request.form.get("entity_ulid") or "").strip()
        if not entity_ulid:
            flash("Enter an Org Entity ULID.", "error")
            return redirect(url_for("resources.onboard_start"))
        return redirect(
            url_for("resources.onboard_start", entity_ulid=entity_ulid)
        )

    if (request.args.get("reset") or "").strip() in ("1", "true", "yes"):
        _clear_active_entity_ulid()
        flash("Resource onboarding reset.", "warning")

    entity_ulid = (request.args.get("entity_ulid") or "").strip()
    if not entity_ulid:
        entity_ulid = _active_entity_ulid() or ""

    if not entity_ulid:
        active_ulid = _active_entity_ulid()
        return render_template(
            "resources/onboard/start.html",
            active_entity_ulid=active_ulid,
            active_entity_card=_try_entity_name_card(active_ulid),
            entity_ulid="",
            error=None,
        )

    req = ensure_request_id()
    actor = current_actor_ulid()

    try:
        wiz.ensure_resource_for_onboard(
            entity_ulid=entity_ulid,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        _set_active_entity_ulid(entity_ulid)

        next_ep = wiz.wizard_next_step(entity_ulid=entity_ulid)
        return redirect(url_for(next_ep, entity_ulid=entity_ulid))

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "resources onboarding start failed",
            extra={"request_id": req, "entity_ulid": entity_ulid},
        )
        flash(str(exc) or "Unable to start onboarding.", "error")
        active_ulid = _active_entity_ulid()
        return render_template(
            "resources/onboard/start.html",
            active_entity_ulid=active_ulid,
            active_entity_card=_try_entity_name_card(active_ulid),
            entity_ulid=entity_ulid,
            error=str(exc),
        )

# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/onboard/<entity_ulid>/profile",
    methods=["GET", "POST"],
    endpoint="onboard_profile",
)
@login_required
def onboard_profile(entity_ulid: str):
    step = "profile"
    _set_active_entity_ulid(entity_ulid)

    req = ensure_request_id()
    actor = current_actor_ulid()

    if request.method == "GET":
        hints = {}
        error = None
        try:
            hints = res_svc.get_profile_hints(entity_ulid) or {}
        except Exception as exc:
            error = str(exc)

        return render_template(
            "resources/onboard/profile.html",
            entity_ulid=entity_ulid,
            entity_card=_try_entity_name_card(entity_ulid),
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            hints=hints,
            error=error,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("resources.onboard_profile", entity_ulid=entity_ulid)
        )

    payload = {
        "service_area_note": (
            request.form.get("service_area_note") or ""
        ).strip(),
        "sla_note": (request.form.get("sla_note") or "").strip(),
    }

    try:
        res_svc.set_profile_hints(
            resource_entity_ulid=entity_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        wiz.mark_step(
            entity_ulid=entity_ulid,
            step=step,
            request_id=req,
            actor_ulid=actor,
        )

        db.session.commit()
        _consume_nonce(step, entity_ulid)
        flash("Saved profile hints.", "success")
        return redirect(
            url_for("resources.onboard_capabilities", entity_ulid=entity_ulid)
        )

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "onboard_profile failed",
            extra={"request_id": req, "entity_ulid": entity_ulid},
        )
        flash(str(exc) or "Unable to save profile hints.", "error")
        return render_template(
            "resources/onboard/profile.html",
            entity_ulid=entity_ulid,
            entity_card=_try_entity_name_card(entity_ulid),
            nav=_nav(entity_ulid, step),
            wiz_nonce=expected,
            hints=payload,
            error=str(exc),
        )

# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/onboard/<entity_ulid>/capabilities",
    methods=["GET", "POST"],
    endpoint="onboard_capabilities",
)
@login_required
def onboard_capabilities(entity_ulid: str):
    step = "capabilities"
    _set_active_entity_ulid(entity_ulid)

    req = ensure_request_id()
    actor = current_actor_ulid()

    if request.method == "GET":
        selected: set[str] = set()
        error = None
        try:
            v = res_svc.resource_view(entity_ulid)
            if v:
                selected = {
                    f"{c.domain}.{c.key}"
                    for c in (v.active_capabilities or [])
                }
        except Exception as exc:
            error = str(exc)

        return render_template(
            "resources/onboard/capabilities.html",
            entity_ulid=entity_ulid,
            entity_card=_try_entity_name_card(entity_ulid),
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            cap_tree=getattr(tax, "RESOURCE_CAPABILITY_KEYS_BY_DOMAIN", {}),
            selected=selected,
            error=error,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("resources.onboard_capabilities", entity_ulid=entity_ulid)
        )

    raw = request.form.getlist("caps")
    selected = {str(s).strip() for s in raw if str(s).strip()}
    payload = dict.fromkeys(sorted(selected), True)

    try:
        res_svc.upsert_capabilities(
            resource_entity_ulid=entity_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        wiz.mark_step(
            entity_ulid=entity_ulid,
            step=step,
            request_id=req,
            actor_ulid=actor,
        )

        db.session.commit()
        _consume_nonce(step, entity_ulid)
        flash("Saved capabilities.", "success")
        return redirect(
            url_for("resources.onboard_capacity", entity_ulid=entity_ulid)
        )

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "onboard_capabilities failed",
            extra={"request_id": req, "entity_ulid": entity_ulid},
        )
        flash(str(exc) or "Unable to save capabilities.", "error")
        return render_template(
            "resources/onboard/capabilities.html",
            entity_ulid=entity_ulid,
            entity_card=_try_entity_name_card(entity_ulid),
            nav=_nav(entity_ulid, step),
            wiz_nonce=expected,
            cap_tree=getattr(tax, "RESOURCE_CAPABILITY_KEYS_BY_DOMAIN", {}),
            selected=selected,
            error=str(exc),
        )

# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/onboard/<entity_ulid>/capacity",
    methods=["GET", "POST"],
    endpoint="onboard_capacity",
)
@login_required
def onboard_capacity(entity_ulid: str):
    step = "capacity"
    _set_active_entity_ulid(entity_ulid)

    req = ensure_request_id()
    actor = current_actor_ulid()

    if request.method == "GET":
        return render_template(
            "resources/onboard/capacity.html",
            entity_ulid=entity_ulid,
            entity_card=_try_entity_name_card(entity_ulid),
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            error=None,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("resources.onboard_capacity", entity_ulid=entity_ulid)
        )

    try:
        wiz.mark_step(
            entity_ulid=entity_ulid,
            step=step,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        _consume_nonce(step, entity_ulid)
        return redirect(
            url_for("resources.onboard_pocs", entity_ulid=entity_ulid)
        )

    except Exception as exc:
        db.session.rollback()
        flash(str(exc) or "Unable to continue.", "error")
        return redirect(
            url_for("resources.onboard_capacity", entity_ulid=entity_ulid)
        )

# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/onboard/<entity_ulid>/pocs",
    methods=["GET", "POST"],
    endpoint="onboard_pocs",
)
@login_required
def onboard_pocs(entity_ulid: str):
    step = "pocs"
    _set_active_entity_ulid(entity_ulid)

    req = ensure_request_id()
    actor = current_actor_ulid()

    if request.method == "GET":
        pocs = []
        error = None
        try:
            pocs = res_svc.resource_list_pocs(
                resource_entity_ulid=entity_ulid
            )
        except Exception as exc:
            error = str(exc)

        poc_cards = {}
        try:
            person_ulids = []
            seen = set()
            for p in pocs or []:
                u = str(p.link.person_entity_ulid).strip()
                if u and u not in seen:
                    seen.add(u)
                    person_ulids.append(u)
            if person_ulids:
                cards = entity_v2.get_entity_name_cards(person_ulids)
                poc_cards = {c.entity_ulid: c for c in cards}
        except ContractError:
            poc_cards = {}

        return render_template(
            "resources/onboard/pocs.html",
            entity_ulid=entity_ulid,
            entity_card=_try_entity_name_card(entity_ulid),
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            pocs=pocs,
            poc_cards=poc_cards,
            scopes=list(tax.POC_SCOPES),
            default_scope=str(tax.DEFAULT_POC_SCOPE),
            error=error,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("resources.onboard_pocs", entity_ulid=entity_ulid)
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
            res_svc.resource_link_poc(
                resource_entity_ulid=entity_ulid,
                person_entity_ulid=person_ulid,
                scope=scope,
                rank=rank,
                is_primary=is_primary,
                org_role=org_role,
                actor_ulid=actor,
                request_id=req,
            )

        wiz.mark_step(
            entity_ulid=entity_ulid,
            step=step,
            request_id=req,
            actor_ulid=actor,
        )

        db.session.commit()
        _consume_nonce(step, entity_ulid)

        if action == "continue":
            return redirect(
                url_for("resources.onboard_mou", entity_ulid=entity_ulid)
            )

        flash("POC saved.", "success")
        return redirect(
            url_for("resources.onboard_pocs", entity_ulid=entity_ulid)
        )

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "onboard_pocs failed",
            extra={"request_id": req, "entity_ulid": entity_ulid},
        )
        flash(str(exc) or "Unable to save POC.", "error")
        return redirect(
            url_for("resources.onboard_pocs", entity_ulid=entity_ulid)
        )

# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/onboard/<entity_ulid>/mou",
    methods=["GET", "POST"],
    endpoint="onboard_mou",
)
@login_required
def onboard_mou(entity_ulid: str):
    step = "mou"
    _set_active_entity_ulid(entity_ulid)

    req = ensure_request_id()
    actor = current_actor_ulid()

    if request.method == "GET":
        v = res_svc.resource_view(entity_ulid)
        cur = v.mou_status if v else ""

        return render_template(
            "resources/onboard/mou.html",
            entity_ulid=entity_ulid,
            entity_card=_try_entity_name_card(entity_ulid),
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            mou_statuses=list(tax.RESOURCE_MOU_STATUSES),
            current_status=cur,
            error=None,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("resources.onboard_mou", entity_ulid=entity_ulid)
        )

    status = (request.form.get("mou_status") or "").strip().lower()

    try:
        if status:
            res_svc.set_mou_status(
                resource_entity_ulid=entity_ulid,
                to_status=status,
                request_id=req,
                actor_ulid=actor,
            )

        wiz.mark_step(
            entity_ulid=entity_ulid,
            step=step,
            request_id=req,
            actor_ulid=actor,
        )

        db.session.commit()
        _consume_nonce(step, entity_ulid)
        return redirect(
            url_for("resources.onboard_review", entity_ulid=entity_ulid)
        )

    except Exception as exc:
        db.session.rollback()
        flash(str(exc) or "Unable to save MOU status.", "error")
        return redirect(
            url_for("resources.onboard_mou", entity_ulid=entity_ulid)
        )

# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/onboard/<entity_ulid>/review",
    methods=["GET", "POST"],
    endpoint="onboard_review",
)
@login_required
def onboard_review(entity_ulid: str):
    step = "review"
    _set_active_entity_ulid(entity_ulid)

    req = ensure_request_id()
    actor = current_actor_ulid()

    snap = {}
    error = None
    try:
        snap = wiz.review_snapshot(entity_ulid=entity_ulid)
    except Exception as exc:
        error = str(exc)

    if request.method == "GET":
        return render_template(
            "resources/onboard/review.html",
            entity_ulid=entity_ulid,
            entity_card=_try_entity_name_card(entity_ulid),
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            snap=snap,
            error=error,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("resources.onboard_review", entity_ulid=entity_ulid)
        )

    try:
        wiz.mark_step(
            entity_ulid=entity_ulid,
            step=step,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        _consume_nonce(step, entity_ulid)
        return redirect(
            url_for("resources.onboard_complete", entity_ulid=entity_ulid)
        )

    except Exception as exc:
        db.session.rollback()
        flash(str(exc) or "Unable to continue.", "error")
        return redirect(
            url_for("resources.onboard_review", entity_ulid=entity_ulid)
        )

# VCDB-SEC: ACTIVE entry=authenticated_user authority=login_required reason=operator_surface
@bp.route(
    "/onboard/<entity_ulid>/complete",
    methods=["GET", "POST"],
    endpoint="onboard_complete",
)
@login_required
def onboard_complete(entity_ulid: str):
    step = "complete"
    _set_active_entity_ulid(entity_ulid)

    req = ensure_request_id()
    actor = current_actor_ulid()

    if request.method == "GET":
        return render_template(
            "resources/onboard/complete.html",
            entity_ulid=entity_ulid,
            entity_card=_try_entity_name_card(entity_ulid),
            nav=_nav(entity_ulid, step),
            wiz_nonce=_issue_nonce(step, entity_ulid),
            error=None,
        )

    expected = _expect_nonce(step, entity_ulid)
    submitted = (request.form.get("wiz_nonce") or "").strip()
    if (not expected) or (submitted != expected):
        flash("That page is stale. Reload and try again.", "warning")
        return redirect(
            url_for("resources.onboard_complete", entity_ulid=entity_ulid)
        )

    try:
        wiz.submit_onboard_for_admin_review(
            entity_ulid=entity_ulid,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        _consume_nonce(step, entity_ulid)

        flash("Submitted for Admin review.", "success")
        return redirect(
            url_for(
                "resources.search_resources",
                readiness="draft",
                onboard_step="complete",
            )
        )

    except Exception as exc:
        db.session.rollback()
        flash(str(exc) or "Unable to complete onboarding.", "error")
        return redirect(
            url_for("resources.onboard_complete", entity_ulid=entity_ulid)
        )
