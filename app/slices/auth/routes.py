# app/slices/auth/routes.py
"""
VCDB v2 — Auth slice routes

Auth route-owned audit / transaction deviation
==============================================

This slice intentionally deviates from the general project mutation pattern.

- Auth services mutate and may flush.
- Auth services do NOT emit Ledger events.
- Auth routes own all canonical ``event_bus.emit(...)`` calls.
- Auth routes also own explicit ``db.session.commit()`` / rollback framing.

Why:
- login failure is a negative-outcome event that still must be auditable
- logout success is a session-lifecycle event that still must be auditable
- keeping all Auth audit writes at the route layer is simpler and easier for
  Future Dev to reason about than splitting emits between routes and services

This deviation is slice-local and deliberate.
"""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import (
    current_user,
    login_required,
    login_user,
    logout_user,
)

from app.extensions import csrf, db, event_bus
from app.lib.ids import new_ulid
from app.lib.request_ctx import ensure_request_id
from app.lib.security import rbac

from . import services as svc

bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth",
    template_folder="templates",
)


def _session_account_ulid() -> str | None:
    if getattr(current_user, "is_authenticated", False):
        value = getattr(current_user, "ulid", None)
        if value:
            return str(value)

    sess = session.get("session_user")
    if isinstance(sess, dict):
        value = (
            sess.get("ulid")
            or sess.get("user_ulid")
            or sess.get("account_ulid")
        )
        if value:
            return str(value)

    return None


def _safe_next_url(raw_value: str | None) -> str:
    value = str(raw_value or "").strip()
    if value.startswith("/") and not value.startswith("//"):
        return value
    return url_for("web.index")


def _request_id_value() -> str:
    rid = ensure_request_id()
    if rid:
        return str(rid)

    g_rid = getattr(g, "request_id", None)
    if g_rid:
        return str(g_rid)

    return new_ulid()


def _current_actor_ulid() -> str | None:
    if getattr(current_user, "is_authenticated", False):
        return getattr(current_user, "ulid", None)
    return None


def _emit_and_commit(
    *,
    operation: str,
    target_ulid: str | None = None,
    actor_ulid: str | None = None,
    refs: dict[str, object] | None = None,
    changed: dict[str, object] | None = None,
    meta: dict[str, object] | None = None,
) -> None:
    event_bus.emit(
        domain="auth",
        operation=operation,
        request_id=_request_id_value(),
        actor_ulid=actor_ulid
        if actor_ulid is not None
        else _current_actor_ulid(),
        target_ulid=target_ulid,
        refs=refs,
        changed=changed,
        meta=meta,
    )
    db.session.commit()


def _rollback_with_log(message: str) -> None:
    db.session.rollback()
    current_app.logger.exception(message)


@bp.get("/login", endpoint="login")
def login_form():
    nxt = request.args.get("next", "")
    return render_template("auth/login.html", next_url=nxt)


@bp.post("/login", endpoint="login_post")
def login_post():
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    next_url = request.form.get("next", "")

    try:
        view = svc.authenticate(username, password)

        from app.slices.auth import SessionUser, session_identity_from_view

        identity = session_identity_from_view(view)
        session["session_user"] = identity
        login_user(SessionUser(**identity), remember=False)

        _emit_and_commit(
            operation="login_succeeded",
            actor_ulid=str(view["ulid"]),
            target_ulid=str(view["ulid"]),
            meta={
                "must_change_password": bool(
                    view.get("must_change_password", False)
                ),
                "roles": list(view.get("roles") or []),
            },
        )

        if identity.get("must_change_password"):
            return redirect(
                url_for("auth.change_password_form", next=next_url)
            )

        return redirect(_safe_next_url(next_url))

    except ValueError:
        try:
            failure_view = svc.get_auth_failure_view(username)
            target_ulid = None
            meta: dict[str, object] = {
                "reason": "invalid_credentials",
                "had_username": bool(str(username or "").strip()),
            }
            if failure_view is not None:
                target_ulid = str(failure_view["ulid"])
                meta["failed_login_attempts"] = int(
                    failure_view["failed_login_attempts"]
                )
                meta["is_locked"] = bool(failure_view["is_locked"])

            _emit_and_commit(
                operation="login_failed",
                target_ulid=target_ulid,
                meta=meta,
            )
        except Exception:
            session.pop("session_user", None)
            try:
                logout_user()
            except Exception:
                pass
            _rollback_with_log("Auth login failure commit/audit failed")
            flash("Something went wrong. Please try again.", "error")
            return redirect(url_for("auth.login", next=next_url))

        flash("Invalid username or password", "error")
        return redirect(url_for("auth.login", next=next_url))

    except Exception:
        session.pop("session_user", None)
        try:
            logout_user()
        except Exception:
            pass
        _rollback_with_log("Unexpected error during login")
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for("auth.login", next=next_url))


