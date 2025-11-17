# app/lib/tracing.py
from typing import Any, Dict, Optional

from .chrono import utc_now
from .request_ctx import get_actor_ulid, get_request_id


def trace_fields(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {
        "ts": utc_now(),
        "request_id": get_request_id(),
        "actor_ulid": get_actor_ulid(),
    }
    if extra:
        out.update(extra)
    return out
