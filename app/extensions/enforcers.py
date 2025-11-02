# app/extensions/enforcers.py

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from app.lib.errors import PolicyError


class _Enforcers:
    def __init__(self) -> None:
        self._map: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Optional[Callable[..., Any]] = None):
        """
        Usage:
          enforcers.register("my_check", fn)
        or:
          @enforcers.register("my_check")
          def my_check(...): ...
        """
        if fn is None:

            def deco(f: Callable[..., Any]):
                self._map[name] = f
                return f

            return deco
        self._map[name] = fn
        return fn

    def get(self, name: str, default: Optional[Callable[..., Any]] = None):
        return self._map.get(name, default)

    def names(self) -> tuple[str, ...]:
        return tuple(self._map.keys())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._map

    def __getattr__(self, name: str) -> Callable[..., Any]:
        try:
            return self._map[name]
        except KeyError:
            # Raise AttributeError for unknown attributes
            # (expected by Python tooling)
            raise AttributeError(
                f"enforcer '{name}' not registered"
            ) from None


enforcers = _Enforcers()


# -----------------
# Calendar
# blackout check
# -----------------
import importlib


@enforcers.register("calendar_blackout_ok")
def calendar_blackout_ok(ctx) -> Tuple[bool, Dict[str, Any]]:
    """
    Gate: calendar blackout
      - If contract is unavailable: allow (soft) with reason="calendar_unavailable"
      - If contract says blackout (True or (True, label)): deny with reason="calendar_blackout" and optional window
      - If contract says no blackout (False): allow with reason="ok"
    """
    when_iso = getattr(ctx, "when_iso", None)
    project_ulid = getattr(ctx, "project_ulid", None)

    # Try to load the contract and function
    try:
        from app.extensions.contracts import calendar_v2  # type: ignore

        is_blackout = getattr(calendar_v2, "is_blackout", None)
    except Exception:
        is_blackout = None

    # Contract missing/unavailable -> soft-allow
    if not callable(is_blackout):
        return True, {"reason": "calendar_unavailable"}

    # Ask the contract
    try:
        result = is_blackout(when_iso, project_ulid)
    except Exception:
        # Defensive: treat errors as deny with a clear reason
        return False, {"reason": "calendar_error"}

    # Normalize results
    if result is False:
        return True, {"reason": "ok"}

    if result is True:
        return False, {"reason": "calendar_blackout"}

    if isinstance(result, tuple) and result and result[0] is True:
        label = result[1] if len(result) > 1 else None
        meta = {"reason": "calendar_blackout"}
        if label:
            meta["window"] = label
        return False, meta

    # Anything else: treat as allow
    return True, {"reason": "ok"}


"""Lightweight named hook registry for policy/runtime checks."""

__all__ = ["enforcers", "_Enforcers"]
