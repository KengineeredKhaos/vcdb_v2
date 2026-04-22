# app/extensions/contracts/admin_v2.py

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "AdminResolutionTargetDTO",
    "AdminAlertUpsertDTO",
    "AdminAlertCloseDTO",
    "AdminAlertReceiptDTO",
    "upsert_alert",
    "close_alert",
    "acknowledge_alert",
    "set_alert_status",
    "list_active_alerts",
]


@dataclass(frozen=True)
class AdminResolutionTargetDTO:
    route_name: str
    route_params: Mapping[str, str]
    launch_label: str
    http_method: str = "GET"


@dataclass(frozen=True)
class AdminAlertUpsertDTO:
    source_slice: str
    reason_code: str
    request_id: str
    target_ulid: str | None
    title: str
    summary: str
    source_status: str
    workflow_key: str
    resolution_target: AdminResolutionTargetDTO
    context: Mapping[str, Any]


@dataclass(frozen=True)
class AdminAlertCloseDTO:
    source_slice: str
    reason_code: str
    request_id: str
    target_ulid: str | None
    source_status: str
    close_reason: str
    admin_status: str
    closed_at_utc: str | None = None


@dataclass(frozen=True)
class AdminAlertReceiptDTO:
    alert_ulid: str
    source_slice: str
    reason_code: str
    request_id: str
    target_ulid: str | None
    admin_status: str


def upsert_alert(dto: AdminAlertUpsertDTO) -> AdminAlertReceiptDTO:
    from app.slices.admin import services as provider

    return provider.upsert_alert(dto)


def close_alert(dto: AdminAlertCloseDTO) -> AdminAlertReceiptDTO | None:
    from app.slices.admin import services as provider

    return provider.close_alert(dto)


def acknowledge_alert(
    alert_ulid: str,
    *,
    actor_ulid: str,
) -> AdminAlertReceiptDTO:
    from app.slices.admin import services as provider

    return provider.acknowledge_alert(
        alert_ulid,
        actor_ulid=actor_ulid,
    )


def set_alert_status(
    alert_ulid: str,
    *,
    admin_status: str,
) -> AdminAlertReceiptDTO:
    from app.slices.admin import services as provider

    return provider.set_alert_status(
        alert_ulid,
        admin_status=admin_status,
    )


def list_active_alerts():
    from app.slices.admin import services as provider

    return provider.list_active_alerts()
