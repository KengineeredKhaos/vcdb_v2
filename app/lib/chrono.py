# app/lib/chrono.py
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

from __future__ import annotations

from datetime import UTC, date, datetime

"""
Canonical helpers (final names & meanings):

utcnow_naive() for DB DateTime
utcnow_naive() → datetime (naive UTC)

utcnow_aware() for comparisons/math
utcnow_aware() → datetime (aware UTC, tz=UTC)

now_iso8601_ms() for string timestamps,logs & JSON
now_iso8601_ms() → str (ISO-8601 with Z, milliseconds)

parse_iso8601() for inbound ISO strings
parse_iso8601(s: str) parse ISO-8601 string (aware UTC datetime)

ensure_aware_utc(dt) for normalization
ensure_aware_utc(dt: datetime) -> datetime

as_naive_utc(dt) for DB-safe conversion
as_naive_utc(dt:datetime) → str (normalize a dt)

to_iso8601(dt) for outbound ISO strings
to_iso8601(dt: datetime) -> str

Convenience helpers so callers stop inventing one-off formatting:

utc_today() -> date
utc_current_year() -> int
utc_year_month() -> str (returning "YYYY-MM")
utc_filename_stamp() -> str (returning "YYYYMMDD-HHMMSS")

We will NOT keep aliases for legacy names just so nothing explodes.





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
    return datetime.now(UTC)


def utcnow_naive() -> datetime:
    """Naive UTC datetime for DB columns (policy: naive == UTC)."""
    return utcnow_aware().replace(tzinfo=None)  # noqa: DTZ011


def ensure_aware_utc(dt: datetime) -> datetime:
    """Normalize any datetime to aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


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
    return dt.astimezone(UTC)


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
# Boring little helpers
# ------------------
"""
Usage examples so the replacements stay mechanical:

datetime.now(tz=UTC).date() → utc_today()
datetime.now(UTC).year → utc_current_year()
datetime.now(UTC).strftime("%Y-%m") → utc_year_month()
datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S") → utc_filename_stamp()
"""


def utc_today() -> date:
    """UTC calendar date for display/default buckets."""
    return utcnow_aware().date()


def utc_current_year() -> int:
    """UTC year as an int."""
    return utcnow_aware().year


def utc_year_month() -> str:
    """UTC year-month string like '2026-04'."""
    return utcnow_aware().strftime("%Y-%m")


def utc_filename_stamp() -> str:
    """UTC timestamp for filenames like '20260405-103012'."""
    return utcnow_aware().strftime("%Y%m%d-%H%M%S")


__all__ = [
    "utcnow_aware",
    "utcnow_naive",
    "ensure_aware_utc",
    "as_naive_utc",
    "parse_iso8601",
    "to_iso8601",
    "now_iso8601_ms",
    "utc_today",
    "utc_current_year",
    "utc_year_month",
    "utc_filename_stamp",
]
