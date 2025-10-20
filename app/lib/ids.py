# app/lib/ids.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

from datetime import datetime, timezone

# Support both popular ULID libs without upsetting Pyright.
try:
    # ulid-py (https://pypi.org/project/ulid-py/)
    import ulid as _ulid  # type: ignore

    def new_ulid() -> str:
        return _ulid.new().str  # e.g., "01JABCDE2FG3H4JK5MN6PQ7RS8"

except Exception:
    # python-ulid (https://pypi.org/project/ulid/)
    from ulid import ULID  # type: ignore

    def new_ulid() -> str:
        return str(ULID())


_CROCK = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode_crockford_base32(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_CROCK[value & 0b11111])
        value >>= 5
    out.reverse()
    return "".join(out)


def _dt_to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp() * 1000)


def ulid_min_for(dt: datetime) -> str:
    ms = _dt_to_ms(dt)
    time_part = _encode_crockford_base32(ms, 10)
    rand_part = "0" * 16
    return time_part + rand_part


def ulid_max_for(dt: datetime) -> str:
    ms = _dt_to_ms(dt)
    time_part = _encode_crockford_base32(ms, 10)
    rand_part = "Z" * 16
    return time_part + rand_part
