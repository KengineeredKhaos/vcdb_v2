# app/lib/errors.py
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

"""
VCDB core error types.

This module defines the base AppError hierarchy used across VCDB's core
libraries and slices. It gives us a single, structured way to represent
recoverable domain errors:

- AppError: base type with code, HTTP-ish status, message, details, and
  optional context (request_id, actor_ulid, etc.).
- Common subclasses: NotFoundError, ValidationError, PermissionDenied,
  ConflictError, PolicyError, etc.

Handlers (routes, CLI, jobs) should raise or catch these instead of
bare Exceptions wherever a caller might reasonably recover or emit a
clean error response. The JSON-friendly to_dict() output is designed to
feed directly into logs and API responses.

Public API is considered canon: do not change signatures or semantics
without a migration plan.
"""

from __future__ import annotations

from typing import Any

# ---- Core ------------------------------------------------------------------


class AppError(RuntimeError):
    """
    Base domain error.

    Attributes:
      code: machine code (stable across refactors; good for clients/tests)
      message: human-friendly summary
      status: HTTP-ish status (used by web layer; not required)
      details: structured extra info (e.g., field errors, ids, etc.)
      cause: original exception (optional)
      ctx: ltwgt context (e.g. {"request_id": "...", "actor_ulid": "..."})
    """

    code: str = "app_error"
    status: int = 500  # default; handler can map as needed

    def __init__(
        self,
        message: str | None = None,
        *,
        status: int | None = None,
        details: dict[str, Any] | None = None,
        cause: BaseException | None = None,
        ctx: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = (
            message or self.__class__.__name__.replace("_", " ").title()
        )
        if status is not None:
            self.status = status
        self.details = details or {}
        self.cause = cause
        self.ctx = ctx or {}

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
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
    def with_context(self, **ctx: Any) -> AppError:
        self.ctx.update(ctx)
        return self

    # Wrap arbitrary exception as this class (or subclass)
    @classmethod
    def wrap(cls, exc: BaseException, **kwargs: Any) -> AppError:
        return cls(str(exc), cause=exc, **kwargs)


# ---- Common subclasses (use these everywhere) -----------------------------


class NotFoundError(AppError):
    code = "not_found"
    status = 404


class ValidationError(AppError):
    code = "validation_error"
    status = 400

    @classmethod
    def field(cls, field: str, msg: str) -> ValidationError:
        return (
            cls("Invalid input")
            .with_context()
            .with_details(errors={field: msg})
        )

    def with_details(self, **details: Any) -> ValidationError:
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


class PolicyError(AppError):
    code = "policy_error"
    status = 422
