# app/extensions/contracts/admin_v1.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "AdminInboxCloseDTO",
    "AdminInboxReceiptDTO",
    "AdminInboxUpsertDTO",
    "upsert_inbox_item",
    "close_inbox_item",
]


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
    opened_at_utc: str | None = None
    updated_at_utc: str | None = None


@dataclass(frozen=True)
class AdminInboxCloseDTO:
    source_slice: str
    issue_kind: str
    source_ref_ulid: str
    source_status: str
    close_reason: str
    admin_status: str
    closed_at_utc: str | None = None


@dataclass(frozen=True)
class AdminInboxReceiptDTO:
    inbox_item_ulid: str
    source_slice: str
    issue_kind: str
    source_ref_ulid: str
    admin_status: str


def upsert_inbox_item(dto: AdminInboxUpsertDTO) -> AdminInboxReceiptDTO:
    """
    Publish or refresh an Admin inbox notice.

    This is a contract wrapper. It should stay thin and defer to the
    Admin slice provider/service implementation.
    """
    from app.slices.admin import services as provider

    return provider.upsert_inbox_item(dto)


def close_inbox_item(
    dto: AdminInboxCloseDTO,
) -> AdminInboxReceiptDTO | None:
    """
    Close an Admin inbox notice from the owning slice once the owning
    workflow has reached a terminal state.
    """
    from app.slices.admin import services as provider

    return provider.close_inbox_item(dto)
