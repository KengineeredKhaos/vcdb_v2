# app/extensions/__init__.py
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from email.utils import parseaddr
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, Optional

from flask import session
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.lib.chrono import parse_iso8601, to_iso8601, now_iso8601_ms
from app.lib.ids import new_ulid

# -----------------------
# Core singletons
# -----------------------
login_manager = LoginManager()
csrf = CSRFProtect()
db = SQLAlchemy()
migrate = Migrate()


# -----------------
# JSON / CSV Handler
# -----------------
def _cast_json_or_iter(v):
    if v is None:
        return ()
    if isinstance(v, (list, tuple, set)):
        return tuple(v)
    s = str(v).strip()
    if s.startswith("[") or s.startswith("{"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return tuple(parsed)
        except Exception:
            pass
    # fallback: CSV
    return tuple(p.strip() for p in s.split(",") if p.strip())


# -----------------
# Bootstrap Initialization
# -----------------


def ensure_initialized() -> None:
    """
    Idempotent; call from app factory after blueprints/contracts are wired.
    Ensures defaults are bootstrapped into DB, then refreshes the cache.
    """
    global _INIT
    if _INIT:
        return

    # 1) Bootstrap defaults into DB if missing
    try:
        from app.slices.governance import services as gov

        for family in gov.list_policy_keys():
            # This call inserts the default as an active row if none exists yet
            gov.get_policy_value(family)
    except Exception as e:
        # Don't fail app boot — if Governance isn’t ready yet, we’ll still refresh whatever exists
        print(f"[policy] bootstrap skipped: {e}")

    # 2) Load the active rows into the in-process cache
    refresh()


# -----------------
# State Code Helpers
# -----------------
def us_state_codes() -> tuple[str, ...]:
    """
    Allowed state/territory codes for validation.
    Governance can override via policy['entity.us_states']
    (JSON list of codes).
    Fallback: keys from geo.US_STATE_CODES.
    """
    default_codes = tuple(_STATE_MAP.keys())
    return tuple(
        policy.get(
            "entity.us_states", default=default_codes, cast=_cast_json_or_iter
        )
    )


def us_state_choices() -> tuple[tuple[str, str], ...]:
    """
    (code, label) pairs for Select widgets, using long 'name' by default.
    """
    codes = us_state_codes()
    return tuple((c, _STATE_MAP.get(c, {}).get("name", c)) for c in codes)


def state_label(code: str) -> str:
    """Get the display name for a code (fallbacks to the code)."""
    return _STATE_MAP.get(code, {}).get("name", code)


# -----------------
# Entity API
# -----------------
class _EntityAPI:
    def __init__(self):
        self._impl = {}

    def register(self, **impl):
        self._impl.update(impl)

    # stable signatures
    def ensure_person(self, **kw):
        return self._impl["ensure_person"](**kw)

    def ensure_org(self, **kw):
        return self._impl["ensure_org"](**kw)

    def upsert_contacts(self, **kw):
        return self._impl["upsert_contacts"](**kw)

    def upsert_address(self, **kw):
        return self._impl["upsert_address"](**kw)

    def ensure_role(self, **kw):
        return self._impl["ensure_role"](**kw)


entity_api = _EntityAPI()


# -----------------
# Entity read-side Facade
# -----------------


class EntityReadFacade:
    def __init__(self):
        self._impl = {}

    def register(self, **kw):
        self._impl.update(kw)

    def list_people_with_role(self, role_code: str, page: int, per: int):
        fn = self._impl.get("list_people_with_role")
        if not fn:
            raise RuntimeError(
                "entity_read.list_people_with_role not registered"
            )
        return fn(role_code=role_code, page=page, per=per)

    def person_view(self, person_id: str):
        fn = self._impl.get("person_view")
        if not fn:
            raise RuntimeError("entity_read.person_view not registered")
        return fn(person_id=person_id)


entity_read = EntityReadFacade()


# -----------------------------------------
# Auth context shim: current_actor_id (ULID)
# -----------------------------------------


def current_actor_id() -> Optional[str]:
    """
    Return a stable ULID for the *actor* in this session.
    In prod you might store an actor ULID on the user row; for dev we cache in session.
    """
    if not getattr(current_user, "is_authenticated", False):
        return None
    key = f"actor_ulid:u{getattr(current_user, 'id', 'anon')}"
    if key not in session:
        session[key] = new_ulid()
    return session[key]


# -----------------------
# Event bus (optional sink)
# -----------------------


class _EventBus:
    """
    Thin façade to forward events to an optional persistence sink.
    If no sink is registered, emit() is a no-op (returns request_id).
    """

    def __init__(self) -> None:
        self._sink: Optional[Callable[[Dict[str, Any]], str]] = None

    def register_sink(
        self, sink: Optional[Callable[[Dict[str, Any]], str]] = None
    ) -> None:
        """
        Register a callable(event_env) -> ULID (or any str).
        If sink is None, persistence is disabled — emit() will no-op and return request_id.
        """
        self._sink = sink

    def emit(
        self,
        *,
        type: str,
        slice: str,
        request_id: str,
        happened_at: Optional[str] = None,
        operation: Optional[str] = None,
        actor_id: Optional[str] = None,
        target_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        changed_fields: Optional[Dict[str, Any]] = None,
        entity_ids: Optional[Dict[str, Any]] = None,
        refs: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> str:
        # Normalize timestamp to ISO-8601 Z string from your chrono helper
        if happened_at is None:
            happened_at = now_iso8601_ms()

        env: Dict[str, Any] = {
            "type": type,
            "slice": slice,
            "request_id": request_id,
            "happened_at": happened_at,
            "operation": operation,
            "actor_id": actor_id,
            "target_id": target_id,
            "customer_id": customer_id,
            "changed_fields": changed_fields,
            "entity_ids": entity_ids,
            "refs": refs,
            "correlation_id": correlation_id,
            "reason": reason,
        }

        # If no sink registered, no-op but succeed
        if self._sink is None:
            return request_id

        return self._sink(env)


event_bus = _EventBus()


# -----------------------
# Policy registry (lazy DB-backed cache)
# -----------------------


class PolicyError(RuntimeError):
    """Raised when a required policy is missing or violated."""


class _Policy:
    """
    Cross-cutting policy lookup:
      - policy.get("key", default=..., cast=int)
      - policy.require("key", cast=int, validate=lambda v: ..., default=None)
      - policy.refresh()
      - policy.snapshot()
    Lazily loads governance_policy table on first use (fallback).
    If a provider is registered, delegates to it.
    """

    def __init__(self) -> None:
        self._cache: Optional[Dict[str, str]] = None
        self._loaded_at: Optional[datetime] = None
        # provider hooks (optional)
        self._get_provider: Optional[
            Callable[[str, Any, Optional[Callable[[Any], Any]]], Any]
        ] = None
        self._require_provider: Optional[
            Callable[
                [
                    str,
                    Optional[Callable[[Any], Any]],
                    Optional[Callable[[Any], bool]],
                    Any,
                    Optional[str],
                ],
                Any,
            ]
        ] = None
        self._refresh_provider: Optional[Callable[[], None]] = None
        self._snapshot_provider: Optional[Callable[[], Dict[str, str]]] = None

    def register_provider(
        self,
        *,
        get: Callable[[str, Any, Optional[Callable[[Any], Any]]], Any],
        require: Callable[
            [
                str,
                Optional[Callable[[Any], Any]],
                Optional[Callable[[Any], bool]],
                Any,
                Optional[str],
            ],
            Any,
        ],
        refresh: Callable[[], None],
        snapshot: Callable[[], Dict[str, str]],
    ) -> None:
        self._get_provider = get
        self._require_provider = require
        self._refresh_provider = refresh
        self._snapshot_provider = snapshot

    def _load(self) -> None:
        try:
            # Lazy import keeps extensions independent
            from app.slices.governance.models import GovernancePolicy

            rows = db.session.query(GovernancePolicy).all()
            self._cache = {r.key: r.value for r in rows}
        except Exception:
            self._cache = {}
        self._loaded_at = now_iso8601_ms()

    def refresh(self) -> None:
        if self._refresh_provider:
            return self._refresh_provider()
        self._load()

    def get(
        self,
        key: str,
        default: Any = None,
        cast: Optional[Callable[[Any], Any]] = None,
    ) -> Any:
        if self._get_provider:
            return self._get_provider(key, default, cast)
        if self._cache is None:
            self._load()
        val = self._cache.get(key) if self._cache else None
        return default if val is None else (cast(val) if cast else val)

    def require(
        self,
        key: str,
        *,
        cast: Optional[Callable[[Any], Any]] = None,
        validate: Optional[Callable[[Any], bool]] = None,
        default: Any = None,
        reason: Optional[str] = None,
    ) -> Any:
        if self._require_provider:
            return self._require_provider(
                key, cast, validate, default, reason
            )
        v = self.get(key, default=default, cast=cast)
        if v is None:
            raise PolicyError(
                f"policy '{key}' missing" + (f": {reason}" if reason else "")
            )
        if validate and not validate(v):
            raise PolicyError(
                f"policy '{key}' failed validation (value={v!r})"
                + (f": {reason}" if reason else "")
            )
        return v

    def snapshot(self) -> Dict[str, str]:
        if self._snapshot_provider:
            return self._snapshot_provider()
        if self._cache is None:
            self._load()
        return dict(self._cache or {})


policy = _Policy()

# -----------------------
# Enforcer registry
# -----------------------


# Enforcer registry (pluggable)
class _Enforcers:
    def __init__(self) -> None:
        self._map: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._map[name] = fn

    def __getattr__(self, name: str):
        try:
            return self._map[name]
        except KeyError:
            raise PolicyError(f"enforcer '{name}' not registered")


enforcers = _Enforcers()


# -----------------
# Role codes helper
# -----------------
def _cast_csv_or_iter(v) -> tuple[str, ...]:
    if isinstance(v, (list, tuple, set)):
        return tuple(v)
    if v is None:
        return ()
    return tuple(s.strip() for s in str(v).split(",") if s.strip())


def allowed_role_codes() -> tuple[str, ...]:
    """
    Policy-driven list of allowed roles.
    Default: ('customer','resource','sponsor','governor').
    Governance can override with policy['entity.allowed_roles'] as CSV or list.
    """
    default = ("customer", "resource", "sponsor", "governor")
    return tuple(
        policy.get(
            "entity.allowed_roles", default=default, cast=_cast_csv_or_iter
        )
    )


# -----------------------
# App init
# -----------------------


def init_extensions(app):
    # Flask-Login
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.session_protection = "strong"

    # CSRF
    csrf.init_app(app)

    # SQLAlchemy
    db.init_app(app)
    # app/extensions/__init__.py

    # Global listener: fires for any SQLAlchemy Engine (only applies if DBAPI is sqlite3)
    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    # Alembic/Migrations
    migrate.init_app(app, db)

    return app


# -----------------
# Export Hygiene
# -----------------
