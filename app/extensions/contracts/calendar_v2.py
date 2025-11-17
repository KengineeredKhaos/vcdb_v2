# app / extensions / contracts / calendar_v2.py

from __future__ import annotations

from typing import Optional, TypedDict


class CalendarGateDTO(TypedDict):
    ok: bool
    label: Optional[str]
    reason: str  # ok|calendar_blackout|calendar_unavailable

__schema__ = {
    "blackout_ok": {"requires": ["when_iso?"], "returns_keys": ["ok", "label", "reason"]}
}


# Provider: Calendar slice


def blackout_ok(when_iso: str | None = None) -> CalendarGateDTO:
    return {"ok": True, "label": None, "reason": "ok"}


def is_blackout(when_iso: str, project_ulid: str) -> bool | tuple[bool, str]:
    # Real implementation will consult Governance policy_calendar.json
    # For now, a harmless stub:
    return False


__all__ = ["is_blackout"]
