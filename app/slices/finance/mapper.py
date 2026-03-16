# app/slices/finance/mapper.py
"""
Slice-local projection layer.

This module holds typed view/summary shapes and pure mapping functions.
It must not perform DB queries/writes, commits/rollbacks, or Ledger emits.
"""
from __future__ import annotations

from typing import NotRequired, TypedDict


class DonationDTO(TypedDict):
    id: str
    sponsor_ulid: str
    fund_id: str
    happened_at_utc: str
    amount_cents: int
    flags: list[str]


class ReceiptDTO(TypedDict):
    id: str
    fund_id: str
    received_on: str
    source: str
    amount_cents: int
    instrument: NotRequired[str]


class ExpenseDTO(TypedDict):
    id: str
    fund_id: str
    project_id: str
    happened_at_utc: str
    vendor: str
    amount_cents: int
    expense_type: str
    approved_by_ulid: NotRequired[str | None]
    flags: NotRequired[list[str]]
