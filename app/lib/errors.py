from __future__ import annotations
from typing import Any, Dict, Optional

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
        message: Optional[str] = None,
        *,
        status: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
        ctx: Optional[Dict[str, Any]] = None,
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


# ---- Common subclasses (use these everywhere) -----------------------------


class NotFoundError(AppError):
    code = "not_found"
    status = 404


class ValidationError(AppError):
    code = "validation_error"
    status = 400

    @classmethod
    def field(cls, field: str, msg: str) -> "ValidationError":
        return (
            cls("Invalid input")
            .with_context()
            .with_details(errors={field: msg})
        )

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
