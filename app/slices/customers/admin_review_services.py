# app/slices/customers/admin_review_services.py
from __future__ import annotations

from typing import Any

from app.extensions import db
from app.extensions.contracts import admin_v1
from app.lib.guards import (
    ensure_actor_ulid,
    ensure_entity_ulid,
    ensure_request_id,
)

from . import services as cust_svc

ISSUE_KIND_WATCHLIST_NOTICE = "customer_watchlist_notice"
ISSUE_KIND_ASSESSMENT_COMPLETED_NOTICE = (
    "customer_assessment_completed_notice"
)

SOURCE_STATUS_ADVISORY_OPEN = "advisory_open"
WORKFLOW_KEY_CUSTOMER_ADVISORY = "customer_advisory"


def publish_assessment_completed_admin_advisory(
    *,
    entity_ulid: str,
    history_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> admin_v1.AdminInboxReceiptDTO:
    ent = ensure_entity_ulid(entity_ulid)
    hid = str(history_ulid or "").strip()
    if not hid:
        raise ValueError("history_ulid is required")

    ensure_request_id(request_id)
    ensure_actor_ulid(actor_ulid)

    dash = cust_svc.get_customer_dashboard(ent)
    detail = cust_svc.get_customer_history_detail_public(
        entity_ulid=ent,
        history_ulid=hid,
    )
    env = detail.parsed.envelope

    receipt = admin_v1.upsert_inbox_item(
        admin_v1.AdminInboxUpsertDTO(
            source_slice="customers",
            issue_kind=ISSUE_KIND_ASSESSMENT_COMPLETED_NOTICE,
            source_ref_ulid=hid,
            subject_ref_ulid=ent,
            severity="medium" if dash.watchlist else "low",
            title=env.title or "Customer assessment completed",
            summary=env.summary
            or "Customer assessment or reassessment completed.",
            source_status=SOURCE_STATUS_ADVISORY_OPEN,
            workflow_key=WORKFLOW_KEY_CUSTOMER_ADVISORY,
            resolution_route=f"/customers/{ent}/history/{hid}",
            context=_build_assessment_advisory_context(
                entity_ulid=ent,
                history_ulid=hid,
            ),
        )
    )
    db.session.flush()
    return receipt


def publish_watchlist_admin_advisory(
    *,
    entity_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
    source_ref_ulid: str | None = None,
) -> admin_v1.AdminInboxReceiptDTO:
    ent = ensure_entity_ulid(entity_ulid)
    ensure_request_id(request_id)
    ensure_actor_ulid(actor_ulid)

    dash = cust_svc.get_customer_dashboard(ent)
    if not dash.watchlist:
        raise ValueError("customer is not watchlisted")

    source_ref = str(source_ref_ulid or ent).strip()

    receipt = admin_v1.upsert_inbox_item(
        admin_v1.AdminInboxUpsertDTO(
            source_slice="customers",
            issue_kind=ISSUE_KIND_WATCHLIST_NOTICE,
            source_ref_ulid=source_ref,
            subject_ref_ulid=ent,
            severity="medium",
            title="Customer watchlist notice",
            summary=(
                "Customer is marked watchlist=True. " "QC/QA awareness only."
            ),
            source_status=SOURCE_STATUS_ADVISORY_OPEN,
            workflow_key=WORKFLOW_KEY_CUSTOMER_ADVISORY,
            resolution_route=f"/customers/{ent}",
            context=_build_watchlist_advisory_context(entity_ulid=ent),
        )
    )
    db.session.flush()
    return receipt


def _build_assessment_advisory_context(
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
        "entity_ulid": entity_ulid,
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


def _build_watchlist_advisory_context(
    *,
    entity_ulid: str,
) -> dict[str, Any]:
    dash = cust_svc.get_customer_dashboard(entity_ulid)
    elig = cust_svc.get_customer_eligibility(entity_ulid)

    return {
        "entity_ulid": entity_ulid,
        "status": dash.status,
        "intake_step": dash.intake_step,
        "watchlist": bool(dash.watchlist),
        "veteran_status": elig.veteran_status,
        "housing_status": elig.housing_status,
        "assessment_version": int(dash.assessment_version),
        "tier1_min": dash.tier1_min,
        "tier2_min": dash.tier2_min,
        "tier3_min": dash.tier3_min,
    }
