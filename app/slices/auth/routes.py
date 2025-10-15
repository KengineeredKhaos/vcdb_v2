# app/slices/auth/routes.py
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
from flask_login import login_required, login_user, logout_user

from app.lib.request_ctx import ensure_request_id, get_actor_ulid

from . import services as svc
from .decorators import rbac
from .models import User

bp = Blueprint(
    "auth", __name__, url_prefix="/auth", template_folder="templates"
)


@bp.get("/login", endpoint="login")
def login_form():
    return render_template("auth/login.html")  # include CSRF hidden field


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
    except Exception as e:
        flash("Login failed", "error")
        return redirect(url_for("auth.login"))


@bp.post("/logout", endpoint="logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))


# --- Minimal admin API to manage roles (JSON) ---
@bp.post("/admin/users/<user_ulid>/roles")
@rbac("admin")
def admin_set_roles(user_ulid: str):
    payload = request.get_json(force=True) or {}
    roles = payload.get("roles", [])
    svc.set_account_roles(
        account_ulid=user_ulid,
        roles=roles,
        actor_entity_ulid=get_actor_ulid(),
    )
    return jsonify(svc.user_view(user_ulid))
