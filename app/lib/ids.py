# app/lib/ids.py
# -*- coding: utf-8 -*-
# VCDB CANON — ULID generator + SQLAlchemy PK/FK helpers
# (python-ulid required)

from __future__ import annotations

from datetime import datetime, timezone
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
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
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
# SQLAlchemy helpers
# (SQLAlchemy 2.x)
# -----------------

try:
    from sqlalchemy import ForeignKey, String
    from sqlalchemy.orm import Mapped, declarative_mixin, mapped_column
except Exception:  # pragma: no cover
    Mapped = object  # type: ignore

    def mapped_column(*args, **kwargs):  # type: ignore
        raise RuntimeError("SQLAlchemy not available")

    def ForeignKey(*args, **kwargs):  # type: ignore
        raise RuntimeError("SQLAlchemy not available")

    def declarative_mixin(cls):  # type: ignore
        return cls

    String = None  # type: ignore


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
    dt = u.timestamp().replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


from app.lib.models import ULIDFK, ULIDPK

__all__ = [
    "new_ulid",
    "is_ulid",
    "ulid_min_for",
    "ulid_max_for",
    "ULIDPK",  # from lib.models - exported here as a shim
    "ULIDFK",  # from lib.models - exported here as a shim
]
