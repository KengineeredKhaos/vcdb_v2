# app/extensions/contracts/customer_v2.py

from __future__ import annotations

from dataclasses import dataclass

from app.slices.customers.services import get_eligibility_snapshot

__all__ = ["CustomerEligibilitySnapshot", "get_eligibility_snapshot"]


@dataclass(frozen=True)
class CustomerEligibilitySnapshot:
    customer_ulid: str
    is_veteran_verified: bool
    is_homeless_verified: bool
    tier1_min: int | None  # 1=immediate, 2=marginal, 3=sufficient, None=unknown
    tier2_min: int | None
    tier3_min: int | None
    as_of_iso: str
