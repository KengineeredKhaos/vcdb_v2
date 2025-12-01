# app/extensions/contracts/logistics_v2.py

from __future__ import annotations

from typing import Optional, TypedDict

from app.slices.logistics.issuance_services import available_skus_for_customer
from app.slices.logistics.services import count_issues_in_window


class CadenceGateDTO(TypedDict, total=False):
    eligible: bool
    next_eligible_at_iso: Optional[str]
    rule_id: str
    label: str


__schema__ = {
    "get_sku_cadence": {
        "requires": ["customer_ulid", "sku"],
        "returns_keys": [
            "eligible",
            "next_eligible_at_iso",
            "rule_id",
            "label",
        ],
    }
}


def get_sku_cadence(customer_ulid: str, sku: str) -> CadenceGateDTO:
    return {
        "eligible": True,
        "next_eligible_at_iso": None,
        "rule_id": "stub",
        "label": "stub",
    }


__all__ = [
    "available_skus_for_customer",
    "count_issues_in_window",
]


# 🔗 Bind to provider
