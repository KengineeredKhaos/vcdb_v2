# app/lib/tracing.py
from typing import Any

from .chrono import utc_now
from .request_ctx import get_actor_ulid, get_request_id


def trace_fields(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "ts": utc_now(),
        "request_id": get_request_id(),
        "actor_ulid": get_actor_ulid(),
    }
    if extra:
        out.update(extra)
    return out
