# app/slices/admin/routes.py
from __future__ import annotations
import difflib, json, os, sqlite3
from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
    jsonify,
)
from sqlalchemy import text

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.slices.admin import bp
from flask_login import login_required
from app.slices.auth.decorators import roles_required
from app.extensions.contracts.governance import v1 as gov_contract


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


# ---------- Ledger: verify (stub kept commented while Ledger v2 lands) ----------
# ... (leave your commented verification scaffolding as-is) ...


# ---------- Data snapshot ----------
@bp.post("/snapshots/db")
@login_required
@roles_required("admin")
def snapshot_db():
    dst = _sqlite_backup()
    flash(f"DB snapshot created: {os.path.basename(dst)}", "success")
    return send_file(dst, as_attachment=True)


def _sqlite_backup() -> str:
    # Use configured path; support sqlite:////absolute and sqlite:///relative
    uri = current_app.config.get(
        "SQLALCHEMY_DATABASE_URI", "sqlite:///var/app-instance/dev.db"
    )
    assert uri.startswith("sqlite:///")
    src = uri.replace("sqlite:///", "")
    os.makedirs("var/snapshots", exist_ok=True)
    # Build a compact filesystem-safe name from ISO timestamp
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


# ---------- Cron: list / ack / run ----------
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

    # names-only event
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
    # Hook for your scheduler; return False for now
    return False
