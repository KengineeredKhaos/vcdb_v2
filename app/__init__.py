# app/__init__.py
from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from flask import Flask, g, jsonify, request
from flask_login import (
    UserMixin,
    current_user,
    login_user,
)
from jinja2 import StrictUndefined
from sqlalchemy import text
from werkzeug.exceptions import HTTPException

from app.cli import register_cli
from app.extensions.errors import ContractError
from app.lib.chrono import parse_iso8601, utcnow_aware
from app.lib.logging import configure_logging

from .extensions import csrf, init_extensions


def _bind_contracts(app: Flask) -> None:
    # Intentionally empty; contracts are imported on demand by slices.
    pass
    # Nothing else required for boot; specific bind calls happen below.


# -----------------
# ---   CREATE APP   ---   (Time to make the donuts)
# -----------------
# create the app framework and load object from config.py
def create_app(config_object="config.DevConfig"):
    """Single app factory. Boring, deterministic, test-friendly."""
    flask_app = Flask(
        __name__, template_folder="templates", instance_relative_config=True
    )
    flask_app.config.from_object(config_object)

    # prod | staging | development | test

    # --- DB defaults (must be before init_extensions) ---
    # Prefer explicit SQLALCHEMY_DATABASE_URI; otherwise derive from DATABASE,
    # otherwise fall back to instance/dev.db.
    # Resolve DB URI once, predictably.
    if not flask_app.config.get("SQLALCHEMY_DATABASE_URI"):
        db_path = flask_app.config.get("DATABASE")
        if not db_path:
            Path(flask_app.instance_path).mkdir(parents=True, exist_ok=True)
            db_path = Path(flask_app.instance_path) / "dev.db"
            flask_app.config["DATABASE"] = str(db_path)
        flask_app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    # Always good to disable this noise
    flask_app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    # -----------------
    # testing logging
    # -----------------

    # Configure logging before extensions/blueprints
    configure_logging(flask_app)
    if not flask_app.testing and (
        flask_app.debug
        or flask_app.config.get("ENV") in {"dev", "development"}
    ):
        hnames = [type(h).__name__ for h in logging.getLogger().handlers]
        logging.getLogger("app").info(
            {
                "event": "boot_handlers",
                "root_handlers": hnames,
                "log_dir": flask_app.config.get("LOG_DIR"),
            }
        )

    # init extensions first
    init_extensions(flask_app)

    # Bind CSRF after core extensions are attached
    csrf.init_app(flask_app)

    # -------------
    # CSRF + Jinja + http error handlers
    # (after extensions, before blueprints)
    # -------------

    try:
        from flask_wtf.csrf import CSRFError, generate_csrf
    except Exception:  # allow tests/envs without Flask-WTF
        CSRFError = None

        def generate_csrf() -> str:
            return ""

    # Make {{ csrf_token() }} available in templates
    flask_app.jinja_env.globals["csrf_token"] = generate_csrf

    if CSRFError is not None:

        @flask_app.errorhandler(CSRFError)
        def handle_csrf_error(e):
            return (
                {
                    "error": "csrf_failed",
                    "description": getattr(
                        e,
                        "description",
                        "CSRF validation failed.",
                    ),
                },
                400,
            )

    # jinja strict mode (keep) & Currency filter

    flask_app.jinja_env.undefined = StrictUndefined

    def currency(cents: int | None) -> str:
        v = int(cents or 0)
        return f"${v/100:,.2f}"

    flask_app.jinja_env.filters["currency"] = currency

    # -------------
    # Stub auth
    # (dev/testing only)
    # -------------
    @dataclass
    class StubUser(UserMixin):
        id: str = "stub-user"
        username: str = "stub"
        name: str = "Stub User"
        email: str = "stub@example.invalid"
        roles: list[str] = field(default_factory=list)
        domain_roles: list[str] = field(default_factory=list)

        @property
        def is_active(self) -> bool:  # flask-login expects this
            return True

        @property
        def is_authenticated(self) -> bool:
            return True

        @property
        def is_admin(self) -> bool:
            return "admin" in [r.lower() for r in (self.roles or [])]

    @flask_app.before_request
    def _apply_stub_auth():
        """Enable header-based or auto-admin stub auth in dev/testing."""
        cfg = flask_app.config
        if cfg.get("AUTH_MODE") != "stub":
            return  # real auth path

        roles: list[str] = []
        domains: list[str] = []

        # 1) Header stubs (take precedence if present)
        if cfg.get("ALLOW_HEADER_AUTH", True):
            x_rbac = request.headers.get("X-Auth-Stub")
            x_domain = request.headers.get("X-Domain-Stub")
            if x_rbac:
                roles = [x_rbac.lower()]
            if x_domain:
                domains = [x_domain.lower()]

        # 2) Auto-admin if allowed and nothing set by headers
        if not roles and cfg.get("AUTO_LOGIN_ADMIN", False):
            roles = ["admin"]

        if roles:
            user = StubUser(
                id=f"stub:{roles[0]}",
                roles=roles,
                domain_roles=domains,
            )
            # Log the user in for this request (sessionless; fine for dev)
            with suppress(Exception):
                login_user(user, remember=False, force=True, fresh=True)

    #

    # -------------
    # Register
    # <slice> blueprints
    # -------------

    # after  CSRF/Jinja are set & loaded

    # --- register blueprints ---
    from app.slices.admin import bp as admin_bp
    from app.slices.attachments import bp as attachments_bp
    from app.slices.auth import bp as auth_bp
    from app.slices.calendar import bp as calendar_bp
    from app.slices.customers import bp as customers_bp
    from app.slices.entity import bp as entity_bp
    from app.slices.finance import bp as finance_bp
    from app.slices.governance import bp as governance_bp
    from app.slices.ledger import bp as ledger_bp
    from app.slices.logistics import bp as logistics_bp
    from app.slices.resources import bp as resources_bp
    from app.slices.sponsors import bp as sponsors_bp
    from app.slices.sponsors import bp_funding as sponsors_funding_bp
    from app.web import bp as web_bp

    # ---- Registration ----
    flask_app.register_blueprint(web_bp)
    flask_app.register_blueprint(admin_bp)
    flask_app.register_blueprint(attachments_bp)
    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(calendar_bp)
    flask_app.register_blueprint(customers_bp)
    flask_app.register_blueprint(entity_bp)
    flask_app.register_blueprint(finance_bp)
    flask_app.register_blueprint(governance_bp)
    flask_app.register_blueprint(ledger_bp)
    flask_app.register_blueprint(logistics_bp)
    flask_app.register_blueprint(resources_bp)
    flask_app.register_blueprint(sponsors_bp)
    flask_app.register_blueprint(sponsors_funding_bp)

    # -------------
    # Globals Injection
    # compact, side-effect-free
    # -------------

    @flask_app.context_processor
    def inject_globals():
        from flask import current_app
        from flask_login import current_user

        def has_endpoint(name: str) -> bool:
            return name in current_app.view_functions

        def has_blueprint(name: str) -> bool:
            return name in current_app.blueprints

        def user_is_admin() -> bool:
            roles = getattr(current_user, "roles", []) or []
            roles = [r.lower() for r in roles]
            return "admin" in roles
            # tweak if you prefer

        return {
            "current_year": datetime.now(UTC).year,
            "has_endpoint": has_endpoint,
            "has_blueprint": has_blueprint,
            "user_is_admin": user_is_admin,
        }

    # Helper (not a context processor): use inside server-side functions
    def _is_admin_user() -> bool:
        try:
            return bool(
                getattr(current_user, "is_authenticated", False)
            ) and (
                getattr(current_user, "is_admin", False)
                or ("admin" in (getattr(current_user, "roles", []) or []))
            )
        except Exception:
            return False

    @flask_app.context_processor
    def admin_alerts():
        """Lightweight admin banner fed from admin_cron_status, tolerant to absence."""
        from app.extensions import db

        if not _is_admin_user():
            return {"admin_alerts": []}
        try:
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
        except Exception:
            return {"admin_alerts": []}

        alerts: list[str] = []
        cutoff_dt = utcnow_aware() - timedelta(hours=6)
        for r in rows:
            last_err = r.get("last_error")
            if last_err:
                alerts.append(
                    f"Job {r['job_name']} error at {r.get('last_error_utc')}: {last_err}"
                )
                continue
            last_ok_iso = r.get("last_success_utc")
            if not last_ok_iso:
                alerts.append(
                    f"Job {r['job_name']} is stale; never succeeded."
                )
                continue
            try:
                if parse_iso8601(last_ok_iso) < cutoff_dt:
                    alerts.append(
                        f"Job {r['job_name']} is stale; no success in 6h (last: {last_ok_iso})."
                    )
            except Exception:
                alerts.append(
                    f"Job {r['job_name']} has unreadable timestamp: {last_ok_iso}"
                )
        return {"admin_alerts": alerts}

    @flask_app.context_processor
    def macro_ctx():
        """Expose `_macros` template module if present; tolerate absence in test."""
        try:
            tmpl = flask_app.jinja_env.get_template("_macros.html")
            return {"_macros": tmpl.module}
        except Exception:
            return {"_macros": None}

    # Global error handler (logs all exceptions once, honors debugger in dev)
    @flask_app.errorhandler(ContractError)
    def _handle_contract_error(e: ContractError):
        # Don’t log as "unhandled" — this is an expected, normalized error.
        flask_app.logger.warning(
            {
                "event": "contract_error",
                "status": e.http_status,
                "code": e.code,
                "where": e.where,
                "endpoint": request.endpoint,
                "path": request.path,
            }
        )
        payload = {
            "ok": False,
            "error": e.message,
            "code": e.code,
            "where": e.where,
        }
        if getattr(e, "data", None):
            payload["data"] = e.data
        return jsonify(payload), e.http_status

    @flask_app.errorhandler(HTTPException)
    def _handle_http_exception(e: HTTPException):
        # Keep logging once
        flask_app.logger.warning(
            {
                "event": "http_exception",
                "status": e.code,
                "error": str(e),
                "endpoint": request.endpoint,
                "path": request.path,
            }
        )
        # JSON response (not HTML)
        return (
            jsonify(
                {
                    "ok": False,
                    "error": e.name,  # e.g. "Not Found"
                    "detail": e.description,  # short explanation
                }
            ),
            e.code,
        )

    @flask_app.errorhandler(Exception)
    def _handle_any_exception(e: Exception):
        # Let pytest see the real traceback
        if flask_app.testing or flask_app.config.get("PROPAGATE_EXCEPTIONS"):
            raise

        flask_app.logger.exception(
            {
                "event": "unhandled_exception",
                "error": str(e),
                "endpoint": getattr(request, "endpoint", None),
                "path": getattr(request, "path", None),
            }
        )
        if flask_app.debug:
            raise
        return jsonify({"error": "internal_error"}), 500

    @flask_app.context_processor
    def _stub_banner():
        return {
            "_stub_auth_active": flask_app.config.get("AUTH_MODE") == "stub"
        }

    # -------------
    # dev Dbase schema check, Route dump, Sanity check
    # -------------

    # dev Dbase schema check, Route dump, Sanity check
    if flask_app.debug:
        from app.dev.boot_diag import run_on_boot

        run_on_boot(flask_app)

    register_cli(flask_app)
    return flask_app


#####################################################
##                                                 ##
##      Application Instantiation Complete         ##
##                                                 ##
#####################################################
