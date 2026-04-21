# app/slices/sponsors/routes.py
from __future__ import annotations

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.extensions.contracts import entity_v2
from app.extensions.errors import ContractError
from app.lib.request_ctx import ensure_request_id, get_actor_ulid
from app.lib.security import rbac

from . import services as sp_svc
from . import services_calendar as cal_handoff_svc
from . import services_crm as crm_svc

bp = Blueprint(
    "sponsors",
    __name__,
    template_folder="templates",
    static_folder=None,
    url_prefix="/sponsors",
)


# -----------------
# internal helpers
# -----------------


def _ok(data: dict, request_id: str):
    return jsonify({"ok": True, "request_id": request_id, "data": data}), 200


def _err(exc: Exception, code: int = 400):
    # Prefer ContractError shaping
    if isinstance(exc, ContractError):
        payload = {
            "ok": False,
            "error": exc.message,
            "code": exc.code,
            "where": exc.where,
        }
        if getattr(exc, "data", None):
            payload["data"] = exc.data
        return jsonify(payload), exc.http_status

    if isinstance(exc, LookupError):
        return jsonify({"ok": False, "error": str(exc)}), 404
    if isinstance(exc, PermissionError):
        return jsonify({"ok": False, "error": str(exc)}), 403
    if isinstance(exc, ValueError):
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": False, "error": str(exc)}), code


def _try_entity_name_card(entity_ulid: str | None):
    if not entity_ulid:
        return None
    try:
        return entity_v2.get_entity_name_card(entity_ulid)
    except Exception:
        return None


def _actor_ulid() -> str | None:
    return (
        get_actor_ulid()
        or getattr(current_user, "entity_ulid", None)
        or getattr(current_user, "ulid", None)
    )


# -----------------
# Wizard Routes
# -----------------


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.get("/onboard/start/<entity_ulid>", endpoint="onboard_start_legacy")
@login_required
@rbac("staff", "admin")
def onboard_start_legacy(entity_ulid: str):
    # Legacy helper: bounce to the new onboarding entrypoint.
    return redirect(
        url_for("sponsors.onboard_start", entity_ulid=entity_ulid)
    )


