# app/extensions/errors.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ContractError(RuntimeError):
    """
    Raised by Extensions contracts when a contract boundary cannot be honored.
    Never include PII. Keep messages operator-friendly, not end-user.
    """

    code: str  # short machine code, e.g. "policy_missing", "policy_invalid"
    where: str  # contract function name, e.g. "governance_v2.get_role_catalogs"
    message: str  # human readable one-liner
    http_status: int = (
        503  # 4xx for caller misuse, 5xx for system/config problems
    )
    data: Optional[
        dict[str, Any]
    ] = None  # safe payload (paths, counts, keys)

    def __str__(self) -> str:
        return f"{self.code} @ {self.where}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        out = {
            "error": self.code,
            "where": self.where,
            "message": self.message,
            "status": self.http_status,
        }
        if self.data:
            out["data"] = self.data
        return out
