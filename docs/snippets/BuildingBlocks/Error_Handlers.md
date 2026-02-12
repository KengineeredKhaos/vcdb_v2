Centralizing errors makes everything cleaner—services, contracts, routes, even tests. Here’s a tight, DRY pattern you can drop into `app/lib/errors.py`, plus tiny glue for Flask so web/API responses are consistent.

# app/lib/errors.py

```python
from __future__ import annotations
from typing import Any, Dict, Optional

# ---- Core --------------------------------------------------------------------

class AppError(RuntimeError):
    """
    Base domain error.

    Attributes:
      code: short machine code (stable across refactors; good for clients/tests)
      message: human-friendly summary
      status: HTTP-ish status (used by web layer; not required)
      details: structured extra info (e.g., field errors, ids, etc.)
      cause: original exception (optional)
      ctx: lightweight context (e.g., {"request_id": "...", "actor_ulid": "..."})
    """

    code: str = "app_error"
    status: int = 500  # default; handler can map as needed

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        status: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
        ctx: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__.replace("_", " ").title()
        if status is not None:
            self.status = status
        self.details = details or {}
        self.cause = cause
        self.ctx = ctx or {}

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "error": {
                "code": self.code,
                "message": self.message,
                "status": self.status,
                "details": self.details,
            }
        }
        if self.ctx:
            data["context"] = self.ctx
        return data

    # Fluent helper to add context *without* losing the original type
    def with_context(self, **ctx: Any) -> "AppError":
        self.ctx.update(ctx)
        return self

    # Wrap arbitrary exception as this class (or subclass)
    @classmethod
    def wrap(cls, exc: BaseException, **kwargs: Any) -> "AppError":
        return cls(str(exc), cause=exc, **kwargs)


# ---- Common subclasses (use these everywhere) --------------------------------

class NotFoundError(AppError):
    code = "not_found"
    status = 404


class ValidationError(AppError):
    code = "validation_error"
    status = 400

    @classmethod
    def field(cls, field: str, msg: str) -> "ValidationError":
        return cls("Invalid input").with_context().with_details(errors={field: msg})

    def with_details(self, **details: Any) -> "ValidationError":
        # convenience to attach {"errors": {...}} or other info
        self.details.update(details)
        return self


class ConflictError(AppError):
    code = "conflict"
    status = 409


class PermissionDenied(AppError):
    code = "permission_denied"
    status = 403


class AuthRequired(AppError):
    code = "auth_required"
    status = 401


class RateLimitError(AppError):
    code = "rate_limited"
    status = 429


class DataIntegrityError(AppError):
    code = "data_integrity"
    status = 500


class ExternalServiceError(AppError):
    code = "external_service_error"
    status = 502


# ---- Contract-layer shims (optional): keep facade errors consistent ----------

class ContractError(AppError):
    code = "contract_error"
    status = 502


class ContractDataNotFound(ContractError):
    code = "contract_data_not_found"
    status = 404


class ContractValidationError(ContractError):
    code = "contract_validation_error"
    status = 400
```

> Notes

- **`code`** is your stable identifier. Use it in tests and logs.

- **`details`** is where you can stash field errors, ids, etc. (keeps messages clean).

- **`with_context()`** is handy to add request_id/actor_ulid without rebuilding the error.

- Contract errors inherit from `AppError` so your handler can treat everything uniformly.

# Flask glue (single place)

Add this once (e.g., in `app/__init__.py` after `create_app` config) to render errors consistently for HTML vs. JSON routes:

```python
from flask import jsonify, request, render_template
from app.lib.errors import AppError

def register_error_handlers(app):
    @app.errorhandler(AppError)
    def handle_app_error(err: AppError):
        app.logger.warning(
            {"event": "app_error", **err.to_dict()},
            exc_info=err.cause is not None,
        )

        # Simple heuristic: API routes under /api return JSON; others render page
        wants_json = request.accept_mimetypes.best == "application/json" or request.path.startswith("/api")
        status = err.status or 500

        if wants_json:
            return jsonify(err.to_dict()), status

        # For HTML, use a generic template. You can map codes to nicer pages later.
        return render_template("error.html", error=err), status
```

Call `register_error_handlers(app)` during app setup.

# Usage examples

- **Service layer**

