# app/slices/auth/routes.py
from __future__ import annotations

from flask import (
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required, login_user, logout_user

from app.extensions import csrf
from app.lib.request_ctx import ensure_request_id
from app.lib.security import rbac, require_domain_role

from . import bp
from . import services as svc


@bp.get("/login", endpoint="login")
def login_form():
    nxt = request.args.get("next", "")
    return render_template("auth/login.html", next_url=nxt)


@bp.post("/login", endpoint="login_post")
def login_post():
    ensure_request_id()
    try:
        ident = request.form.get("ident", "")
        password = request.form.get("password", "")
        view = svc.authenticate(ident, password)
        # create a lightweight session user object resolved by login_manager.user_loader
        from app.slices.auth.__init__ import SessionUser

        login_user(
            SessionUser(
                ulid=view["ulid"],
                name=view["username"],
                username=view["username"],
                email=view["email"],
                roles=view["roles"],
            ),
            remember=True,
        )
        return redirect(request.form.get("next") or url_for("web.index"))
    except ValueError:
        flash("Invalid username or password", "error")
    except Exception:
        current_app.logger.exception("Unexpected error during login")
        flash("Something went wrong. Please try again.", "error")


@bp.post("/logout", endpoint="logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))


# --- Minimal admin API to manage roles (JSON) ---


@bp.post("/admin/users/<user_ulid>/roles", endpoint="admin_set_roles")
@csrf.exempt  # tests don’t send a token; exempt the JSON admin endpoint
@rbac("admin")  # our decorator returns 401/403 instead of redirecting
def admin_set_roles(user_ulid: str):
    payload = request.get_json(force=True) or {}
    roles = payload.get("roles", [])
    svc.set_account_roles(account_ulid=user_ulid, roles=roles)
    return jsonify(svc.user_view(user_ulid))
