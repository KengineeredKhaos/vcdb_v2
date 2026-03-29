# app/extensions/contracts/admin_v1.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.slices.admin.mapper import (
    AdminInboxCloseDTO,
    AdminInboxReceiptDTO,
    AdminInboxUpsertDTO,
)

__all__ = [
    "AdminInboxCloseDTO",
    "AdminInboxReceiptDTO",
    "AdminInboxUpsertDTO",
    "upsert_inbox_item",
    "close_inbox_item",
]


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
