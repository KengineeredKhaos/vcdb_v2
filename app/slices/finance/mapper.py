# app/slices/finance/mapper.py
"""
Slice-local projection layer.

This module holds typed view/summary shapes and pure mapping functions.
It must not perform DB queries/writes, commits/rollbacks, or Ledger emits.
"""
from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class OpsFloatDTO:
    ops_float_ulid: str
    action: str
    support_mode: str
    source_funding_demand_ulid: str
    source_project_ulid: str | None
    dest_funding_demand_ulid: str
    dest_project_ulid: str | None
    fund_key: str
    amount_cents: int
    status: str
    parent_ops_float_ulid: str | None
    decision_fingerprint: str | None


@dataclass(frozen=True)
class OpsFloatSummaryDTO:
    funding_demand_ulid: str
    incoming_open_cents: int
    outgoing_open_cents: int
    incoming_open_by_fund: tuple[dict[str, int | str], ...]
    outgoing_open_by_fund: tuple[dict[str, int | str], ...]
    ops_float_ulids: tuple[str, ...]
