# app/extensions/contracts/admin_v1.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AdminInboxUpsertDTO:
    source_slice: str
    issue_kind: str
    source_ref_ulid: str
    subject_ref_ulid: str | None
    severity: str
    title: str
    summary: str
    source_status: str
    workflow_key: str
    resolution_route: str
    context: dict[str, Any]
    opened_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True)
class AdminInboxCloseDTO:
    source_slice: str
    issue_kind: str
    source_ref_ulid: str
    source_status: str
    closed_at_utc: str
    close_reason: str


@dataclass(frozen=True)
class AdminInboxReceiptDTO:
    inbox_item_ulid: str
    admin_status: str
    source_slice: str
    issue_kind: str
    source_ref_ulid: str
