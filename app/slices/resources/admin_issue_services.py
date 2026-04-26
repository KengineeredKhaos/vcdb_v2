# app/slices/resources/admin_issue_services.py

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.extensions import db, event_bus
from app.extensions.contracts.admin_v2 import (
    AdminAlertCloseDTO,
    AdminAlertReceiptDTO,
    AdminAlertUpsertDTO,
    AdminResolutionTargetDTO,
    close_alert,
    upsert_alert,
)
from app.lib.chrono import now_iso8601_ms
from app.lib.guards import ensure_actor_ulid, ensure_request_id

from .models import Resource, ResourceAdminIssue

REASON_CODE_ONBOARD = "advisory_resources_onboard"

SOURCE_STATUS_PENDING = "pending_review"
SOURCE_STATUS_APPROVED = "approved"
SOURCE_STATUS_REJECTED = "rejected"
SOURCE_STATUS_CANCELLED = "cancelled"


def raise_onboard_admin_issue(
    *,
    entity_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> AdminAlertReceiptDTO:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)

    issue = _get_open_issue(
        request_id=rid,
        target_ulid=entity_ulid,
        reason_code=REASON_CODE_ONBOARD,
    )
    if issue is None:
        issue = _create_onboard_issue(
            target_ulid=entity_ulid,
            actor_ulid=act,
            request_id=rid,
        )

    receipt = upsert_alert(
        AdminAlertUpsertDTO(
            source_slice="resources",
            reason_code=issue.reason_code,
            request_id=str(issue.request_id),
            target_ulid=issue.target_ulid,
            title=issue.title,
            summary=issue.summary,
            source_status=issue.source_status,
            workflow_key="resources_onboard_issue",
            resolution_target=AdminResolutionTargetDTO(
                route_name="resources.admin_issue_onboard_get",
                route_params={"issue_ulid": issue.ulid},
                launch_label="Open resource onboarding issue",
            ),
            context=_build_onboard_issue_context(entity_ulid),
        )
    )
    db.session.flush()
    return receipt


def onboard_issue_get(issue_ulid: str) -> dict[str, Any]:
    issue = _get_issue_or_raise(issue_ulid)
    return {
        "issue_ulid": issue.ulid,
        "request_id": issue.request_id,
        "target_ulid": issue.target_ulid,
        "reason_code": issue.reason_code,
        "source_status": issue.source_status,
        "title": issue.title,
        "summary": issue.summary,
        "facts": _build_onboard_issue_context(str(issue.target_ulid)),
        "allowed_decisions": ("approve", "reject"),
        "as_of_utc": now_iso8601_ms(),
    }


