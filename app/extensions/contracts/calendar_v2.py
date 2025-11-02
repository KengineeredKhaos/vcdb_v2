# app / extensions / contracts / calendar_v2.py

from __future__ import annotations


# Provider: Calendar slice


def is_blackout(when_iso: str, project_ulid: str) -> bool | tuple[bool, str]:
    # Real implementation will consult Governance policy_calendar.json
    # For now, a harmless stub:
    return False


__all__ = ["is_blackout"]
