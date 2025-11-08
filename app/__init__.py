# app/__init__.py
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Union

from flask import Flask, jsonify, request
from flask_login import current_user
from jinja2 import StrictUndefined
from sqlalchemy import text
from werkzeug.exceptions import HTTPException

from app.cli import register_cli
from app.lib.chrono import parse_iso8601, utcnow_aware
from app.lib.logging import configure_logging
from .extensions import init_extensions
from .web import bp as web_bp


def _bind_contracts(app: Flask) -> None:
    # Intentionally empty; contracts are imported on demand by slices.
    pass
    # Nothing else required for boot; specific bind calls happen below.


# -----------------
# ---   CREATE APP   ---   (Time to make the donuts)
# -----------------
# create the app framework and load object from config.py
def create_app(config_object: Union[str, type[Any]] = "config.DevConfig") -> Flask:
    """Single app factory. Boring, deterministic, test-friendly."""
    app = Flask(__name__, template_folder="templates")
    app.config.from_object(config_object)
    app.config["APP_MODE"] = os.getenv("APP_MODE", "development")

    # prod | staging | development | test

    # --- DB defaults (must be before init_extensions) ---
    # Prefer explicit SQLALCHEMY_DATABASE_URI; otherwise derive from DATABASE,
    # otherwise fall back to instance/dev.db.
    # Resolve DB URI once, predictably.
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        db_path = app.config.get("DATABASE")
        if not db_path:
            Path(app.instance_path).mkdir(parents=True, exist_ok=True)
            db_path = Path(app.instance_path) / "dev.db"
            app.config["DATABASE"] = str(db_path)
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"


    # Always good to disable this noise
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)



    # Configure logging first
    configure_logging(app)

    # -----------------
    # testing logging
    # -----------------

    # Configure logging before extensions/blueprints
    configure_logging(app)
    if not app.testing and (app.debug or app.config.get("ENV") in {"dev", "development"}):
        hnames = [type(h).__name__ for h in logging.getLogger().handlers]
        logging.getLogger("app").info(
            {
                "event": "boot_handlers",
                "root_handlers": hnames,
                "log_dir": app.config.get("LOG_DIR"),
            }
        )

    # init extensions first
    init_extensions(app)

    from flask_wtf.csrf import CSRFError, generate_csrf

    # Make {{ csrf_token() }} available in templates
    app.jinja_env.globals["csrf_token"] = generate_csrf

    # Nice error for CSRF failures
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        return (
            {
                "error": "csrf_failed",
                "description": getattr(
                    e, "description", "CSRF validation failed."
                ),
            },
            400,
        )

    # jinja strict mode (keep)
    app.jinja_env.undefined = StrictUndefined

    # register web first (no prefix)
    app.register_blueprint(web_bp)

    # Register blueprints (slices) -- after CSRF / Jinja are set
    from app.slices.admin import bp as admin_bp
    from app.slices.attachments import bp as attachments_bp
    from app.slices.auth import bp as auth_bp
    from app.slices.calendar import bp as calendar_bp
    from app.slices.customers import bp as customers_bp
    from app.slices.devtools.routes import bp as devtools_bp
    from app.slices.entity import bp as entity_bp
    from app.slices.finance import bp as finance_bp
    from app.slices.governance import bp as governance_bp
    from app.slices.ledger import bp as ledger_bp
    from app.slices.logistics import bp as logistics_bp
    from app.slices.resources import bp as resources_bp
    from app.slices.sponsors import bp as sponsors_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(attachments_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(entity_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(governance_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(logistics_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(sponsors_bp)

    if app.config.get("APP_MODE") != "production":
        app.register_blueprint(devtools_bp)

    # -------------
    # Globals Injection
    # compact, side-effect-free
    # -------------

    @app.context_processor
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
            "current_year": datetime.now(timezone.utc).year,
            "has_endpoint": has_endpoint,
            "has_blueprint": has_blueprint,
            "user_is_admin": user_is_admin,
        }

    @app.context_processor
    def _user_is_admin() -> bool:
        try:
            # Flexible: supports either boolean flag or a roles list/tuple
            return bool(
                getattr(current_user, "is_authenticated", False)
            ) and (
                getattr(current_user, "is_admin", False)
                or ("admin" in getattr(current_user, "roles", []))
            )
        except Exception:
            return False

    @app.context_processor
    def admin_alerts():
        """Lightweight admin banner fed from admin_cron_status, tolerant to absence."""
        from app.extensions import db
        if not _user_is_admin():
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
                alerts.append(f"Job {r['job_name']} is stale; never succeeded.")
                continue
            try:
                if parse_iso8601(last_ok_iso) < cutoff_dt:
                    alerts.append(
                        f"Job {r['job_name']} is stale; no success in 6h (last: {last_ok_iso})."
                    )
            except Exception:
                alerts.append(f"Job {r['job_name']} has unreadable timestamp: {last_ok_iso}")
        return {"admin_alerts": alerts}


    @app.context_processor
    def macro_ctx():
        """Expose `_macros` template module if present; tolerate absence in test."""
        try:
            tmpl = app.jinja_env.get_template("_macros.html")
            return {"_macros": tmpl.module}
        except Exception:
            return {"_macros": None}

    # Global error handler (logs all exceptions once, honors debugger in dev)
    @app.errorhandler(Exception)
    def _handle_any_exception(e: Exception):
        if isinstance(e, HTTPException):
            app.logger.warning(
                {
                    "event": "http_exception",
                    "status": e.code,
                    "error": str(e),
                    "endpoint": request.endpoint,
                    "path": request.path,
                }
            )
            return e
        app.logger.exception(
            {
                "event": "unhandled_exception",
                "error": str(e),
                "endpoint": getattr(request, "endpoint", None),
                "path": getattr(request, "path", None),
            }
        )
        if app.debug:
            raise
        return jsonify({"error": "internal_error"}), 500

    # -------------
    # dev Dbase schema check, Route dump, Sanity check
    # -------------
    """
    Silenced during Development
    if app.debug:
        _dump_routes(app)
        _boot_sanity(app)

    # only in dev, not during tests
    if app.config.get("ENV") == "development" and not app.testing:
        _5chema_5heck(app)

    if app.debug and app.config.get("LEDGER_CHECK_ON_BOOT", True):
        _ledger_sanity(
            app, limit=int(app.config.get("LEDGER_CHECK_LIMIT", 20))
        )
    """
    register_cli(app)
    return app


#####################################################
##                                                 ##
##      Application Instantiation Complete         ##
##    everything below is strickly diagnositic     ##
##  and called directly above (see block comment)  ##
##                                                 ##
#####################################################


# -----------------
# a little route map dump (debug only)
# -----------------


def _boot_sanity(app):
    from flask_login import LoginManager

    from app.extensions import login_manager

    print("\n=== BOOT SANITY ===")
    print(f"Config object       : {app.config.get('ENV', 'unknown')}")
    print(f"DATABASE            : {app.config.get('DATABASE')}")
    sk = app.config.get("SECRET_KEY")
    print(
        f"SECRET_KEY set?     : {'OK (len='+str(len(sk))+')' if sk else 'NO'}"
    )
    print(f"Jinja Undefined     : {type(app.jinja_env.undefined).__name__}")
    print(f"Blueprints          : {', '.join(sorted(app.blueprints.keys()))}")

    # --- Flask-Login ---
    lm_bound = hasattr(app, "login_manager") and isinstance(
        app.login_manager, LoginManager
    )
    user_loader_set = (
        getattr(login_manager, "_user_callback", None) is not None
    )
    request_loader_set = (
        getattr(login_manager, "_request_callback", None) is not None
    )
    login_view = getattr(login_manager, "login_view", None) or "—"

    print("Extensions loaded   :", ", ".join(sorted(app.extensions.keys())))
    print("--- Flask-Login ---")
    print(f"login_manager bound : {'OK' if lm_bound else 'NO'}")
    print(f"user_loader set     : {'OK' if user_loader_set else 'NO'}")
    print(f"request_loader set  : {'OK' if request_loader_set else 'NO'}")
    print(f"login_view          : {login_view}")
    print("====================\n")


def _dump_routes(app):
    """Compact route map (methods/rule -> endpoint) plus DB echo."""
    print("\n=== ROUTES ===")
    rows = []
    for rule in app.url_map.iter_rules():
        methods = ",".join(
            m
            for m in sorted(rule.methods or [])
            if m in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        )
        rows.append((rule.rule, methods, rule.endpoint))
    for rule, methods, endpoint in sorted(rows, key=lambda x: (x[0], x[1])):
        print(f"{methods:6} {rule:35} -> {endpoint}")
    print("=== END ROUTES ===")
    print("DEV_DB_PATH =", app.config.get("DATABASE"))


def _5chema_5heck(app):
    from app.extensions import db
    from sqlalchemy import inspect

    with app.app_context():
        insp = inspect(db.engine)

    """
    Read-only SQLite schema sanity.
    - Fast table presence check (always)
    - Optional column check (nullable/PK/type), disabled by default for speed/noise
    Config toggles (all optional):
      SCHEMA_CHECK_DEEP = bool       # default False (turn on to compare columns)
      SCHEMA_CHECK_PREFIXES = list   # only compare columns for tables starting with these prefixes
      SCHEMA_CHECK_IGNORE_UNKNOWN = set  # tables to ignore if present in DB but not in models
    """
    deep = bool(app.config.get("SCHEMA_CHECK_DEEP", False))
    prefixes = (
        app.config.get("SCHEMA_CHECK_PREFIXES") or []
    )  # e.g., ["resources_", "governance_", "transactions_"]
    ignore_unknown = set(app.config.get("SCHEMA_CHECK_IGNORE_UNKNOWN") or [])

    def type_equiv(model_t: str, db_t: str) -> bool:
        # Normalize common aliases (SQLite reports)
        aliases = {
            "String": {"VARCHAR", "NVARCHAR", "TEXT"},
            "Text": {"TEXT", "CLOB"},
            "Integer": {"INTEGER", "INT"},
            "DateTime": {"DATETIME", "TIMESTAMP"},
            "Date": {"DATE"},
            "Boolean": {
                "BOOLEAN",
                "BOOL",
                "INTEGER",
            },  # SQLite often stores as int
        }
        if model_t == db_t:
            return True
        return db_t in aliases.get(model_t, set())

    def type_name(coltype) -> str:
        try:
            return coltype.__class__.__name__
        except Exception:
            return str(coltype)

    with app.app_context():
        insp = inspect(db.engine)

        declared = dict(db.metadata.tables)  # {table_name: Table}
        existing = set(insp.get_table_names())

        # Tables
        missing = sorted([t for t in declared if t not in existing])
        unknown = sorted((existing - set(declared)) - ignore_unknown)

        # Log brief always
        app.logger.info("=== SCHEMA CHECK ===")
        app.logger.info(
            "declared: %d  existing: %d  deep:%s",
            len(declared),
            len(existing),
            deep,
        )
        if missing:
            app.logger.warning("MISSING tables: %s", ", ".join(missing))
        else:
            app.logger.info("MISSING tables: none")
        if unknown:
            app.logger.warning("UNKNOWN tables: %s", ", ".join(unknown))
        else:
            app.logger.info("UNKNOWN tables: none")

        col_issues = {}  # table -> list[str]

        if deep:
            # optional column checks (small and focused)
            # scope: either all declared tables, or those matching given prefixes
            def in_scope(tname: str) -> bool:
                if not prefixes:
                    return True
                return any(tname.startswith(pfx) for pfx in prefixes)

            for tname, table in declared.items():
                if tname not in existing or not in_scope(tname):
                    continue

                try:
                    db_cols = {c["name"]: c for c in insp.get_columns(tname)}
                except Exception as e:
                    app.logger.warning(
                        "Column inspect failed for %s: %s", tname, e
                    )
                    continue

                model_cols = {c.name: c for c in table.columns}
                issues = []

                # presence
                miss_cols = [c for c in model_cols if c not in db_cols]
                unk_cols = [c for c in db_cols if c not in model_cols]
                if miss_cols:
                    issues.append("missing: " + ", ".join(sorted(miss_cols)))
                if unk_cols:
                    issues.append("unknown: " + ", ".join(sorted(unk_cols)))

                # common cols (nullable/PK/type)
                common = sorted(set(model_cols) & set(db_cols))
                try:
                    pk = insp.get_pk_constraint(tname) or {}
                    db_pk = set(pk.get("constrained_columns") or [])
                except Exception:
                    db_pk = set()

                for cname in common:
                    mcol = model_cols[cname]
                    dcol = db_cols[cname]

                    # nullable
                    if bool(mcol.nullable) != bool(
                        dcol.get("nullable", True)
                    ):
                        issues.append(
                            f"{cname}: nullable model={bool(mcol.nullable)} db={bool(dcol.get('nullable', True))}"
                        )

                    # primary key
                    if bool(mcol.primary_key) != (cname in db_pk):
                        issues.append(
                            f"{cname}: pk model={bool(mcol.primary_key)} db={(cname in db_pk)}"
                        )

                    # loose type compare
                    m_t = type_name(mcol.type)
                    d_t = type_name(dcol.get("type") or NullType())
                    if not type_equiv(m_t, d_t):
                        issues.append(f"{cname}: type {m_t} vs {d_t}")

                if issues:
                    col_issues[tname] = issues
                    # one log line per table keeps logs readable
                    app.logger.warning("[%s] %s", tname, " | ".join(issues))

        app.logger.info("====================")

        # Print once to stdout ONLY if problems (so it’s unmissable on boot)
        if missing or unknown or col_issues:
            print("\n*** SCHEMA WARNINGS ***")
            if missing:
                print(f"- Missing tables: {', '.join(missing)}")
                print(
                    "  Hint: run  PYTHONPATH=. python scripts/db_create_all.py"
                )
            if unknown:
                print(
                    f"- Unknown tables (in DB, not in models): {', '.join(unknown)}"
                )
            if col_issues:
                for tname, issues in col_issues.items():
                    print(f"- {tname}:")
                    for i in issues:
                        print(f"    • {i}")
            print("*** END SCHEMA WARNINGS ***\n")
        else:
            # Print a single green line (optional, easy to comment out)
            print("SCHEMA OK")


def _ledger_sanity(app, limit: int = 20) -> None:
    """
    Verify the hash chain for the last `limit` events (if a ledger table exists):
      - newest.prev_event_id == previous.id
      - newest.prev_hash == previous.event_hash
      - recomputed hash == stored hash

    Self-contained (no imports from slices). No-op if ledger table is absent.
    """
    try:
        from app.extensions import db

        insp = inspect(db.engine)
        tables = set(insp.get_table_names())
        if "ledger_event" in tables:
            tname = "ledger_event"
        elif "transactions_ledger" in tables:
            tname = "transactions_ledger"
        else:
            print("Ledger sanity skipped (no ledger table present).")
            return
    except Exception as e:
        print(f"Ledger sanity skipped (engine inspect failed): {e}")
        return

    # Local hash calculator (canonical json)
    import hashlib

    def _stable_hash(payload: dict) -> str:
        # Keep the exact canonical subset you persist in the table
        canonical = {
            "id": payload.get("id"),
            "happened_at_utc": payload.get("happened_at_utc"),
            "prev_event_id": payload.get("prev_event_id"),
            "prev_hash": payload.get("prev_hash"),
            "type": payload.get("type"),
            "domain": payload.get("domain"),
            "operation": payload.get("operation"),
            "request_id": payload.get("request_id"),
            "actor_ulid": payload.get("actor_ulid"),
            "target_id": payload.get("target_id"),
            "entity_ids_json": payload.get("entity_ids_json"),
            "changed_fields_json": payload.get("changed_fields_json"),
            "refs_json": payload.get("refs_json"),
        }
        raw = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    with app.app_context():
        try:
            rows = (
                db.session.execute(
                    text(
                        f"""
                        SELECT id, happened_at_utc, prev_event_id, prev_hash, event_hash,
                               type, domain, operation, request_id, actor_ulid, target_id,
                               entity_ids_json, changed_fields_json, refs_json
                          FROM {tname}
                      ORDER BY happened_at_utc DESC, id DESC
                         LIMIT :lim
                    """
                    ),
                    {"lim": limit},
                )
                .mappings()
                .all()
            )
        except Exception as e:
            print(f"Ledger sanity skipped (query failed): {e}")
            return

        if not rows:
            print("LEDGER: empty (no events yet)")
            return

        mismatches = []
        for i in range(len(rows) - 1):
            cur = dict(rows[i])
            prev = dict(rows[i + 1])

            link_ok = (cur.get("prev_event_id") == prev.get("id")) and (
                cur.get("prev_hash") == prev.get("event_hash")
            )
            rehash = _stable_hash(cur)
            hash_ok = rehash == cur.get("event_hash")

            if not (link_ok and hash_ok):
                mismatches.append(
                    {
                        "id": cur.get("id"),
                        "prev_event_id": cur.get("prev_event_id"),
                        "prev_hash": cur.get("prev_hash"),
                        "stored_event_hash": cur.get("event_hash"),
                        "recomputed_event_hash": rehash,
                        "prev_id_should_be": prev.get("id"),
                        "prev_hash_should_be": prev.get("event_hash"),
                    }
                )

        head = rows[0]
        tail = rows[-1]
        print(
            "LEDGER:",
            f"head={head['id']}  tail(window)={tail['id']}  checked={len(rows)}",
        )

        if mismatches:
            print(
                f"LEDGER: {len(mismatches)} issue(s) detected in last {len(rows)} events"
            )
            for m in mismatches[:5]:
                print("  MISMATCH:", m)
            if len(mismatches) > 5:
                print(f"  ... and {len(mismatches) - 5} more")
        else:
            print("LEDGER: chain OK for last", len(rows), "events")