@bp.get("/change-password", endpoint="change_password_form")
@login_required
def change_password_form():
    nxt = request.args.get("next", "")
    return render_template("auth/change_password.html", next_url=nxt)


@bp.post("/change-password", endpoint="change_password_post")
@login_required
def change_password_post():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    next_url = request.form.get("next", "")

    try:
        if not str(current_password or "").strip():
            raise ValueError("Current password is required.")

        if not str(new_password or ""):
            raise ValueError("New password is required.")

        if not str(confirm_password or ""):
            raise ValueError("Please confirm the new password.")

        if new_password != confirm_password:
            raise ValueError("New password and confirmation do not match.")

        account_ulid = getattr(current_user, "ulid", None) or (
            session.get("session_user") or {}
        ).get("ulid")
        if not account_ulid:
            raise LookupError("No authenticated account ULID in session.")

        view = svc.change_own_password(
            str(account_ulid),
            current_password=current_password,
            new_password=new_password,
        )

        _emit_and_commit(
            operation="password_changed",
            actor_ulid=str(view["ulid"]),
            target_ulid=str(view["ulid"]),
            changed={
                "fields": [
                    "password_hash",
                    "password_changed_at_utc",
                    "must_change_password",
                    "failed_login_attempts",
                ]
            },
            meta={"self_service": True},
        )

        from app.slices.auth import SessionUser, session_identity_from_view

        identity = session_identity_from_view(view)
        session["session_user"] = identity
        login_user(SessionUser(**identity), remember=False)

        flash("Password changed.", "info")
        return redirect(_safe_next_url(next_url))

    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("auth.change_password_form", next=next_url))

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "Password change failed: %s: %s",
            type(exc).__name__,
            exc,
        )
        flash(
            f"DEBUG password change failed: {type(exc).__name__}: {exc}",
            "error",
        )
        return redirect(url_for("auth.change_password_form", next=next_url))


@bp.post("/logout", endpoint="logout")
@login_required
def logout():
    actor_ulid = _session_account_ulid()

    try:
        _emit_and_commit(
            operation="logout_succeeded",
            actor_ulid=actor_ulid,
            target_ulid=actor_ulid,
        )
    except Exception:
        _rollback_with_log("Unexpected error during logout")
        flash("Sign out could not be completed.", "error")
        return redirect(url_for("web.index"))

    session.pop("session_user", None)
    session.pop("assumed_domain_roles", None)
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.post("/bootstrap/first-admin", endpoint="bootstrap_first_admin")
@csrf.exempt
def bootstrap_first_admin():
    payload = request.get_json(silent=True) or {}

    try:
        view = svc.bootstrap_first_admin(
            username=payload.get("username", ""),
            password=payload.get("password", ""),
            email=payload.get("email"),
            entity_ulid=payload.get("entity_ulid"),
        )

        _emit_and_commit(
            operation="bootstrap_first_admin_created",
            target_ulid=str(view["ulid"]),
            changed={
                "fields": [
                    "username",
                    "password_hash",
                    "roles",
                    "is_active",
                    "must_change_password",
                ]
            },
            meta={"roles": list(view.get("roles") or [])},
        )

        return jsonify(view), 201

    except PermissionError as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 409

    except ValueError as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400

    except Exception:
        _rollback_with_log("Unexpected error during first-admin bootstrap")
        return (
            jsonify({"ok": False, "error": "bootstrap failed unexpectedly"}),
            500,
        )


@bp.get("/admin/users", endpoint="admin_list_users")
@rbac("admin")
def admin_list_users():
    items = svc.list_user_views()
    return jsonify(
        {
            "items": items,
            "count": len(items),
        }
    )


@bp.get("/admin/users/<user_ulid>", endpoint="admin_get_user")
@rbac("admin")
def admin_get_user(user_ulid: str):
    try:
        view = svc.get_user_view(user_ulid)
        return jsonify(view)
    except LookupError:
        abort(404)