```python
from app.lib.errors import NotFoundError, ValidationError

def get_customer(ulid: str):
    row = db.session.get(Customer, ulid)
    if not row:
        raise NotFoundError(f"Customer {ulid} not found").with_context(customer_ulid=ulid)
    return row

def update_roles(ulid: str, roles: list[str]):
    illegal = [r for r in roles if r not in ALLOWED_ROLES]
    if illegal:
        raise ValidationError("Illegal roles").with_details(errors={"roles": illegal})
    # ... perform update
```

- **Contract facade**

```python
from app.lib.errors import ContractDataNotFound, ContractValidationError
from app.slices.governance import services as gov

def policy_get_roles():
    try:
        data = gov.policy_get("entity.roles")      # may raise NotFoundError
        gov.validate("entity.roles", data)         # may raise ValidationError
        return {"roles": data["roles"]}
    except NotFoundError as e:
        raise ContractDataNotFound().with_context(policy="entity.roles") from e
    except ValidationError as e:
        raise ContractValidationError(str(e)).with_context(policy="entity.roles") from e
```

- **Route**

```python
from app.lib.errors import AppError

@bp.route("/admin/roles/<ulid>", methods=["POST"])
def roles_update(ulid):
    try:
        # do work...
        return redirect(url_for("admin.roles_view", ulid=ulid))
    except AppError as e:
        flash(e.message, "error")
        return redirect(request.referrer or url_for("admin.index")), e.status
```

This keeps error *definitions* in one place, gives you structured data for logs/JSON, and avoids sprinkling ad-hoc messages all over the codebase. If you want, we can also add a tiny `error_codes.md` to document the canonical `code` values for future you.

Existing error handler in `app/__init__.py`

```python
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
```

Quick question, how will the proposed implementation interact with my established Global error handler as represented in the app/__init__.py file (line 297-331)?

Great question. Short version: your new contract-layer handler and your existing global handler will happily coexist—as long as you register the specific one (for `AppError`) once during `create_app`. Here’s how they interact:

# What runs when an error is raised?

- **`AppError` (and subclasses)** → handled by the specific handler you added via `register_error_handlers(app)`. That handler logs once and returns JSON for API paths or renders an HTML error page for others .

- **`HTTPException` (Flask/Werkzeug)** → bypasses `AppError` handler and is caught by your **global** `@app.errorhandler(Exception)` block, which logs a structured “http_exception” and returns the original response (status/message) .

- **Any other unexpected `Exception`** → falls through to your **global** handler, which logs an “unhandled_exception” and (in non-debug) returns `{"error": "internal_error"}` with 500 .

Because Flask chooses the **most specific** matching error handler, your `AppError` path is used first; the catch-all `Exception` handler only runs for everything else. That keeps logging single-sourced and avoids duplicate messages.

# Where to register

Call `register_error_handlers(app)` once during `create_app`, **after** logging is configured (so its log calls use your JSON formatter) and **before** requests start flowing. Anywhere after `configure_logging(app)` in your factory is fine. Your current factory already installs the global handler; adding the `AppError` registration won’t conflict with it .

# Mapping contract errors cleanly

Your contracts currently define their own light exceptions (`ValidationError`, `NotFound`, `Conflict`) at the **extensions** layer . In slice/services code, wrap those and raise an `AppError` (or a subclass) so they hit the specific handler:

- `ValidationError` → raise `app.lib.errors.ValidationError(...)`

- Missing rows → raise `app.lib.errors.NotFoundError(...)`

- State conflicts → raise `app.lib.errors.ConflictError(...)`

Those `AppError` subclasses are the types your specific handler is designed for , keeping internal exceptions behind the facade and surfacing uniform responses.

# Gotchas to avoid

- **Double logging:** Don’t log again inside services if you’re going to raise `AppError`; the `AppError` handler already logs with context .

- **Return format drift:** Your `AppError` handler switches JSON vs HTML by path/Accept header. That aligns with your global handler’s JSON fallback for unknown errors, so callers get predictable formats in both paths .

- **Registration order:** Make sure you don’t install multiple global handlers; your factory already defines one place for it and that’s perfect .

If you want, I can point to the exact spot in your `create_app` where to drop `register_error_handlers(app)` and show a tiny wrapper that translates contract errors into `AppError` subclasses.


