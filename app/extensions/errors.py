# app/extensions/errors.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ContractError(RuntimeError):
    """
    Canonical exception type for Extensions contracts.

    Semantics
    ---------
    * Raised ONLY at the contract boundary (app.extensions.contracts.*).
    * Means: the contract could not be honored in a controlled, expected way.
      - Use 4xx for caller misuse (bad args, unsupported operation, wrong state).
      - Use 5xx for system/config/runtime problems (missing policy, corrupt file,
        DB unavailable, IO error, etc.).
    * Never include PII in `message` or `data`. These are safe to log verbatim.

    Fields
    ------
    code:
        Short machine code used for programmatic branching and log filtering,
        e.g. "policy_missing", "policy_invalid", "bad_argument".
        Prefer snake_case, optionally namespaced per domain.

    where:
        Fully-qualified contract function name, e.g.
        "governance_v2.get_poc_policy" or "customers_v2.get_needs_profile".
        This should always point at the public contract surface, even if the
        error originates deeper in the stack.

    message:
        One-line, operator-friendly explanation. Human-readable, but not
        end-user copy. Think “what would an on-call engineer want to see
        at 02:00?”.

    http_status:
        HTTP status you would return if this error were exposed through an
        HTTP contract (REST/JSON). The default is 503 (“service unavailable”)
        to match common config/policy issues (see governance_v2).

        Conventions:
          - 400 / 422: caller passed bad or semantically invalid arguments
          - 404: referenced resource does not exist (from this contract’s POV)
          - 409: contract-level conflict (e.g. optimistic concurrency)
          - 5xx: system/config/runtime problems

    data:
        Optional, PII-free detail payload (paths, keys, counts, ULIDs…).
        Intended for operators and tests; safe to log and emit to the ledger.
    """

    code: str  # short machine code, e.g. "policy_missing", "policy_invalid"
    where: (
        str  # contract function name, e.g. "governance_v2.get_role_catalogs"
    )
    message: str  # human readable one-liner
    http_status: int = 503
    # 4xx for caller misuse, 5xx for system/config problems
    data: dict[str, Any] | None = None
    # safe payload (paths, counts, keys)

    def __str__(self) -> str:
        # Stable, log-friendly representation
        return f"{self.code} @ {self.where}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to a plain dict suitable for JSON logging or HTTP responses.
        """
        out = {
            "error": self.code,
            "where": self.where,
            "message": self.message,
            "status": self.http_status,
        }
        if self.data:
            out["data"] = self.data
        return out

    def __post_init__(self) -> None:
        """Populate the base Exception/RuntimeError args.

        Dataclasses do not call ``RuntimeError.__init__`` automatically.
        Having ``args`` populated improves interop with loggers/tracebacks
        and tools that expect ``exc.args`` to contain a meaningful message.
        """
        # Use the stable, log-friendly string representation.
        RuntimeError.__init__(self, self.__str__())
