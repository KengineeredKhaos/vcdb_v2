# app/extensions/enforcers.py

"""
Named hook registry for runtime policy checks ("enforcers").

This module provides a very small registry for cross-cutting "gates" that
slice code can call without knowing the underlying policy details.

Key pieces:

- `calendar_blackout_ok(ctx)`: sample gate that consults the Governance
  calendar policy (policy_calendar.json) to decide whether an operation
  is allowed at a given time. Returns (ok: bool, meta: dict) where
  meta.reason is one of {"ok", "calendar_blackout", "calendar_unavailable"}.

- `_Enforcers`: registry type that lets you do:
      enforcers.register("my_gate", fn)
    or:
      @enforcers.register("my_gate")
      def my_gate(...): ...

- `enforcers`: the singleton registry instance used by the rest of the app.

Future Dev:
- Treat enforcer names as a small, stable vocabulary. Once something is
  in use ("calendar_blackout_ok", future "cadence_ok", etc.), it becomes
  part of the implicit contract between slices and Governance policy.
- Enforcers should be thin: read policies and context, return a simple
  (ok, meta) tuple; they should not perform heavy side effects.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.extensions.policies import load_policy_operations
from app.lib.chrono import now_iso8601_ms


def calendar_blackout_ok(ctx):
    """
    Gate: calendar blackout
      Returns (ok: bool, meta: dict)
      meta.reason in {"ok","calendar_blackout","calendar_unavailable"}
      meta.label optional window label
    """
    # dev tripwire
    if getattr(ctx, "force_blackout", False):
        return False, {"reason": "calendar_blackout", "label": "dev-forced"}

    # load policy (gracefully allow if unavailable)
    try:
        pol = load_policy_operations() or {}
    except Exception:
        return True, {"reason": "calendar_unavailable"}

    when_iso = getattr(ctx, "when_iso", None) or now_iso8601_ms()

    # expect windows like [{"start":"...Z","end":"...Z","label":"..."}]
    for w in pol.get("windows", []):
        start, end = w.get("start"), w.get("end")
        if start and end and (start <= when_iso <= end):
            return False, {
                "reason": "calendar_blackout",
                "label": w.get("label"),
            }
    return True, {"reason": "ok"}


class _Enforcers:
    def __init__(self) -> None:
        self._map: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any] | None = None):
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

    def get(self, name: str, default: Callable[..., Any] | None = None):
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
enforcers.register("calendar_blackout_ok", calendar_blackout_ok)

"""Lightweight named hook registry for policy/runtime checks."""

__all__ = ["enforcers", "_Enforcers", "calendar_blackout_ok"]
