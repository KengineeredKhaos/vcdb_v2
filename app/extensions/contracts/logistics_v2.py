# app/extensions/contracts/logistics_v2.py

from __future__ import annotations

from typing import List

__all__ = [
    "available_skus_for_customer",
    "count_issues_in_window",
]

from app.slices.logistics.services import (
    available_skus_for_customer,
    count_issues_in_window,
)

# 🔗 Bind to provider
