# app/extensions/contracts/admin_v1.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "RetiredAdminV1Error",
    "AdminInboxCloseDTO",
    "AdminInboxReceiptDTO",
    "AdminInboxUpsertDTO",
    "upsert_inbox_item",
    "close_inbox_item",
]


@dataclass(frozen=True)
class AdminInboxUpsertDTO:

    def __init__(self, *args, **kwargs) -> None:
        _raise_retired_admin_v1("AdminInboxUpsertDTO")


@dataclass(frozen=True)
class AdminInboxCloseDTO:
    def __init__(self, *args, **kwargs) -> None:
        _raise_retired_admin_v1("AdminInboxCloseDTO")


@dataclass(frozen=True)
class AdminInboxReceiptDTO:
    def __init__(self, *args, **kwargs) -> None:
        _raise_retired_admin_v1("AdminInboxReceiptDTO")


class RetiredAdminV1Error(RuntimeError):
    """Raised when retired admin_v1 contract paths are used."""

_RETIRED_ADMIN_V1_MESSAGE = (
    "admin_v1 is retired and must not be used. "
    "Migrate this caller to app.extensions.contracts.admin_v2."
)


def _raise_retired_admin_v1(symbol_name: str) -> None:
    raise RetiredAdminV1Error(
        f"{symbol_name}: {_RETIRED_ADMIN_V1_MESSAGE}"
    )
def upsert_inbox_item(dto: AdminInboxUpsertDTO) -> AdminInboxReceiptDTO:
    _raise_retired_admin_v1("upsert_inbox_item")


def close_inbox_item(
    dto: AdminInboxCloseDTO,
) -> AdminInboxReceiptDTO | None:
    _raise_retired_admin_v1("close_inbox_item")