# -----------------
# Other Stuff
# -----------------


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.post("")
@login_required
@rbac("staff", "admin")
def ensure_sponsor():
    try:
        payload = request.get_json(force=True, silent=False) or {}
        entity_ulid = (payload.get("entity_ulid") or "").strip()
        if not entity_ulid:
            return _err(ValueError("entity_ulid is required"), 400)
        req, actor = ensure_request_id(), get_actor_ulid()
        sponsor_entity_ulid = sp_svc.ensure_sponsor(
            sponsor_entity_ulid=entity_ulid,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(
            {"sponsor_entity_ulid": sponsor_entity_ulid}, request_id=req
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.get("/<sponsor_entity_ulid>")
@login_required
@rbac("staff", "admin")
def get_sponsor(sponsor_entity_ulid: str):
    dto = sp_svc.sponsor_view(sponsor_entity_ulid)
    return (
        _ok(dto, request_id=ensure_request_id())
        if dto
        else _err(LookupError("not found"), 404)
    )


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.get("/<sponsor_entity_ulid>/detail", endpoint="sponsor_detail_html")
@login_required
@rbac("staff", "admin")
def sponsor_detail_html(sponsor_entity_ulid: str):
    sponsor = sp_svc.sponsor_view(sponsor_entity_ulid)
    if not sponsor:
        return _err(LookupError("not found"), 404)

    posture = crm_svc.get_sponsor_posture(sponsor_entity_ulid)
    note_hints = crm_svc.get_sponsor_profile_note_hints(sponsor_entity_ulid)
    cultivation_outcomes = cal_handoff_svc.list_recent_cultivation_outcomes(
        sponsor_entity_ulid,
        limit=10,
    )

    return render_template(
        "sponsors/detail.html",
        title=f"Sponsor · {sponsor_entity_ulid}",
        sponsor=sponsor,
        posture=posture,
        note_hints=note_hints,
        cultivation_outcomes=cultivation_outcomes,
        entity_ulid=sponsor_entity_ulid,
        entity_card=_try_entity_name_card(sponsor_entity_ulid),
    )


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.post("/<sponsor_entity_ulid>/capabilities")
@login_required
@rbac("staff", "admin")
def upsert_caps(sponsor_entity_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req, actor = ensure_request_id(), get_actor_ulid()
        hist = sp_svc.upsert_capabilities(
            sponsor_entity_ulid=sponsor_entity_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(
            {
                "history_ulid": hist,
                "sponsor": sp_svc.sponsor_view(sponsor_entity_ulid),
            },
            request_id=req,
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.patch("/<sponsor_entity_ulid>/capabilities")
@login_required
@rbac("staff", "admin")
def patch_caps(sponsor_entity_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        req, actor = ensure_request_id(), get_actor_ulid()
        hist = sp_svc.patch_capabilities(
            sponsor_entity_ulid=sponsor_entity_ulid,
            payload=payload,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(
            {
                "history_ulid": hist,
                "sponsor": sp_svc.sponsor_view(sponsor_entity_ulid),
            },
            request_id=req,
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.post("/<sponsor_entity_ulid>/readiness")
@login_required
@rbac("staff", "admin")
def set_readiness(sponsor_entity_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        status = (payload.get("status") or "").strip().lower()
        req, actor = ensure_request_id(), get_actor_ulid()
        sp_svc.set_readiness_status(
            sponsor_entity_ulid=sponsor_entity_ulid,
            status=status,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok({"readiness_status": status}, request_id=req)
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.post("/<sponsor_entity_ulid>/mou")
@login_required
@rbac("staff", "admin")
def set_mou(sponsor_entity_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        status = (payload.get("status") or "").strip().lower()
        req, actor = ensure_request_id(), get_actor_ulid()
        sp_svc.set_mou_status(
            sponsor_entity_ulid=sponsor_entity_ulid,
            status=status,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok({"mou_status": status}, request_id=req)
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.post("/<sponsor_entity_ulid>/pledges")
@login_required
@rbac("staff", "admin")
def upsert_pledge(sponsor_entity_ulid: str):
    try:
        pledge = request.get_json(force=True, silent=False) or {}
        req, actor = ensure_request_id(), get_actor_ulid()
        pid = sp_svc.upsert_pledge(
            sponsor_entity_ulid=sponsor_entity_ulid,
            pledge=pledge,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(
            {
                "pledge_ulid": pid,
                "sponsor": sp_svc.sponsor_view(sponsor_entity_ulid),
            },
            request_id=req,
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.post("/pledges/<pledge_ulid>/status")
@login_required
@rbac("staff", "admin")
def set_pledge_status(pledge_ulid: str):
    try:
        payload = request.get_json(force=True, silent=False) or {}
        status = (payload.get("status") or "").strip().lower()

        req, actor = ensure_request_id(), get_actor_ulid()
        sp_svc.set_pledge_status(
            pledge_ulid=pledge_ulid,
            status=status,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        return _ok(
            {"pledge_ulid": pledge_ulid, "status": status}, request_id=req
        )
    except Exception as e:
        db.session.rollback()
        return _err(e, 400)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.get("")
@login_required
@rbac("staff", "admin")
def search_sponsors():
    req = ensure_request_id()
    try:
        any_param = request.args.get("any", "")
        readiness = [
            p.strip()
            for p in request.args.get("readiness", "").split(",")
            if p.strip()
        ] or None
        has_act = request.args.get("has_active_pledges")
        review = request.args.get("review")

        def _pairs(s):
            out = []
            for t in (s or "").split(","):
                t = t.strip()
                if "." in t:
                    d, k = t.split(".", 1)
                    out.append((d.strip(), k.strip()))
            return out

        any_of = _pairs(any_param)
        page = request.args.get("page", type=int, default=1)
        per = request.args.get("per", type=int, default=50)
        rows, total = sp_svc.find_sponsors(
            any_of=any_of or None,
            readiness_in=readiness,
            has_active_pledges=(
                None
                if has_act is None
                else (has_act.lower() in ("1", "true", "yes"))
            ),
            admin_review_required=(
                None
                if review is None
                else (review.lower() in ("1", "true", "yes"))
            ),
            page=page,
            per=per,
        )
        return _ok(
            {"rows": rows, "total": total, "page": page, "per": per},
            request_id=req,
        )
    except Exception as e:
        return _err(e, 400)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.route("/<sponsor_entity_ulid>/crm/edit", methods=["GET", "POST"])
@login_required
@rbac("staff", "admin")
def sponsor_crm_edit(sponsor_entity_ulid: str):
    sponsor = sp_svc.sponsor_view(sponsor_entity_ulid)
    if not sponsor:
        return _err(LookupError("not found"), 404)

    if request.method == "POST":
        try:
            req, actor = ensure_request_id(), get_actor_ulid()
            key = (request.form.get("key") or "").strip()
            action = (request.form.get("action") or "save").strip().lower()

            if not key:
                raise ValueError("factor key is required")

            if action == "remove":
                hist = crm_svc.patch_crm_factors(
                    sponsor_entity_ulid=sponsor_entity_ulid,
                    payload={key: None},
                    request_id=req,
                    actor_ulid=actor,
                )
                db.session.commit()
                flash(
                    "CRM factor removed." if hist else "No CRM change.",
                    "success",
                )
                return redirect(
                    url_for(
                        "sponsors.sponsor_crm_edit",
                        sponsor_entity_ulid=sponsor_entity_ulid,
                    )
                )

            active = request.form.get("active") == "on"
            strength = (request.form.get("strength") or "").strip()
            source = (request.form.get("source") or "").strip()
            note = (request.form.get("note") or "").strip()

            item = {
                "has": active,
                "strength": strength or "observed",
                "source": source or "operator",
            }
            if note:
                item["note"] = note

            hist = crm_svc.patch_crm_factors(
                sponsor_entity_ulid=sponsor_entity_ulid,
                payload={key: item},
                request_id=req,
                actor_ulid=actor,
            )
            db.session.commit()
            flash(
                "CRM factor saved." if hist else "No CRM change.",
                "success",
            )
            return redirect(
                url_for(
                    "sponsors.sponsor_crm_edit",
                    sponsor_entity_ulid=sponsor_entity_ulid,
                )
            )
        except Exception as exc:
            db.session.rollback()
            flash(str(exc) or "Unable to update CRM factor.", "error")

    editor = crm_svc.get_sponsor_crm_editor(sponsor_entity_ulid)
    note_hints = crm_svc.get_sponsor_profile_note_hints(sponsor_entity_ulid)

    return render_template(
        "sponsors/crm_edit.html",
        title=f"Sponsor CRM · {sponsor_entity_ulid}",
        sponsor=sponsor,
        entity_ulid=sponsor_entity_ulid,
        entity_card=_try_entity_name_card(sponsor_entity_ulid),
        editor=editor,
        note_hints=note_hints,
        crm_strengths=crm_svc.allowed_crm_strengths(),
        crm_sources=crm_svc.allowed_crm_sources(),
    )


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.post("/<sponsor_entity_ulid>/cultivation-task")
@login_required
@rbac("staff", "admin")
def sponsor_cultivation_task_create(sponsor_entity_ulid: str):
    sponsor = sp_svc.sponsor_view(sponsor_entity_ulid)
    if not sponsor:
        return _err(LookupError("not found"), 404)

    next_url = (
        request.form.get("next")
        or request.referrer
        or url_for(
            "sponsors.sponsor_detail_html",
            sponsor_entity_ulid=sponsor_entity_ulid,
        )
    )

    try:
        req, actor = ensure_request_id(), _actor_ulid()
        if not actor:
            raise PermissionError("actor_ulid is required")

        funding_demand_ulid = (
            request.form.get("funding_demand_ulid") or ""
        ).strip() or None
        due_at_utc = (request.form.get("due_at_utc") or "").strip() or None

        task = cal_handoff_svc.create_cultivation_task(
            sponsor_entity_ulid=sponsor_entity_ulid,
            actor_ulid=actor,
            request_id=req,
            funding_demand_ulid=funding_demand_ulid,
            assigned_to_ulid=actor,
            due_at_utc=due_at_utc,
        )
        db.session.commit()

        flash(
            f"Cultivation task created: {task['title']}",
            "success",
        )
        return redirect(next_url)
    except Exception as exc:
        db.session.rollback()
        raise


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.post(
    "/<sponsor_entity_ulid>/cultivation-outcomes/"
    "<task_ulid>/follow-up-task"
)
@login_required
@rbac("staff", "admin")
def sponsor_cultivation_follow_up_task_create(
    sponsor_entity_ulid: str,
    task_ulid: str,
):
    sponsor = sp_svc.sponsor_view(sponsor_entity_ulid)
    if not sponsor:
        return _err(LookupError("not found"), 404)

    next_url = (
        request.form.get("next")
        or request.referrer
        or url_for(
            "sponsors.sponsor_detail_html",
            sponsor_entity_ulid=sponsor_entity_ulid,
        )
    )

    try:
        req, actor = ensure_request_id(), _actor_ulid()
        if not actor:
            raise PermissionError("actor_ulid is required")

        due_at_utc = (request.form.get("due_at_utc") or "").strip()
        due_at_utc = due_at_utc or None

        task = cal_handoff_svc.create_follow_up_cultivation_task(
            sponsor_entity_ulid=sponsor_entity_ulid,
            task_ulid=task_ulid,
            actor_ulid=actor,
            request_id=req,
            assigned_to_ulid=actor,
            due_at_utc=due_at_utc,
        )
        db.session.commit()

        flash(
            f"Follow-up cultivation task created: {task['title']}",
            "success",
        )
        return redirect(next_url)
    except Exception as exc:
        db.session.rollback()
        flash(
            str(exc) or "Unable to create follow-up cultivation task.",
            "error",
        )
        return redirect(next_url)


# VCDB-SEC: ACTIVE entry=staff|admin authority=none reason=operator_surface test=sponsors_route_access
@bp.post(
    "/<sponsor_entity_ulid>/cultivation-outcomes/<task_ulid>/promote-relationship-note"
)
@login_required
@rbac("staff", "admin")
def promote_cultivation_outcome_to_relationship_note(
    sponsor_entity_ulid: str,
    task_ulid: str,
):
    sponsor = sp_svc.sponsor_view(sponsor_entity_ulid)
    if not sponsor:
        return _err(LookupError("not found"), 404)

    next_url = (
        request.form.get("next")
        or request.referrer
        or url_for(
            "sponsors.sponsor_detail_html",
            sponsor_entity_ulid=sponsor_entity_ulid,
        )
    )

    try:
        req, actor = ensure_request_id(), _actor_ulid()
        if not actor:
            raise PermissionError("actor_ulid is required")

        hist = (
            cal_handoff_svc.promote_cultivation_outcome_to_relationship_note(
                sponsor_entity_ulid=sponsor_entity_ulid,
                task_ulid=task_ulid,
                actor_ulid=actor,
                request_id=req,
            )
        )
        db.session.commit()

        flash(
            "Outcome note promoted to relationship note."
            if hist
            else "No relationship note change.",
            "success",
        )
        return redirect(next_url)
    except Exception as exc:
        db.session.rollback()
        flash(
            str(exc) or "Unable to promote cultivation outcome.",
            "error",
        )
        return redirect(next_url)
