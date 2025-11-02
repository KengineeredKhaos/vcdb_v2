# app/extensions/contracts/governance_v2.py

from __future__ import annotations

from dataclasses import dataclass

from app.slices.governance.services import decide_issue

# bind to live module

__all__ = [
    "IssueDecision",
    "RestrictionContext",
    "decide_issue",
]


@dataclass(frozen=True)
class IssueDecision:
    allowed: bool
    reason: str | None
    approver_required: str | None  # e.g., "Treasurer" if over cap
    next_eligible_at_iso: str | None  # if denied by cadence
    limit_window_label: str | None  # e.g., "per_year", "per_quarter"


@dataclass(frozen=True)
class RestrictionContext:
    customer_ulid: str
    sku_code: str
    classification_key: str
    cost_cents: int
    as_of_iso: str
    project_ulid: str | None = None
