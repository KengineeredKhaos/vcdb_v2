# app/slices/resources/admin_review_services.py
from __future__ import annotations

from typing import Any

from app.extensions import db, event_bus
from app.extensions.contracts import admin_v1
from app.lib.chrono import now_iso8601_ms
from app.lib.guards import ensure_actor_ulid, ensure_request_id

from .models import Resource, ResourceAdminReviewRequest

REVIEW_KIND_ONBOARD = "onboard_review_required"

SOURCE_STATUS_PENDING = "pending_review"
SOURCE_STATUS_APPROVED = "approved"
SOURCE_STATUS_REJECTED = "rejected"
SOURCE_STATUS_CANCELLED = "cancelled"


def raise_onboard_admin_issue(
    *,
    entity_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> admin_v1.AdminInboxReceiptDTO:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)

    review = _create_onboard_review_request(
        entity_ulid=entity_ulid,
        actor_ulid=act,
        request_id=rid,
    )

    receipt = admin_v1.upsert_inbox_item(
        admin_v1.AdminInboxUpsertDTO(
            source_slice="resources",
            issue_kind=REVIEW_KIND_ONBOARD,
            source_ref_ulid=review.ulid,
            subject_ref_ulid=review.entity_ulid,
            severity="high",
            title=review.title,
            summary=review.summary,
            source_status=review.source_status,
            workflow_key="resource_onboard_review",
            resolution_route="resources.admin_review_onboard_get",
            context=_build_onboard_review_context(entity_ulid),
        )
    )
    db.session.flush()
    return receipt


def onboard_review_get(review_request_ulid: str) -> dict[str, Any]:
    review = _get_review_request_or_raise(review_request_ulid)
    return {
        "review_request_ulid": review.ulid,
        "source_ref_ulid": review.ulid,
        "subject_ref_ulid": review.entity_ulid,
        "issue_kind": review.review_kind,
        "source_status": review.source_status,
        "title": review.title,
        "summary": review.summary,
        "facts": _build_onboard_review_context(review.entity_ulid),
        "allowed_decisions": ("approve", "reject"),
        "as_of_utc": now_iso8601_ms(),
    }


