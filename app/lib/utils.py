# app/lib/utils.py
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

"""
Small normalization and validation helpers for common identifiers.

This module collects a few generic input helpers:

- Email:
  - normalize_email(): lowercase + strip.
  - validate_email() / assert_valid_email(): lightweight syntax checks.
- Phone (US-style):
  - normalize_phone(): strip non-digits, drop a leading '1'.
  - validate_phone() / assert_valid_phone(): require exactly 10 digits.
- EIN:
  - normalize_ein(): extract 9 digits (or None).
  - validate_ein() / assert_valid_ein(): accept None or 9 digits.
- DOB:
  - normalize_dob(): normalize to 'YYYY-MM-DD'.
  - Accepts common input forms:
    - YYYY-MM-DD
    - YYYY/MM/DD
    - YYYYMMDD
    - MM/DD/YYYY
    - MM-DD-YYYY
  - validate_dob(): minimal sanity checks:
    - year ≥ 1900
    - not in the future
    - valid calendar date

Use these instead of sprinkling regexes and ad-hoc validation logic
throughout slices. They’re intentionally minimal and business-rule-free.

Import sanity:

from app.lib.utils import (
    normalize_dob,
    normalize_ein,
    normalize_email,
    normalize_phone,
    validate_dob,
    validate_ein,
    validate_email,
    validate_phone,
)

"""

from __future__ import annotations

import re
from datetime import date
from email.utils import parseaddr

# -----------------
# Email Normailizer
# -----------------


def normalize_email(value: str | None) -> str | None:
    """Lowercase + strip. Does not validate."""
    if not value:
        return None
    return value.strip().lower()


_EMAIL_RE = re.compile(
    r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$",
    re.IGNORECASE,
)


def validate_email(value: str | None) -> bool:
    """Lightweight email validation."""
    if not value:
        return False
    value = value.strip()
    # quick sanity via parseaddr then regex
    name, addr = parseaddr(value)
    if not addr:
        return False
    return bool(_EMAIL_RE.match(addr))


def assert_valid_email(value: str | None) -> None:
    if not validate_email(value):
        raise ValueError("Invalid email address")


# -----------------
# Phone Normalizer
# (US-style, 10-digit)
# -----------------


def normalize_phone(value: str | None) -> str | None:
    """Strip all non-digits; drop leading '1' for NANP numbers."""
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def validate_phone(value: str | None) -> bool:
    """Valid if normalization yields exactly 10 digits."""
    if not value:
        return False
    digits = normalize_phone(value)
    return bool(digits and len(digits) == 10)


def assert_valid_phone(value: str | None) -> None:
    if not validate_phone(value):
        raise ValueError("Invalid phone number (expected 10 digits)")


# -----------------
# EIN Validation
# -----------------

_EIN_DIGITS_RE = re.compile(r"^\d{9}$")
_EIN_EXTRACT_RE = re.compile(r"\d")


def normalize_ein(value: str | None) -> str | None:
    """Return 9-digit EIN string or None."""
    if value is None:
        return None
    digits = "".join(_EIN_EXTRACT_RE.findall(value))
    return digits if len(digits) == 9 else None


def validate_ein(value: str | None) -> bool:
    """True if value is None or 9 digits."""
    if value is None:
        return True
    return bool(_EIN_DIGITS_RE.fullmatch(value))


def assert_valid_ein(value: str | None) -> None:
    if not validate_ein(value):
        raise ValueError("Invalid EIN (expected 9 digits or None)")


# -----------------
# DOB Normalizer
# (canonical: YYYY-MM-DD)
# -----------------


_DOB_MIN_YEAR = 1900

_DOB_YMD_SEP_RE = re.compile(
    r"^(?P<y>\d{4})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})$"
)
_DOB_YMD_COMPACT_RE = re.compile(r"^(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})$")
_DOB_MDY_SEP_RE = re.compile(
    r"^(?P<m>\d{1,2})[-/](?P<d>\d{1,2})[-/](?P<y>\d{4})$"
)


def _parse_dob(value: str) -> date | None:
    v = (value or "").strip()
    if not v:
        return None

    # allow '.' as a separator without adding more regexes
    v = v.replace(".", "/")

    m = _DOB_YMD_SEP_RE.match(v)
    if m:
        y = int(m.group("y"))
        mo = int(m.group("m"))
        d = int(m.group("d"))
    else:
        m = _DOB_YMD_COMPACT_RE.match(v)
        if m:
            y = int(m.group("y"))
            mo = int(m.group("m"))
            d = int(m.group("d"))
        else:
            m = _DOB_MDY_SEP_RE.match(v)
            if not m:
                return None
            y = int(m.group("y"))
            mo = int(m.group("m"))
            d = int(m.group("d"))

    try:
        dt = date(y, mo, d)
    except ValueError:
        return None

    today = date.today()
    if dt.year < _DOB_MIN_YEAR:
        return None
    if dt > today:
        return None

    return dt


def normalize_dob(value: str | None) -> str | None:
    """
    Normalize date-of-birth input to canonical 'YYYY-MM-DD' or None.
    Accepts: YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD, MM/DD/YYYY, MM-DD-YYYY.
    """
    if not value:
        return None
    dt = _parse_dob(value)
    return dt.isoformat() if dt else None


def validate_dob(value: str | None) -> bool:
    """Valid if value can be normalized to a canonical DOB date."""
    if not value:
        return False
    return _parse_dob(value) is not None


def assert_valid_dob(value: str | None) -> None:
    if not validate_dob(value):
        raise ValueError("Invalid date of birth")


__all__ = [
    "normalize_email",
    "validate_email",
    "assert_valid_email",
    "normalize_phone",
    "validate_phone",
    "assert_valid_phone",
    "normalize_ein",
    "validate_ein",
    "assert_valid_ein",
    "normalize_dob",
    "validate_dob",
    "assert_valid_dob",
]
