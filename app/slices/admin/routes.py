# app/slices/admin/routes.py
from __future__ import annotations

import difflib
import json
import os
import sqlite3
from pathlib import Path

from flask import (
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

# POLICY helpers from our extensions
# POLICY helpers from our extensions
from app.extensions.policies import (
    canonicalize_json,
    load_policy,
    save_policy,
    validate_json_schema,
)
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.slices.admin import bp
from app.slices.auth.decorators import roles_required

# Optional semantic validators (safe to import if you added them)
try:
    from app.extensions.policy_semantics import (
        validate_issuance_semantics,
        validate_rbac_semantics,
    )
except Exception:

    def validate_issuance_semantics(doc: dict) -> list[str]:
        return []

    def validate_rbac_semantics(doc: dict) -> list[str]:
        return []


# ---------- Dashboard ----------
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


# ---------- Data snapshot ----------
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


# ---------- Cron ----------
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
    event_bus.emit(
        type="cron.job.acknowledged",
        slice="admin",
        operation="acknowledged",
        request_id=new_ulid(),
        actor_ulid=None,
        target_ulid=None,
        happened_at_utc=now_iso8601_ms(),
        refs={"job_name": job},
    )
    db.session.execute(
        text(
            "UPDATE admin_cron_status SET last_error = NULL WHERE job_name = :job"
        ),
        {"job": job},
    )
    db.session.commit()
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
    event_bus.emit(
        type="cron.job.triggered",
        slice="admin",
        operation="triggered",
        request_id=new_ulid(),
        actor_ulid=None,
        target_ulid=None,
        happened_at_utc=now_iso8601_ms(),
        refs={"job_name": job},
    )
    if not _enqueue_job(job):
        flash(
            f"No runner configured for '{job}'. (Recorded request.)", "info"
        )
    else:
        flash(f"Triggered '{job}'.", "success")
    return redirect(url_for("admin.cron_index"))


def _enqueue_job(job_name: str) -> bool:
    return False  # plug your scheduler later


# ---------- Policies UI ----------
# single source of truth locations:
GOV_DATA = Path("app/slices/governance/data")
AUTH_DATA = Path("app/slices/auth/data")


@bp.get("/policies")
@login_required
@roles_required("admin")
def policy_index():
    items = []
    for root, label in [(GOV_DATA, "governance"), (AUTH_DATA, "auth")]:
        if root.exists():
            for p in sorted(root.glob("*.json")):
                items.append({"area": label, "name": p.name, "path": str(p)})
    return render_template("admin/policy_index.html", items=items)


@bp.get("/policies/edit")
@login_required
@roles_required("admin")
def policy_edit():
    rel = request.args.get("path", "")
    if ".." in rel:
        flash("Invalid policy path.", "error")
        return redirect(url_for("admin.policy_index"))
    # only allow under our data roots
    abs_path = Path(rel)
    if not abs_path.exists() or (
        not str(abs_path).startswith(str(GOV_DATA))
        and not str(abs_path).startswith(str(AUTH_DATA))
    ):
        flash("Policy not found.", "error")
        return redirect(url_for("admin.policy_index"))

    raw = abs_path.read_text(encoding="utf-8")
    return render_template(
        "admin/policy_edit.html", policy_path=str(abs_path), raw=raw
    )


@bp.post("/policies/validate")
@login_required
@roles_required("admin")
def policy_validate():
    payload = request.get_json(silent=True) or {}
    policy_path = Path(payload.get("policy_path", ""))
    raw = payload.get("raw", "")
    try:
        doc = json.loads(raw)
    except Exception as e:
        return (
            jsonify({"ok": False, "errors": [f"JSON parse error: {e}"]}),
            200,
        )

    errors = []
    hints = []

    # pick schema + semantics by filename
    name = policy_path.name
    try:
        if name == "policy_issuance.json":
            errors += validate_json_schema("policy_issuance.schema.json", doc)
            hints += validate_issuance_semantics(doc)
        elif name == "policy_rbac.json":
            errors += validate_json_schema(
                "policy_rbac.schema.json",
                doc,
                base_dir="app/slices/auth/data/schemas",
            )
            hints += validate_rbac_semantics(doc)
        else:
            # generic check: is JSON + canonicalizable
            canonicalize_json(doc)
    except Exception as e:
        errors.append(f"validation error: {e}")

    return jsonify({"ok": not errors, "errors": errors, "hints": hints}), 200


@bp.post("/policies/save")
@login_required
@roles_required("admin")
def policy_save():
    policy_path = Path(request.form.get("policy_path", ""))
    raw = request.form.get("raw", "")

    # minimal guard
    if ".." in str(policy_path):
        flash("Invalid path.", "error")
        return redirect(url_for("admin.policy_index"))
    if not policy_path.exists():
        flash("Policy not found.", "error")
        return redirect(url_for("admin.policy_index"))

    try:
        doc = json.loads(raw)
    except Exception as e:
        flash(f"JSON parse error: {e}", "error")
        return redirect(url_for("admin.policy_edit", path=str(policy_path)))

    # schema + semantic validate before write
    name = policy_path.name
    errors = []
    hints = []
    try:
        if name == "policy_issuance.json":
            errors += validate_json_schema("policy_issuance.schema.json", doc)
            hints += validate_issuance_semantics(doc)
        elif name == "policy_rbac.json":
            errors += validate_json_schema(
                "policy_rbac.schema.json",
                doc,
                base_dir="app/slices/auth/data/schemas",
            )
            hints += validate_rbac_semantics(doc)
        else:
            canonicalize_json(doc)
    except Exception as e:
        errors.append(f"validation error: {e}")

    if errors:
        for e in errors:
            flash(e, "error")
        for h in hints:
            flash(f"hint: {h}", "warning")
        return redirect(url_for("admin.policy_edit", path=str(policy_path)))

    # save canonicalized JSON
    save_policy(str(policy_path), doc)

    # emit a ledger event (names only)
    event_bus.emit(
        type="policy.saved",
        slice="admin",
        operation="save",
        request_id=new_ulid(),
        actor_ulid=None,
        target_ulid=None,
        happened_at_utc=now_iso8601_ms(),
        refs={"path": str(policy_path.name)},
    )
    db.session.commit()

    for h in hints:
        flash(f"hint: {h}", "warning")
    flash("Policy saved.", "success")
    return redirect(url_for("admin.policy_edit", path=str(policy_path)))
