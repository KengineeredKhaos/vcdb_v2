# app/lib/utils.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

"""
Small normalization and validation helpers for common identifiers.

This module collects a few generic input helpers:

- Email:
  - normalize_email(): lowercase/strip only.
  - validate_email() / assert_valid_email(): lightweight syntax checks.
- Phone (US-style):
  - normalize_phone(): strip non-digits, drop leading '1'.
  - validate_phone() / assert_valid_phone(): require exactly 10 digits.
- EIN:
  - normalize_ein(): extract 9 digits or None.
  - validate_ein() / assert_valid_ein(): accept None or 9 digits.

Use these instead of sprinkling regexes and ad-hoc validation logic
throughout slices. They’re intentionally minimal and business-rule-free.
"""

from __future__ import annotations

import re
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
]
