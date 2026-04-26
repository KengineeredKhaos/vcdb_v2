# app/slices/ledger/errors.py

from __future__ import annotations


class LedgerError(RuntimeError):
    """Base provider error for Ledger slice operations."""


class LedgerBadArgument(LedgerError, ValueError):
    """Caller supplied invalid append/verify arguments."""


class LedgerUnavailable(LedgerError):
    """Ledger persistence backend is unavailable."""


class ProviderTemporarilyDown(LedgerUnavailable):
    """
    Ledger provider/storage is temporarily unavailable.

    Use this for retryable/transient provider conditions such as database
    locks, connection interruptions, or temporary storage unavailability.
    """


class LedgerIntegrityError(LedgerError):
    """Ledger chain verification found broken integrity."""


class EventHashConflict(LedgerIntegrityError):
    """
    Ledger append/replay would create an inconsistent or conflicting event.

    Use this for idempotency conflicts, hash-chain fork/collision conditions,
    or append races that could not be resolved safely inside the provider.
    """


class LedgerHashchainFailure(LedgerIntegrityError):
    """
    Ledger hash-chain state is too broken for routine operation.

    This is for failure posture, not ordinary survivable anomalies.
    """
