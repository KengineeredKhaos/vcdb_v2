# app/lib/chrono.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

from __future__ import annotations

from datetime import datetime, timezone

"""
Canonical helpers (final names & meanings)

utcnow_naive() → datetime (naive UTC). Use for DB default/onupdate.
utcnow_aware() → datetime (aware UTC, tz=UTC). Use for math/comparisons.
now_iso8601_ms() → str ISO-8601 with Z, milliseconds. Use for logs/JSON.
ensure_aware_utc(dt) / as_naive_utc(dt) → normalize a dt either way.
parse_iso8601(s) → parse ISO-8601 string → aware UTC datetime.

We’ll keep aliases for legacy names so nothing explodes while you migrate:

utc_now → now_iso8601_ms (old “string now”)
utcnow_aware → utcnow_aware
utcnow_naive → utcnow_naive
parse_iso8601 → parse_iso8601

These aliases live only in chrono.py.
You can clean them out after you’ve flipped call sites.

Migration guide (quick and mechanical)

Search & replace by intent:
DB model defaults/onupdate
Replace: default=utc_now or default=utcnow_naive → default=utcnow_naive
Replace: onupdate=utc_now → onupdate=utcnow_naive
Columns: use db.DateTime (naive) for created_at_utc, updated_at_utc, etc.

Logging / JSON payloads
Replace: now_iso8601_ms() → now_iso8601_ms()
If you already have a datetime dt: to_iso8601 isn’t required;
do ensure_aware_utc(dt).isoformat().replace("+00:00","Z") or
add a tiny to_iso8601(dt) if you like.

Time math / comparisons
Replace: utcnow_aware() → utcnow_aware()

Parsing
Replace: parse_iso8601(s) → parse_iso8601(s)

Need naive for DB? → as_naive_utc(parse_iso8601(s))
"""

# -----------------
# Primary helpers
# -----------------


def utcnow_aware() -> datetime:
    """Aware UTC datetime (tzinfo=UTC)."""
    return datetime.now(timezone.utc)


def utcnow_naive() -> datetime:
    """Naive UTC datetime for DB columns (policy: naive == UTC)."""
    return utcnow_aware().replace(tzinfo=None)  # noqa: DTZ011


def ensure_aware_utc(dt: datetime) -> datetime:
    """Normalize any datetime to aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def as_naive_utc(dt: datetime) -> datetime:
    """Normalize any datetime to naive UTC."""
    return ensure_aware_utc(dt).replace(tzinfo=None)  # noqa: DTZ011


def now_iso8601_ms() -> str:
    """ISO-8601 UTC 'Z' string with millisecond precision (good for logs/wire)."""
    dt = utcnow_aware()
    ms = (dt.microsecond // 1000) * 1000
    return dt.replace(microsecond=ms).isoformat().replace("+00:00", "Z")


def parse_iso8601(s: str) -> datetime:
    """Parse ISO-8601 (accepts 'Z' or offsets) -> aware UTC datetime."""
    ss = s.replace("Z", "+00:00") if s.endswith("Z") else s
    dt = datetime.fromisoformat(ss)
    if dt.tzinfo is None:
        # Treat naive inputs as invalid to catch bugs sooner.
        raise ValueError(
            "Naive datetime not allowed; include timezone or 'Z'."
        )
    return dt.astimezone(timezone.utc)


def to_iso8601(dt: datetime) -> str:
    """
    Normalize any datetime to an ISO-8601 UTC 'Z' string (millisecond precision).
    - Naive datetimes are treated as UTC per app policy.
    - Aware datetimes are converted to UTC.
    """
    z = ensure_aware_utc(dt)  # -> aware UTC
    z = z.replace(microsecond=(z.microsecond // 1000) * 1000)  # round to ms
    return z.isoformat().replace("+00:00", "Z")


# -----------------
# Back-compat aliases
# (remove after migration)
# -----------------
utc_now = now_iso8601_ms  # legacy "string now"
utcnow_aware = utcnow_aware
utcnow_naive = utcnow_naive
parse_iso8601 = parse_iso8601

__all__ = [
    "utcnow_aware",
    "utcnow_naive",
    "ensure_aware_utc",
    "as_naive_utc",
    "now_iso8601_ms",
    "parse_iso8601",
    "to_iso8601",
    # legacy aliases (remove when safe)
    "utc_now",
    "utcnow_aware",
    "utcnow_naive",
    "parse_iso8601",
]
