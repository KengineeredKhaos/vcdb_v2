# app/extensions/contracts/_funding_dto.py

from __future__ import annotations

from dataclasses import dataclass


"""
MODULE POLICY: funding contract primitives only.

This module MUST remain "pure DTO primitives" to prevent import cycles.

ALLOWED:
- @dataclass(frozen=True) DTO definitions
- typing aliases / constants
- default empty tuples

FORBIDDEN:
- importing other contract modules
- importing any slice modules (app.slices.*)
- ContractError helpers / error mapping
- chrono/time helpers
- conversion/mapping helpers (e.g., _to_money_by_key)

IMPORT DIRECTION:
- Extensions contracts MAY import this module.
- Slices MUST NOT import this module.
"""


@dataclass(frozen=True)
class MoneyByKeyDTO:
    key: str
    amount_cents: int


@dataclass(frozen=True)
class MoneyLinksDTO:
    income_journal_ulids: tuple[str, ...] = ()
    expense_journal_ulids: tuple[str, ...] = ()
    reserve_ulids: tuple[str, ...] = ()
    encumbrance_ulids: tuple[str, ...] = ()
    pledge_ulids: tuple[str, ...] = ()
    donation_ulids: tuple[str, ...] = ()
