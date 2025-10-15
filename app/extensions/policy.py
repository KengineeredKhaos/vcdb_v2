# app/extensions/policy.py
from __future__ import annotations
from typing import Any, Dict
import threading
import uuid
from app.lib.chrono import now_iso8601_ms

# Local cache: family -> {"value": <dict>, "version": int, "ulid": str}
_CACHE: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.RLock()
_INIT = False


def _rid() -> str:  # simple request_id for contract calls
    return uuid.uuid4().hex[:26]


def refresh() -> None:
    """
    Rebuild the entire cache from Governance via its contract 'dump_active'.
    Safe to call at boot and when 'governance.policy.updated' fires.
    """
    from app.extensions.contracts.governance import (
        v1 as gov_contract,
    )  # contract boundary (allowed)

    req = {
        "request_id": _rid(),
        "ts": now_iso8601_ms(),
        "actor_ulid": None,
        "data": {},
    }
    resp = gov_contract.dump_active(
        req
    )  # returns {"ok": True, "data": {"rows":[...]}}
    if not resp.get("ok"):
        raise RuntimeError(f"policy.refresh failed: {resp.get('error')}")
    rows = resp["data"]["rows"]

    with _LOCK:
        _CACHE.clear()
        for r in rows:
            family = f"{r['namespace']}.{r['key']}"
            _CACHE[family] = {
                "value": r["value"],
                "version": r["version"],
                "ulid": r["policy_ulid"],
            }
    global _INIT
    _INIT = True


def get(family: str, default: Any = None) -> Any:
    """
    Fast, threadsafe read. Returns the policy 'value' (the JSON object),
    or 'default' if not present.
    """
    with _LOCK:
        rec = _CACHE.get(family)
        return rec["value"] if rec else default


def require(family: str) -> Any:
    """
    Like get(), but raises if missing. Use for must-have policies.
    """
    with _LOCK:
        rec = _CACHE.get(family)
        if not rec:
            raise KeyError(f"policy not loaded: {family}")
        return rec["value"]


def meta(family: str) -> dict | None:
    """
    Return metadata {version, ulid} for observability.
    """
    with _LOCK:
        rec = _CACHE.get(family)
        return (
            None
            if not rec
            else {"version": rec["version"], "policy_ulid": rec["ulid"]}
        )


def ensure_initialized() -> None:
    """
    Idempotent; call from app factory after blueprints/contracts are wired.
    """
    global _INIT
    if _INIT:
        return
    refresh()
