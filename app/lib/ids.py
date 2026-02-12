# app/lib/ids.py
# VCDB CANON — ULID generator + SQLAlchemy PK/FK helpers
# (python-ulid required)

"""
VCDB ULID helpers and SQLAlchemy ID primitives.

This module centralizes all ULID-related logic:

- new_ulid(): generate a canonical 26-char ULID string.
- ulid_min_for() / ulid_max_for(): compute key-range ULIDs for a given
  datetime (used for time-sliced queries).
- is_ulid() / is_ulid_strict(): shallow vs strict validation.
- ulid_sort_key() / ulid_ts_ms(): helpers for sorting and timestamp
  extraction.

All entity primary keys are ULIDs, and every FK points to a ULID column.
If you need an ID, you should be using these helpers instead of uuid4
or ad-hoc strings.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from ulid import ULID  # python-ulid

# -----------------
# ULID generation
# -----------------


def new_ulid() -> str:
    """Return a canonical 26-char ULID string
    (Crockford base32, upper-case)."""
    return str(ULID())


_CROCK: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCK_SET = frozenset(_CROCK)


def _encode_crockford_base32(value: int, length: int) -> str:
    out = ["0"] * length
    for i in range(length - 1, -1, -1):
        out[i] = _CROCK[value & 31]
        value >>= 5
    return "".join(out)


def _dt_to_ms(dt: datetime) -> int:
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return int(dt.timestamp() * 1000)


def ulid_min_for(dt: datetime) -> str:
    """Smallest ULID (lexicographically) for the given datetime (UTC)."""
    ms = _dt_to_ms(dt)
    return _encode_crockford_base32(ms, 10) + ("0" * 16)


def ulid_max_for(dt: datetime) -> str:
    """Largest ULID (lexicographically) for the given datetime (UTC)."""
    ms = _dt_to_ms(dt)
    return _encode_crockford_base32(ms, 10) + ("Z" * 16)


def is_ulid(s: str) -> bool:
    """Shallow validation: 26 chars, Crockford base32 uppercase."""
    return (
        isinstance(s, str)
        and len(s) == 26
        and all(ch in _CROCK_SET for ch in s)
    )


# -----------------
# Strict validation
# & helpers
# -----------------


def is_ulid_strict(s: str) -> bool:
    """Parse via python-ulid; True only if fully valid ULID."""
    try:
        ULID.from_str(s)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def ulid_sort_key(s: str) -> bytes:
    """Key function for sorting ULIDs (lexicographic == chronological)."""
    return s.encode("ascii", "strict")


def ulid_ts_ms(s: str) -> int:
    """Extract timestamp (ms) from a ULID string."""
    u = ULID.from_str(s)  # type: ignore[attr-defined]
    # python-ulid exposes .timestamp as datetime; convert to ms
    dt = u.timestamp().replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


__all__ = [
    "new_ulid",
    "is_ulid",
    "ulid_min_for",
    "ulid_max_for",
]