def resolve_onboard_admin_issue(
    *,
    issue_ulid: str,
    decision: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> AdminAlertReceiptDTO | None:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()

    issue = _get_issue_or_raise(issue_ulid)

    if issue.closed_at_utc:
        return close_onboard_admin_issue(
            issue_ulid=issue.ulid,
            source_status=issue.source_status,
            close_reason="already_terminal",
            admin_status="source_closed",
        )

    if decision == "approve":
        source_status = SOURCE_STATUS_APPROVED
        close_reason = "approved_in_resources"
        event_name = "resource.admin_issue.onboard.approved"
        _apply_onboard_approval(
            target_ulid=str(issue.target_ulid),
            actor_ulid=act,
            request_id=rid,
        )
    elif decision == "reject":
        source_status = SOURCE_STATUS_REJECTED
        close_reason = "rejected_in_resources"
        event_name = "resource.admin_issue.onboard.rejected"
        _apply_onboard_rejection(
            target_ulid=str(issue.target_ulid),
            actor_ulid=act,
            request_id=rid,
        )
    else:
        raise ValueError("decision must be 'approve' or 'reject'")

    _mark_issue_terminal(
        issue_ulid=issue.ulid,
        source_status=source_status,
        actor_ulid=act,
        request_id=rid,
    )

    receipt = close_onboard_admin_issue(
        issue_ulid=issue.ulid,
        source_status=source_status,
        close_reason=close_reason,
        admin_status="resolved",
    )

    event_bus.emit(
        domain="resources",
        operation="admin_issue_resolution",
        actor_ulid=act,
        target_ulid=str(issue.target_ulid),
        request_id=rid,
        happened_at_utc=now,
        changed={
            "fields": [
                "issue_ulid",
                "reason_code",
                "source_status",
            ]
        },
        meta={
            "origin": "admin_issue",
            "event_name": event_name,
            "resource_admin_issue_ulid": issue.ulid,
        },
    )

    db.session.flush()
    return receipt


def close_onboard_admin_issue(
    *,
    issue_ulid: str,
    source_status: str,
    close_reason: str,
    admin_status: str = "resolved",
) -> AdminAlertReceiptDTO | None:
    issue = _get_issue_or_raise(issue_ulid)
    if not issue.request_id:
        raise ValueError(
            "ResourceAdminIssue.request_id is required to close admin alert"
        )

    return close_alert(
        AdminAlertCloseDTO(
            source_slice="resources",
            reason_code=issue.reason_code,
            request_id=issue.request_id,
            target_ulid=issue.target_ulid,
            source_status=source_status,
            close_reason=close_reason,
            admin_status=admin_status,
        )
    )


# -----------------
# Internal helpers
# -----------------


def _get_open_issue(
    *,
    request_id: str,
    target_ulid: str,
    reason_code: str,
) -> ResourceAdminIssue | None:
    stmt = (
        select(ResourceAdminIssue)
        .where(
            ResourceAdminIssue.request_id == request_id,
            ResourceAdminIssue.target_ulid == target_ulid,
            ResourceAdminIssue.reason_code == reason_code,
            ResourceAdminIssue.closed_at_utc.is_(None),
        )
        .order_by(ResourceAdminIssue.created_at_utc.desc())
        .limit(1)
    )
    return db.session.execute(stmt).scalar_one_or_none()


def _create_onboard_issue(
    *,
    target_ulid: str,
    actor_ulid: str,
    request_id: str,
) -> ResourceAdminIssue:
    now = now_iso8601_ms()

    issue = ResourceAdminIssue(
        target_ulid=target_ulid,
        reason_code=REASON_CODE_ONBOARD,
        source_status=SOURCE_STATUS_PENDING,
        requested_by_actor_ulid=actor_ulid,
        resolved_by_actor_ulid=None,
        request_id=request_id,
        title="Resource onboarding review required",
        summary=(
            "Admin review is required before resource onboarding is "
            "considered complete."
        ),
        details_json=_build_onboard_issue_context(target_ulid),
        created_at_utc=now,
        updated_at_utc=now,
        closed_at_utc=None,
    )
    db.session.add(issue)
    db.session.flush()
    return issue


def _get_issue_or_raise(issue_ulid: str) -> ResourceAdminIssue:
    issue = db.session.get(ResourceAdminIssue, issue_ulid)
    if not issue:
        raise LookupError(f"Resource admin issue not found: {issue_ulid}")
    return issue


def _build_onboard_issue_context(target_ulid: str) -> dict[str, Any]:
    """
    Build a non-PII context payload for Admin alert display and issue page.
    """
    from . import onboard_services as wiz

    snap = wiz.review_snapshot(entity_ulid=target_ulid)
    view = snap.get("view")
    pocs = snap.get("pocs") or []

    return {
        "target_ulid": target_ulid,
        "reason_code": REASON_CODE_ONBOARD,
        "readiness_status": getattr(view, "readiness_status", None),
        "mou_status": getattr(view, "mou_status", None),
        "admin_review_required": getattr(view, "admin_review_required", None),
        "capability_count": len(
            getattr(view, "active_capabilities", []) or []
        ),
        "poc_count": len(pocs),
    }


def _apply_onboard_approval(
    *,
    target_ulid: str,
    actor_ulid: str,
    request_id: str | None,
) -> None:
    resource = _get_resource_or_raise(target_ulid)
    now = now_iso8601_ms()

    resource.readiness_status = "active"
    resource.admin_review_required = False

    if hasattr(resource, "last_touch_utc"):
        resource.last_touch_utc = now

    db.session.flush()


def _apply_onboard_rejection(
    *,
    target_ulid: str,
    actor_ulid: str,
    request_id: str | None,
) -> None:
    resource = _get_resource_or_raise(target_ulid)
    now = now_iso8601_ms()

    resource.readiness_status = "draft"
    resource.admin_review_required = True

    if hasattr(resource, "last_touch_utc"):
        resource.last_touch_utc = now

    db.session.flush()


def _mark_issue_terminal(
    *,
    issue_ulid: str,
    source_status: str,
    actor_ulid: str,
    request_id: str | None,
) -> None:
    issue = _get_issue_or_raise(issue_ulid)
    now = now_iso8601_ms()

    issue.source_status = source_status
    issue.resolved_by_actor_ulid = actor_ulid
    issue.request_id = request_id
    issue.closed_at_utc = now
    issue.updated_at_utc = now

    db.session.flush()


def _get_resource_or_raise(target_ulid: str) -> Resource:
    resource = db.session.get(Resource, target_ulid)
    if not resource:
        raise LookupError(f"Resource not found: {target_ulid}")
    return resource