def resolve_onboard_admin_issue(
    *,
    review_request_ulid: str,
    decision: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> admin_v1.AdminInboxReceiptDTO | None:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()

    review = _get_review_request_or_raise(review_request_ulid)

    if review.closed_at_utc:
        return close_onboard_admin_issue(
            review_request_ulid=review.ulid,
            source_status=review.source_status,
            close_reason="already_terminal",
            admin_status="source_closed",
        )

    if decision == "approve":
        source_status = SOURCE_STATUS_APPROVED
        close_reason = "approved_in_resources"
        event_name = "resource.onboard_review.approved"
        _apply_onboard_approval(
            entity_ulid=review.entity_ulid,
            actor_ulid=act,
            request_id=rid,
        )
    elif decision == "reject":
        source_status = SOURCE_STATUS_REJECTED
        close_reason = "rejected_in_resources"
        event_name = "resource.onboard_review.rejected"
        _apply_onboard_rejection(
            entity_ulid=review.entity_ulid,
            actor_ulid=act,
            request_id=rid,
        )
    else:
        raise ValueError("decision must be 'approve' or 'reject'")

    _mark_review_request_terminal(
        review_request_ulid=review.ulid,
        source_status=source_status,
        actor_ulid=act,
        request_id=rid,
    )

    receipt = close_onboard_admin_issue(
        review_request_ulid=review.ulid,
        source_status=source_status,
        close_reason=close_reason,
        admin_status="resolved",
    )

    event_bus.emit(
        domain="resources",
        operation="admin_review_resolution",
        actor_ulid=act,
        target_ulid=review.entity_ulid,
        request_id=rid,
        happened_at_utc=now,
        changed={
            "fields": [
                "review_request_ulid",
                "review_kind",
                "source_status",
            ]
        },
        meta={
            "origin": "admin_review",
            "event_name": event_name,
            "admin_review_request_ulid": review.ulid,
        },
    )

    db.session.flush()
    return receipt


def close_onboard_admin_issue(
    *,
    review_request_ulid: str,
    source_status: str,
    close_reason: str,
    admin_status: str = "resolved",
) -> admin_v1.AdminInboxReceiptDTO | None:
    return admin_v1.close_inbox_item(
        admin_v1.AdminInboxCloseDTO(
            source_slice="resources",
            issue_kind=REVIEW_KIND_ONBOARD,
            source_ref_ulid=review_request_ulid,
            source_status=source_status,
            close_reason=close_reason,
            admin_status=admin_status,
        )
    )


# Temporary compatibility wrappers while callers are migrated.
def request_onboard_admin_review(
    *,
    entity_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> admin_v1.AdminInboxReceiptDTO:
    return raise_onboard_admin_issue(
        entity_ulid=entity_ulid,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def resolve_onboard_admin_review(
    *,
    review_request_ulid: str,
    approved: bool,
    actor_ulid: str | None,
    request_id: str | None,
) -> admin_v1.AdminInboxReceiptDTO | None:
    return resolve_onboard_admin_issue(
        review_request_ulid=review_request_ulid,
        decision="approve" if approved else "reject",
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


# -----------------
# Internal Helpers
# -----------------


def _create_onboard_review_request(
    *,
    entity_ulid: str,
    actor_ulid: str,
    request_id: str,
) -> ResourceAdminReviewRequest:
    now = now_iso8601_ms()

    review = ResourceAdminReviewRequest(
        entity_ulid=entity_ulid,
        review_kind=REVIEW_KIND_ONBOARD,
        source_status=SOURCE_STATUS_PENDING,
        requested_by_actor_ulid=actor_ulid,
        resolved_by_actor_ulid=None,
        request_id=request_id,
        title="Resource onboarding review required",
        summary=(
            "Admin review is required before resource onboarding is "
            "considered complete."
        ),
        created_at_utc=now,
        updated_at_utc=now,
        closed_at_utc=None,
    )
    db.session.add(review)
    db.session.flush()

    return review


def _get_review_request_or_raise(
    review_request_ulid: str,
) -> ResourceAdminReviewRequest:
    review = db.session.get(ResourceAdminReviewRequest, review_request_ulid)
    if not review:
        raise LookupError(
            "Resource admin review request not found: "
            f"{review_request_ulid}"
        )
    return review


def _build_onboard_review_context(entity_ulid: str) -> dict[str, Any]:
    """
    Build a non-PII context payload for Admin inbox display.
    """
    from . import onboard_services as wiz

    snap = wiz.review_snapshot(entity_ulid=entity_ulid)
    view = snap.get("view")
    pocs = snap.get("pocs") or []

    return {
        "entity_ulid": entity_ulid,
        "review_kind": REVIEW_KIND_ONBOARD,
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
    entity_ulid: str,
    actor_ulid: str,
    request_id: str | None,
) -> None:
    """
    Perform the real Resources-side approval/activation work here.
    """
    resource = _get_resource_or_raise(entity_ulid)
    now = now_iso8601_ms()

    # Keep these aligned with your actual Resource semantics.
    resource.readiness_status = "active"
    resource.admin_review_required = False

    if hasattr(resource, "last_touch_utc"):
        resource.last_touch_utc = now

    db.session.flush()


def _apply_onboard_rejection(
    *,
    entity_ulid: str,
    actor_ulid: str,
    request_id: str | None,
) -> None:
    """
    Keep the resource in a non-active posture and preserve the need for
    Admin review until corrected and resubmitted.
    """
    resource = _get_resource_or_raise(entity_ulid)
    now = now_iso8601_ms()

    # Keep these aligned with your actual Resource semantics.
    resource.readiness_status = "draft"
    resource.admin_review_required = True

    if hasattr(resource, "last_touch_utc"):
        resource.last_touch_utc = now

    db.session.flush()


def _mark_review_request_terminal(
    *,
    review_request_ulid: str,
    source_status: str,
    actor_ulid: str,
    request_id: str | None,
) -> None:
    review = _get_review_request_or_raise(review_request_ulid)
    now = now_iso8601_ms()

    review.source_status = source_status
    review.resolved_by_actor_ulid = actor_ulid
    review.request_id = request_id
    review.closed_at_utc = now
    review.updated_at_utc = now

    db.session.flush()


def _get_resource_or_raise(entity_ulid: str) -> Resource:
    resource = db.session.get(Resource, entity_ulid)
    if not resource:
        raise LookupError(f"Resource not found: {entity_ulid}")
    return resource
