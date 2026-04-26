# app/slices/customers/admin_issue_services.py

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
from app.lib.guards import (
    ensure_actor_ulid,
    ensure_entity_ulid,
    ensure_request_id,
)

from . import services as cust_svc
from .models import CustomerAdminIssue

REASON_CODE_ASSESSMENT_COMPLETED = "advisory_customers_assessment_completed"
REASON_CODE_WATCHLIST = "advisory_customers_watchlist"

SOURCE_STATUS_PENDING = "pending_review"
SOURCE_STATUS_APPROVED = "approved"
SOURCE_STATUS_REJECTED = "rejected"
SOURCE_STATUS_CANCELLED = "cancelled"


def raise_assessment_completed_admin_issue(
    *,
    entity_ulid: str,
    history_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> AdminAlertReceiptDTO:
    ent = ensure_entity_ulid(entity_ulid)
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    hid = str(history_ulid or "").strip()
    if not hid:
        raise ValueError("history_ulid is required")

    issue = _get_open_issue(
        request_id=rid,
        target_ulid=ent,
        reason_code=REASON_CODE_ASSESSMENT_COMPLETED,
    )
    if issue is None:
        detail = cust_svc.get_customer_history_detail_public(
            entity_ulid=ent,
            history_ulid=hid,
        )
        env = detail.parsed.envelope
        issue = _create_issue(
            target_ulid=ent,
            actor_ulid=act,
            request_id=rid,
            reason_code=REASON_CODE_ASSESSMENT_COMPLETED,
            title=env.title or "Customer assessment completed",
            summary=env.summary
            or "Customer assessment or reassessment completed.",
            details_json=_build_assessment_issue_context(
                entity_ulid=ent,
                history_ulid=hid,
            ),
        )

    receipt = upsert_alert(
        AdminAlertUpsertDTO(
            source_slice="customers",
            reason_code=issue.reason_code,
            request_id=str(issue.request_id),
            target_ulid=issue.target_ulid,
            title=issue.title,
            summary=issue.summary,
            source_status=issue.source_status,
            workflow_key="customers_assessment_completed_issue",
            resolution_target=AdminResolutionTargetDTO(
                route_name="customers.admin_issue_assessment_completed_get",
                route_params={"issue_ulid": issue.ulid},
                launch_label="Open customer assessment issue",
            ),
            context=_build_assessment_issue_context(
                entity_ulid=ent,
                history_ulid=hid,
            ),
        )
    )
    db.session.flush()
    return receipt


def raise_watchlist_admin_issue(
    *,
    entity_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> AdminAlertReceiptDTO:
    ent = ensure_entity_ulid(entity_ulid)
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)

    dash = cust_svc.get_customer_dashboard(ent)
    if not dash.watchlist:
        raise ValueError("customer is not watchlisted")

    issue = _get_open_issue(
        request_id=rid,
        target_ulid=ent,
        reason_code=REASON_CODE_WATCHLIST,
    )
    if issue is None:
        issue = _create_issue(
            target_ulid=ent,
            actor_ulid=act,
            request_id=rid,
            reason_code=REASON_CODE_WATCHLIST,
            title="Customer watchlist notice",
            summary=(
                "Customer is marked watchlist=True. "
                "Immediate Tier 1 needs follow-up may be required."
            ),
            details_json=_build_watchlist_issue_context(entity_ulid=ent),
        )

    receipt = upsert_alert(
        AdminAlertUpsertDTO(
            source_slice="customers",
            reason_code=issue.reason_code,
            request_id=str(issue.request_id),
            target_ulid=issue.target_ulid,
            title=issue.title,
            summary=issue.summary,
            source_status=issue.source_status,
            workflow_key="customers_watchlist_issue",
            resolution_target=AdminResolutionTargetDTO(
                route_name="customers.admin_issue_watchlist_get",
                route_params={"issue_ulid": issue.ulid},
                launch_label="Open customer watchlist issue",
            ),
            context=_build_watchlist_issue_context(entity_ulid=ent),
        )
    )
    db.session.flush()
    return receipt


def assessment_completed_issue_get(issue_ulid: str) -> dict[str, Any]:
    issue = _get_issue_or_raise(issue_ulid)
    return {
        "issue_ulid": issue.ulid,
        "request_id": issue.request_id,
        "target_ulid": issue.target_ulid,
        "reason_code": issue.reason_code,
        "source_status": issue.source_status,
        "title": issue.title,
        "summary": issue.summary,
        "facts": dict(issue.details_json or {}),
        "allowed_decisions": ("approve", "reject"),
        "as_of_utc": now_iso8601_ms(),
    }


def watchlist_issue_get(issue_ulid: str) -> dict[str, Any]:
    issue = _get_issue_or_raise(issue_ulid)
    return {
        "issue_ulid": issue.ulid,
        "request_id": issue.request_id,
        "target_ulid": issue.target_ulid,
        "reason_code": issue.reason_code,
        "source_status": issue.source_status,
        "title": issue.title,
        "summary": issue.summary,
        "facts": dict(issue.details_json or {}),
        "allowed_decisions": ("approve", "reject"),
        "as_of_utc": now_iso8601_ms(),
    }


def resolve_assessment_completed_admin_issue(
    *,
    issue_ulid: str,
    decision: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> AdminAlertReceiptDTO | None:
    return _resolve_issue(
        issue_ulid=issue_ulid,
        decision=decision,
        actor_ulid=actor_ulid,
        request_id=request_id,
        approved_event="customer.admin_issue.assessment_completed.approved",
        rejected_event="customer.admin_issue.assessment_completed.rejected",
        approved_close_reason="approved_in_customers",
        rejected_close_reason="rejected_in_customers",
    )


def resolve_watchlist_admin_issue(
    *,
    issue_ulid: str,
    decision: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> AdminAlertReceiptDTO | None:
    return _resolve_issue(
        issue_ulid=issue_ulid,
        decision=decision,
        actor_ulid=actor_ulid,
        request_id=request_id,
        approved_event="customer.admin_issue.watchlist.approved",
        rejected_event="customer.admin_issue.watchlist.rejected",
        approved_close_reason="approved_in_customers",
        rejected_close_reason="rejected_in_customers",
    )


def close_assessment_completed_admin_issue(
    *,
    issue_ulid: str,
    source_status: str,
    close_reason: str,
    admin_status: str = "resolved",
) -> AdminAlertReceiptDTO | None:
    return _close_issue(
        issue_ulid=issue_ulid,
        source_status=source_status,
        close_reason=close_reason,
        admin_status=admin_status,
    )


def close_watchlist_admin_issue(
    *,
    issue_ulid: str,
    source_status: str,
    close_reason: str,
    admin_status: str = "resolved",
) -> AdminAlertReceiptDTO | None:
    return _close_issue(
        issue_ulid=issue_ulid,
        source_status=source_status,
        close_reason=close_reason,
        admin_status=admin_status,
    )


# -----------------
# Internal helpers
# -----------------


def _get_open_issue(
    *,
    request_id: str,
    target_ulid: str,
    reason_code: str,
) -> CustomerAdminIssue | None:
    stmt = (
        select(CustomerAdminIssue)
        .where(
            CustomerAdminIssue.request_id == request_id,
            CustomerAdminIssue.target_ulid == target_ulid,
            CustomerAdminIssue.reason_code == reason_code,
            CustomerAdminIssue.closed_at_utc.is_(None),
        )
        .order_by(CustomerAdminIssue.created_at_utc.desc())
        .limit(1)
    )
    return db.session.execute(stmt).scalar_one_or_none()


def _create_issue(
    *,
    target_ulid: str,
    actor_ulid: str,
    request_id: str,
    reason_code: str,
    title: str,
    summary: str,
    details_json: dict[str, Any],
) -> CustomerAdminIssue:
    now = now_iso8601_ms()

    issue = CustomerAdminIssue(
        target_ulid=target_ulid,
        reason_code=reason_code,
        source_status=SOURCE_STATUS_PENDING,
        requested_by_actor_ulid=actor_ulid,
        resolved_by_actor_ulid=None,
        request_id=request_id,
        title=title,
        summary=summary,
        details_json=details_json,
        created_at_utc=now,
        updated_at_utc=now,
        closed_at_utc=None,
    )
    db.session.add(issue)
    db.session.flush()
    return issue


def _get_issue_or_raise(issue_ulid: str) -> CustomerAdminIssue:
    issue = db.session.get(CustomerAdminIssue, issue_ulid)
    if not issue:
        raise LookupError(f"Customer admin issue not found: {issue_ulid}")
    return issue


def _build_assessment_issue_context(
    *,
    entity_ulid: str,
    history_ulid: str,
) -> dict[str, Any]:
    dash = cust_svc.get_customer_dashboard(entity_ulid)
    detail = cust_svc.get_customer_history_detail_public(
        entity_ulid=entity_ulid,
        history_ulid=history_ulid,
    )

    return {
        "target_ulid": entity_ulid,
        "history_ulid": history_ulid,
        "history_kind": detail.kind,
        "status": dash.status,
        "intake_step": dash.intake_step,
        "watchlist": bool(dash.watchlist),
        "assessment_version": int(dash.assessment_version),
        "tier1_unlocked": bool(dash.tier1_unlocked),
        "tier2_unlocked": bool(dash.tier2_unlocked),
        "tier3_unlocked": bool(dash.tier3_unlocked),
    }


def _build_watchlist_issue_context(
    *,
    entity_ulid: str,
) -> dict[str, Any]:
    dash = cust_svc.get_customer_dashboard(entity_ulid)
    elig = cust_svc.get_customer_eligibility(entity_ulid)

    return {
        "target_ulid": entity_ulid,
        "status": dash.status,
        "intake_step": dash.intake_step,
        "watchlist": bool(dash.watchlist),
        "veteran_status": elig.veteran_status,
        "housing_status": elig.housing_status,
        "assessment_version": int(dash.assessment_version),
        "tier1_min": dash.tier1_min,
        "tier2_min": dash.tier2_min,
        "tier3_min": dash.tier3_min,
        "flag_tier1_immediate": bool(dash.flag_tier1_immediate),
    }


def _resolve_issue(
    *,
    issue_ulid: str,
    decision: str,
    actor_ulid: str | None,
    request_id: str | None,
    approved_event: str,
    rejected_event: str,
    approved_close_reason: str,
    rejected_close_reason: str,
) -> AdminAlertReceiptDTO | None:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()

    issue = _get_issue_or_raise(issue_ulid)

    if issue.closed_at_utc:
        return _close_issue(
            issue_ulid=issue.ulid,
            source_status=issue.source_status,
            close_reason="already_terminal",
            admin_status="source_closed",
        )

    if decision == "approve":
        source_status = SOURCE_STATUS_APPROVED
        close_reason = approved_close_reason
        event_name = approved_event
    elif decision == "reject":
        source_status = SOURCE_STATUS_REJECTED
        close_reason = rejected_close_reason
        event_name = rejected_event
    else:
        raise ValueError("decision must be 'approve' or 'reject'")

    _mark_issue_terminal(
        issue_ulid=issue.ulid,
        source_status=source_status,
        actor_ulid=act,
        request_id=rid,
    )

    receipt = _close_issue(
        issue_ulid=issue.ulid,
        source_status=source_status,
        close_reason=close_reason,
        admin_status="resolved",
    )

    event_bus.emit(
        domain="customers",
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
            "customer_admin_issue_ulid": issue.ulid,
        },
    )

    db.session.flush()
    return receipt


def _close_issue(
    *,
    issue_ulid: str,
    source_status: str,
    close_reason: str,
    admin_status: str = "resolved",
) -> AdminAlertReceiptDTO | None:
    issue = _get_issue_or_raise(issue_ulid)
    if not issue.request_id:
        raise ValueError(
            "CustomerAdminIssue.request_id is required to close admin alert"
        )

    return close_alert(
        AdminAlertCloseDTO(
            source_slice="customers",
            reason_code=issue.reason_code,
            request_id=issue.request_id,
            target_ulid=issue.target_ulid,
            source_status=source_status,
            close_reason=close_reason,
            admin_status=admin_status,
        )
    )


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