@bp.post("/admin/users", endpoint="admin_create_user")
@csrf.exempt
@rbac("admin")
def admin_create_user():
    payload = request.get_json(silent=True) or {}

    try:
        view = svc.create_account(
            username=payload.get("username", ""),
            password=payload.get("password", ""),
            roles=payload.get("roles", ["user"]),
            email=payload.get("email"),
            entity_ulid=payload.get("entity_ulid"),
            is_active=payload.get("is_active", True),
            must_change_password=payload.get(
                "must_change_password",
                True,
            ),
        )

        _emit_and_commit(
            operation="account_created",
            actor_ulid=str(view["ulid"]),
            target_ulid=str(view["ulid"]),
            changed={
                "fields": [
                    "username",
                    "password_hash",
                    "roles",
                    "is_active",
                    "must_change_password",
                ]
            },
            meta={
                "roles": list(view.get("roles") or []),
                "is_active": bool(view.get("is_active", True)),
                "must_change_password": bool(
                    view.get("must_change_password", False)
                ),
            },
        )

        return jsonify(view), 201

    except ValueError as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400

    except Exception:
        _rollback_with_log("Unexpected error during account create")
        return jsonify({"ok": False, "error": "account create failed"}), 500


@bp.post(
    "/admin/users/<user_ulid>/reset-password",
    endpoint="admin_reset_password",
)
@csrf.exempt
@rbac("admin")
def admin_reset_password(user_ulid: str):
    payload = request.get_json(silent=True) or {}
    temporary_password = payload.get("temporary_password", "")

    try:
        view = svc.admin_reset_password(
            account_ulid=user_ulid,
            temporary_password=temporary_password,
        )

        _emit_and_commit(
            operation="account_password_reset",
            target_ulid=user_ulid,
            changed={
                "fields": [
                    "password_hash",
                    "password_changed_at_utc",
                    "must_change_password",
                    "reset_issued_at_utc",
                ]
            },
            meta={"must_change_password": True},
        )

        return jsonify(view)

    except LookupError:
        db.session.rollback()
        abort(404)

    except ValueError as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400

    except Exception:
        _rollback_with_log("Unexpected error during admin password reset")
        return (
            jsonify({"ok": False, "error": "password reset failed"}),
            500,
        )


@bp.post("/admin/users/<user_ulid>/unlock", endpoint="admin_unlock_user")
@csrf.exempt
@rbac("admin")
def admin_unlock_user(user_ulid: str):
    try:
        view = svc.unlock_account(user_ulid)

        _emit_and_commit(
            operation="account_unlocked",
            target_ulid=user_ulid,
            changed={
                "fields": [
                    "is_locked",
                    "failed_login_attempts",
                    "locked_at_utc",
                    "locked_by_ulid",
                ]
            },
        )

        return jsonify(view)

    except LookupError:
        db.session.rollback()
        abort(404)

    except Exception:
        _rollback_with_log("Unexpected error during account unlock")
        return jsonify({"ok": False, "error": "unlock failed"}), 500


@bp.post("/admin/users/<user_ulid>/active", endpoint="admin_set_active")
@csrf.exempt
@rbac("admin")
def admin_set_active(user_ulid: str):
    payload = request.get_json(silent=True) or {}
    is_active = payload.get("is_active")
    if not isinstance(is_active, bool):
        return (
            jsonify({"ok": False, "error": "is_active must be a boolean"}),
            400,
        )

    try:
        view = svc.set_account_active(
            account_ulid=user_ulid,
            is_active=is_active,
        )

        _emit_and_commit(
            operation=(
                "account_activated" if is_active else "account_deactivated"
            ),
            target_ulid=user_ulid,
            changed={"fields": ["is_active"]},
        )

        return jsonify(view)

    except LookupError:
        db.session.rollback()
        abort(404)

    except Exception:
        _rollback_with_log(
            "Unexpected error during account activation toggle"
        )
        return (
            jsonify({"ok": False, "error": "active toggle failed"}),
            500,
        )


@bp.post("/admin/users/<user_ulid>/roles", endpoint="admin_set_roles")
@csrf.exempt
@rbac("admin")
def admin_set_roles(user_ulid: str):
    payload = request.get_json(silent=True) or {}
    roles = payload.get("roles", [])

    if not isinstance(roles, list):
        return jsonify({"ok": False, "error": "roles must be a list"}), 400

    try:
        view = svc.set_account_roles(
            account_ulid=user_ulid,
            roles=roles,
        )

        _emit_and_commit(
            operation="account_roles_updated",
            actor_ulid=str(view["ulid"]),
            target_ulid=user_ulid,
            changed={"fields": ["roles"]},
            meta={"roles": list(view.get("roles") or [])},
        )

        return jsonify(view)

    except LookupError:
        db.session.rollback()
        abort(404)

    except ValueError as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400

    except Exception:
        _rollback_with_log("Unexpected error during role update")
        return (
            jsonify({"ok": False, "error": "role update failed"}),
            500,
        )
