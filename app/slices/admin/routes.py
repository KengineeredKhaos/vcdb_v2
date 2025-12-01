# app/slices/admin/routes.py

"""
Ledger emits in this file need to be moved at some point.
All three are deemed acceptable exceptions for now;
refactor into Admin services when we build out the Admin slice proper
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import login_required
from sqlalchemy import text

from app.extensions import db, event_bus
from app.extensions.auth_ctx import current_actor_ulid
from app.extensions.contracts import governance_v2
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.lib.security import (
    rbac,
    require_domain_role,
    roles_required,
)
from app.slices.admin import bp
from app.slices.admin import services as admin_svc

# -----------------
# Dashboard
# -----------------


@bp.get("/")
@login_required
@roles_required("admin")
def index():
    recent = (
        db.session.execute(
            text(
                """
                SELECT id, happened_at_utc, type, slice, operation
                  FROM transactions_ledger
              ORDER BY happened_at_utc DESC, id DESC LIMIT 10
            """
            )
        )
        .mappings()
        .all()
    )
    cron = (
        db.session.execute(
            text(
                """
                SELECT job_name, last_success_utc, last_error_utc, last_error
                  FROM admin_cron_status
              ORDER BY job_name
            """
            )
        )
        .mappings()
        .all()
    )
    return render_template("admin/index.html", recent=recent, cron=cron)


# -----------------
# Data snapshot
# -----------------


@bp.post("/snapshots/db")
@login_required
@roles_required("admin")
def snapshot_db():
    dst = _sqlite_backup()
    flash(f"DB snapshot created: {os.path.basename(dst)}", "success")
    return send_file(dst, as_attachment=True)


def _sqlite_backup() -> str:
    uri = current_app.config.get(
        "SQLALCHEMY_DATABASE_URI", "sqlite:///var/app-instance/dev.db"
    )
    assert uri.startswith("sqlite:///")
    src = uri.replace("sqlite:///", "")
    os.makedirs("var/snapshots", exist_ok=True)
    ts = (
        now_iso8601_ms()
        .replace(":", "")
        .replace("-", "")
        .replace("T", "-")
        .replace("Z", "")
    )
    dst = os.path.join("var/snapshots", f"db-{ts}.sqlite")
    con_src = sqlite3.connect(src)
    con_dst = sqlite3.connect(dst)
    with con_dst:
        con_src.backup(con_dst)
    con_dst.close()
    con_src.close()
    return dst


# -----------------
# Cron
# -----------------


@bp.get("/cron")
@login_required
@roles_required("admin")
def cron_index():
    rows = (
        db.session.execute(
            text(
                """
                SELECT job_name, last_success_utc, last_error_utc, last_error
                  FROM admin_cron_status
              ORDER BY job_name
            """
            )
        )
        .mappings()
        .all()
    )
    return render_template("admin/cron.html", rows=rows)


@bp.post("/cron/ack")
@login_required
@roles_required("admin")
def cron_ack():
    job = (request.form.get("job_name") or "").strip()
    if not job:
        flash("Missing job name.", "error")
        return redirect(url_for("admin.cron_index"))

    actor = current_actor_ulid()
    try:
        admin_svc.ack_cron_job(job_name=job, actor_ulid=actor)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.cron_index"))

    flash(f"Acknowledged error for '{job}'.", "success")
    return redirect(url_for("admin.cron_index"))


@bp.post("/cron/run")
@login_required
@roles_required("admin")
def cron_run_now():
    job = (request.form.get("job_name") or "").strip()
    if not job:
        flash("Missing job name.", "error")
        return redirect(url_for("admin.cron_index"))

    actor = current_actor_ulid()
    try:
        res = admin_svc.trigger_cron_job(job_name=job, actor_ulid=actor)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("admin.cron_index"))

    if not res.enqueued:
        flash(f"Job '{job}' is not implemented in the scheduler.", "warning")
    else:
        flash(f"Triggered '{job}'.", "success")

    return redirect(url_for("admin.cron_index"))


# -----------------
# Policies UI (read)
# -----------------

# single source of truth locations:
GOV_DATA = Path("app/slices/governance/data")
AUTH_DATA = Path("app/slices/auth/data")


@bp.get("/policies")
@login_required
@roles_required("admin")
def admin_policies_index():
    # Read-only list for the Admin UI; no ledger emits in routes.
    validate = request.args.get("validate") in {"1", "true", "yes"}
    res = governance_v2.list_policies(validate=validate)
    return render_template("admin/policy_index.html", payload=res)


@bp.get("/policies/<string:key>")
@login_required
@roles_required("admin")
def admin_policies_view(key: str):
    validate = request.args.get("validate") in {"1", "true", "yes"}
    res = governance_v2.get_policy(key=key, validate=validate)
    status = (
        200
        if res.get("ok")
        else (404 if res.get("error") == "not_found" else 422)
    )
    return (
        render_template("admin/policy_view.html", key=key, payload=res),
        status,
    )


# -----------------
# Admin API
# (preview/commit)
# -----------------


@bp.post("/api/governance/policies/<string:key>")
@login_required
@roles_required("admin")
@require_domain_role("governor")
def admin_policy_update(key: str):
    """
    POST body:
      {
        "policy": {...},   # required dict
        "dry_run": true|false
      }
    """
    body = request.get_json(silent=True) or {}
    doc = body.get("policy")
    if not isinstance(doc, dict):
        return jsonify({"ok": False, "error": "invalid_payload"}), 400

    if bool(body.get("dry_run", False)):
        res = governance_v2.preview_policy_update(key=key, new_policy=doc)
        return jsonify(res), (200 if res.get("ok") else 422)

    actor = current_actor_ulid()
    res = governance_v2.commit_policy_update(
        key=key,
        new_policy=doc,
        actor_ulid=actor,
    )


@bp.get("/policies/edit")
@login_required
@roles_required("admin")
def policy_edit():
    rel = request.args.get("path", "")
    policy_path = Path(rel)

    try:
        raw = admin_svc.load_policy_text_for_edit(policy_path)
    except ValueError:
        flash("Invalid policy path.", "error")
        return redirect(url_for("admin.policy_index"))
    except FileNotFoundError:
        flash("Policy not found.", "error")
        return redirect(url_for("admin.policy_index"))

    return render_template(
        "admin/policy_edit.html",
        policy_path=str(policy_path),
        raw=raw,
    )


@bp.post("/policies/validate")
@login_required
@roles_required("admin")
def policy_validate():
    payload = request.get_json(silent=True) or {}
    policy_path = Path(payload.get("policy_path", ""))
    raw = payload.get("raw", "")

    try:
        result = admin_svc.validate_policy_raw(policy_path, raw)
    except ValueError as e:
        return (
            jsonify({"ok": False, "errors": [str(e)], "hints": []}),
            200,
        )
    except FileNotFoundError:
        return (
            jsonify(
                {"ok": False, "errors": ["Policy not found."], "hints": []}
            ),
            200,
        )

    return (
        jsonify(
            {
                "ok": result.ok,
                "errors": result.errors,
                "hints": result.hints,
            }
        ),
        200,
    )


@bp.post("/policies/save")
@login_required
@roles_required("admin")
def policy_save():
    policy_path = Path(request.form.get("policy_path", ""))
    raw = request.form.get("raw", "")

    try:
        actor = current_actor_ulid()
        result = admin_svc.save_policy_raw(
            policy_path,
            raw,
            actor_ulid=actor,
        )
    except ValueError:
        flash("Invalid path.", "error")
        return redirect(url_for("admin.policy_index"))
    except FileNotFoundError:
        flash("Policy not found.", "error")
        return redirect(url_for("admin.policy_index"))

    if not result.ok:
        for e in result.errors:
            flash(e, "error")
        for h in result.hints:
            flash(f"hint: {h}", "warning")
        return redirect(url_for("admin.policy_edit", path=str(policy_path)))

    # success path
    for h in result.hints:
        flash(f"hint: {h}", "warning")
    flash("Policy saved.", "success")
    return redirect(url_for("admin.policy_edit", path=str(policy_path)))
