# app/extensions/contracts/errors.py
from __future__ import annotations

from typing import Any, Optional, Sequence


class ContractError(RuntimeError):
    """
    Base class for contract-layer errors.
    Carries safe, non-PII context suitable to surface at slice boundaries.
    """

    code: str = "contract_error"
    status: int = 502

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        if code:
            self.code = code
        self.details = details or {}
        self.__cause__ = cause  # preserve traceback chaining


class ContractDataNotFound(ContractError):
    """The requested data was not found in the provider slice."""

    code = "contract_data_not_found"
    status = 404


class ContractValidationError(ContractError):
    """Payload failed contract schema validation."""

    code = "validation_error"
    status = 400

    @classmethod
    def from_jsonschema(cls, exc: Exception) -> "ContractValidationError":
        # Works with jsonschema.ValidationError or lookalikes
        path: Sequence[Any] = getattr(exc, "absolute_path", ()) or getattr(
            exc, "path", ()
        )
        pointer = "/" + "/".join(map(str, path)) if path else ""
        details = {
            "pointer": pointer,  # e.g. "/roles/0"
            "validator": getattr(exc, "validator", None),
            "validator_value": getattr(exc, "validator_value", None),
            "message": str(exc),
        }
        return cls("Invalid payload", details=details, cause=exc)


class ContractConflict(ContractError):
    """Already exists / optimistic lock / hash mismatch, etc."""

    code = "contract_conflict"
    status = 409


class ContractUnavailable(ContractError):
    """Provider temporarily unavailable (DB down, dependency outage)."""

    code = "contract_unavailable"
    status = 503
