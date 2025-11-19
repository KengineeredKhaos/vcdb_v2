# app/extensions/contracts/ledger/v2.py
"""
Compatibility shim.

Canonical ledger write-path lives in `app.extensions.contracts.ledger_v2`.
Prefer importing that directly or, better yet, use `app.extensions.event_bus`.
"""

from app.extensions.contracts.ledger_v2 import (  # noqa: F401
    CANON_API,
    CANON_VERSION,
    EmitResult,
    emit,
    verify,
)

__all__ = ["CANON_API", "CANON_VERSION", "EmitResult", "emit", "verify"]
