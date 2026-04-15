# app/slices/ledger/errors.py

from __future__ import annotations


class LedgerError(RuntimeError):
    """Base provider error for Ledger slice operations."""


class LedgerBadArgument(LedgerError, ValueError):
    """Caller supplied invalid append/verify arguments."""


class LedgerUnavailable(LedgerError):
    """Ledger persistence backend is unavailable."""


class LedgerIntegrityError(LedgerError):
    """Ledger chain verification found broken integrity."""
