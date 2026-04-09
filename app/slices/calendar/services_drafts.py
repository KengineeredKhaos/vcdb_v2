# app/slices/calendar/services_draft.py

"""Calendar demand-draft services.

Drafts are the pre-publish ask artifacts.
They must point to a locked budget snapshot.
They promote into published FundingDemand rows.

No commit/rollback here; routes own the transaction boundary.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.extensions import db, event_bus
from app.extensions.contracts import governance_v2 as gov
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid

from .models import DemandDraft, FundingDemand, Project, ProjectBudgetSnapshot
from .services_funding import build_canonical_published_context_payload
from .taxonomy import DEMAND_DRAFT_STATUSES, FUNDING_DEMAND_STATUSES

_ALLOWED_DRAFT_STATUSES = set(DEMAND_DRAFT_STATUSES)
_ALLOWED_FUNDING_STATUSES = set(FUNDING_DEMAND_STATUSES)
_EDITABLE_DRAFT_STATUSES = {"draft", "returned_for_revision"}


def _require_ulid(name: str, value: str | None) -> str:
    text = str(value or "").strip()
    if len(text) != 26:
        raise ValueError(f"{name} must be a 26-char ULID")
    return text


def _clean_text(
    value: str | None, *, default: str | None = None
) -> str | None:
    text = str(value or "").strip()
    if text:
        return text
    return default


def _normalize_money(value: int | None, *, field: str) -> int:
    cents = int(value or 0)
    if cents < 0:
        raise ValueError(f"{field} must be >= 0")
    return cents


def _normalize_tags(
    raw: str | list[str] | tuple[str, ...] | None
) -> list[str]:
    if raw is None:
        return []
    parts: list[str]
    if isinstance(raw, str):
        parts = [x.strip() for x in raw.split(",")]
    else:
        parts = [str(x).strip() for x in raw]

    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part or part in seen:
            continue
        seen.add(part)
        out.append(part)
    return out


def _get_project_or_raise(project_ulid: str) -> Project:
    _require_ulid("project_ulid", project_ulid)
    row = db.session.execute(
        select(Project).where(Project.ulid == project_ulid)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"project not found: {project_ulid}")
    return row


def _get_snapshot_or_raise(snapshot_ulid: str) -> ProjectBudgetSnapshot:
    _require_ulid("snapshot_ulid", snapshot_ulid)
    row = db.session.execute(
        select(ProjectBudgetSnapshot).where(
            ProjectBudgetSnapshot.ulid == snapshot_ulid
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"budget snapshot not found: {snapshot_ulid}")
    return row


def _get_draft_or_raise(draft_ulid: str) -> DemandDraft:
    _require_ulid("draft_ulid", draft_ulid)
    row = db.session.execute(
        select(DemandDraft).where(DemandDraft.ulid == draft_ulid)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"demand draft not found: {draft_ulid}")
    return row


def _require_locked_snapshot(snapshot: ProjectBudgetSnapshot) -> None:
    if not bool(snapshot.is_locked):
        raise RuntimeError("demand draft requires a locked budget snapshot")


def _require_draft_status(row: DemandDraft, allowed: set[str]) -> None:
    status = str(row.status or "").strip()
    if status not in allowed:
        names = ", ".join(sorted(allowed))
        raise RuntimeError(f"demand draft must be in one of: {names}")


def _validate_semantics(
    *,
    spending_class: str | None,
    source_profile_key: str | None,
    eligible_fund_codes: list[str] | tuple[str, ...] | None = None,
) -> None:
    if spending_class:
        res = gov.validate_semantic_keys(
            spending_class=str(spending_class),
            demand_eligible_fund_codes=tuple(eligible_fund_codes or ()),
        )
        if not res.ok:
            raise ValueError(
                "; ".join(res.errors) or "invalid spending_class"
            )

    if source_profile_key:
        gov.get_funding_source_profile_summary(str(source_profile_key))


def _emit(
    *,
    operation: str,
    actor_ulid: str,
    target_ulid: str,
    request_id: str | None = None,
    happened_at_utc: str | None = None,
    refs: dict[str, Any] | None = None,
    changed: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    event_bus.emit(
        domain="calendar",
        operation=operation,
        request_id=request_id or new_ulid(),
        actor_ulid=actor_ulid,
        target_ulid=target_ulid,
        happened_at_utc=happened_at_utc or now_iso8601_ms(),
        refs=refs or {},
        changed=changed or {},
        meta=meta or {},
    )


def demand_draft_view(draft_ulid: str) -> dict[str, Any]:
    row = _get_draft_or_raise(draft_ulid)
    return {
        "ulid": row.ulid,
        "project_ulid": row.project_ulid,
        "budget_snapshot_ulid": row.budget_snapshot_ulid,
        "status": row.status,
        "title": row.title,
        "summary": row.summary,
        "scope_summary": row.scope_summary,
        "requested_amount_cents": int(row.requested_amount_cents or 0),
        "deadline_date": row.deadline_date,
        "spending_class_candidate": row.spending_class_candidate,
        "source_profile_key": row.source_profile_key,
        "ops_support_planned": row.ops_support_planned,
        "tag_any": list(row.tag_any_json or ()),
        "governance_note": row.governance_note,
        "approved_semantics_json": row.approved_semantics_json,
        "ready_for_review_at_utc": row.ready_for_review_at_utc,
        "review_decided_at_utc": row.review_decided_at_utc,
        "approved_for_publish_at_utc": row.approved_for_publish_at_utc,
        "promoted_at_utc": row.promoted_at_utc,
        "created_at_utc": row.created_at_utc,
        "updated_at_utc": row.updated_at_utc,
    }


def list_demand_drafts(project_ulid: str) -> list[dict[str, Any]]:
    _get_project_or_raise(project_ulid)
    rows = db.session.execute(
        select(DemandDraft)
        .where(DemandDraft.project_ulid == project_ulid)
        .order_by(DemandDraft.created_at_utc.desc())
    ).scalars()
    return [demand_draft_view(row.ulid) for row in rows]


def create_draft_from_snapshot(
    *,
    project_ulid: str,
    snapshot_ulid: str,
    actor_ulid: str,
    title: str,
    summary: str | None = None,
    scope_summary: str | None = None,
    requested_amount_cents: int | None = None,
    deadline_date: str | None = None,
    spending_class_candidate: str | None = None,
    source_profile_key: str | None = None,
    ops_support_planned: bool | None = None,
    tag_any: str | list[str] | tuple[str, ...] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    project = _get_project_or_raise(project_ulid)
    snapshot = _get_snapshot_or_raise(snapshot_ulid)
    _require_ulid("actor_ulid", actor_ulid)

    if snapshot.project_ulid != project.ulid:
        raise RuntimeError("snapshot belongs to another project")
    _require_locked_snapshot(snapshot)

    clean_title = _clean_text(title)
    if not clean_title:
        raise ValueError("title is required")

    final_amount = (
        int(snapshot.net_need_cents or 0)
        if requested_amount_cents is None
        else _normalize_money(
            requested_amount_cents,
            field="requested_amount_cents",
        )
    )
    final_source_profile_key = (
        _clean_text(source_profile_key)
        if source_profile_key is not None
        else _clean_text(getattr(project, "funding_profile_key", None))
    )
    final_tags = _normalize_tags(tag_any)
    final_spending_class = _clean_text(spending_class_candidate)

    _validate_semantics(
        spending_class=final_spending_class,
        source_profile_key=final_source_profile_key,
    )

    row = DemandDraft(
        project_ulid=project.ulid,
        budget_snapshot_ulid=snapshot.ulid,
        status="draft",
        title=clean_title,
        summary=_clean_text(summary),
        scope_summary=(
            _clean_text(scope_summary)
            if scope_summary is not None
            else _clean_text(snapshot.scope_summary)
        ),
        requested_amount_cents=final_amount,
        deadline_date=_clean_text(deadline_date),
        spending_class_candidate=final_spending_class,
        source_profile_key=final_source_profile_key,
        ops_support_planned=ops_support_planned,
        tag_any_json=final_tags,
        governance_note=None,
        approved_semantics_json=None,
        ready_for_review_at_utc=None,
        review_decided_at_utc=None,
        approved_for_publish_at_utc=None,
        promoted_at_utc=None,
    )
    db.session.add(row)
    db.session.flush()

    _emit(
        operation="demand_draft_created",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=row.created_at_utc,
        refs={
            "project_ulid": project.ulid,
            "budget_snapshot_ulid": snapshot.ulid,
        },
        changed={
            "fields": [
                "status",
                "title",
                "requested_amount_cents",
                "deadline_date",
                "spending_class_candidate",
                "source_profile_key",
                "ops_support_planned",
                "tag_any_json",
            ]
        },
    )
    return demand_draft_view(row.ulid)


def update_draft(
    *,
    draft_ulid: str,
    actor_ulid: str,
    title: str | None = None,
    summary: str | None = None,
    scope_summary: str | None = None,
    requested_amount_cents: int | None = None,
    deadline_date: str | None = None,
    spending_class_candidate: str | None = None,
    source_profile_key: str | None = None,
    ops_support_planned: bool | None = None,
    tag_any: str | list[str] | tuple[str, ...] | None = None,
    governance_note: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    row = _get_draft_or_raise(draft_ulid)
    project = _get_project_or_raise(row.project_ulid)
    snapshot = _get_snapshot_or_raise(row.budget_snapshot_ulid)
    _require_ulid("actor_ulid", actor_ulid)
    _require_locked_snapshot(snapshot)
    _require_draft_status(row, _EDITABLE_DRAFT_STATUSES)

    changed_fields: list[str] = []

    if title is not None:
        clean_title = _clean_text(title)
        if not clean_title:
            raise ValueError("title cannot be blank")
        row.title = clean_title
        changed_fields.append("title")

    if summary is not None:
        row.summary = _clean_text(summary)
        changed_fields.append("summary")

    if scope_summary is not None:
        row.scope_summary = _clean_text(scope_summary)
        changed_fields.append("scope_summary")

    if requested_amount_cents is not None:
        row.requested_amount_cents = _normalize_money(
            requested_amount_cents,
            field="requested_amount_cents",
        )
        changed_fields.append("requested_amount_cents")

    if deadline_date is not None:
        row.deadline_date = _clean_text(deadline_date)
        changed_fields.append("deadline_date")

    if spending_class_candidate is not None:
        row.spending_class_candidate = _clean_text(spending_class_candidate)
        changed_fields.append("spending_class_candidate")

    if source_profile_key is not None:
        row.source_profile_key = _clean_text(source_profile_key)
        changed_fields.append("source_profile_key")

    if ops_support_planned is not None:
        row.ops_support_planned = bool(ops_support_planned)
        changed_fields.append("ops_support_planned")

    if tag_any is not None:
        row.tag_any_json = _normalize_tags(tag_any)
        changed_fields.append("tag_any_json")

    if governance_note is not None:
        row.governance_note = _clean_text(governance_note)
        changed_fields.append("governance_note")

    _validate_semantics(
        spending_class=row.spending_class_candidate,
        source_profile_key=row.source_profile_key,
    )
    db.session.flush()

    _emit(
        operation="demand_draft_updated",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "project_ulid": project.ulid,
            "budget_snapshot_ulid": snapshot.ulid,
        },
        changed={"fields": changed_fields},
    )
    return demand_draft_view(row.ulid)


def mark_draft_ready_for_review(
    *,
    draft_ulid: str,
    actor_ulid: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    row = _get_draft_or_raise(draft_ulid)
    _require_ulid("actor_ulid", actor_ulid)
    _require_draft_status(row, {"draft", "returned_for_revision"})

    row.status = "ready_for_review"
    row.ready_for_review_at_utc = now_iso8601_ms()
    db.session.flush()

    _emit(
        operation="demand_draft_ready_for_review",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=row.ready_for_review_at_utc,
        refs={
            "project_ulid": row.project_ulid,
            "budget_snapshot_ulid": row.budget_snapshot_ulid,
        },
        changed={"fields": ["status", "ready_for_review_at_utc"]},
    )
    return demand_draft_view(row.ulid)


def submit_draft_for_governance_review(
    *,
    draft_ulid: str,
    actor_ulid: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    row = _get_draft_or_raise(draft_ulid)
    _require_ulid("actor_ulid", actor_ulid)
    _require_draft_status(row, {"ready_for_review"})

    if not _clean_text(row.title):
        raise RuntimeError("draft title is required before governance review")
    if int(row.requested_amount_cents or 0) < 0:
        raise RuntimeError("draft requested_amount_cents is invalid")

    _validate_semantics(
        spending_class=row.spending_class_candidate,
        source_profile_key=row.source_profile_key,
    )

    row.status = "governance_review_pending"
    db.session.flush()

    _emit(
        operation="demand_draft_submitted_for_review",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "project_ulid": row.project_ulid,
            "budget_snapshot_ulid": row.budget_snapshot_ulid,
        },
        changed={"fields": ["status"]},
    )
    return demand_draft_view(row.ulid)


def return_draft_for_revision(
    *,
    draft_ulid: str,
    actor_ulid: str,
    note: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    row = _get_draft_or_raise(draft_ulid)
    _require_ulid("actor_ulid", actor_ulid)
    _require_draft_status(row, {"governance_review_pending"})

    clean_note = _clean_text(note)
    if not clean_note:
        raise ValueError(
            "note is required when returning a draft for revision"
        )

    row.status = "returned_for_revision"
    row.governance_note = clean_note
    row.review_decided_at_utc = now_iso8601_ms()
    row.approved_for_publish_at_utc = None
    row.approved_semantics_json = None
    db.session.flush()

    _emit(
        operation="demand_draft_returned_for_revision",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=row.review_decided_at_utc,
        refs={
            "project_ulid": row.project_ulid,
            "budget_snapshot_ulid": row.budget_snapshot_ulid,
        },
        changed={
            "fields": [
                "status",
                "governance_note",
                "review_decided_at_utc",
            ]
        },
    )
    return demand_draft_view(row.ulid)


def _build_governance_review_request(
    row: DemandDraft,
    *,
    overrides: dict[str, Any] | None = None,
) -> gov.GovernanceReviewRequestDTO:
    raw = dict(overrides or {})

    spending_class = _clean_text(
        raw.get("spending_class_candidate"),
        default=row.spending_class_candidate,
    )
    source_profile_key = _clean_text(
        raw.get("source_profile_key_candidate"),
        default=row.source_profile_key,
    )
    tag_any = _normalize_tags(raw.get("tag_any") or row.tag_any_json)

    return gov.GovernanceReviewRequestDTO(
        demand_draft_ulid=row.ulid,
        project_ulid=row.project_ulid,
        budget_snapshot_ulid=row.budget_snapshot_ulid,
        requested_amount_cents=int(row.requested_amount_cents or 0),
        title=str(row.title or "").strip(),
        summary=_clean_text(row.summary),
        scope_summary=_clean_text(row.scope_summary),
        needed_by_date=_clean_text(row.deadline_date),
        source_profile_key_candidate=source_profile_key,
        ops_support_planned=row.ops_support_planned,
        spending_class_candidate=spending_class,
        tag_any=tuple(tag_any),
    )


def _governance_decision_to_json(
    decision: gov.GovernanceReviewDecisionDTO,
) -> dict[str, Any]:
    return {
        "decision": decision.decision,
        "governance_note": decision.governance_note,
        "approved_spending_class": decision.approved_spending_class,
        "approved_source_profile_key": (decision.approved_source_profile_key),
        "eligible_fund_codes": list(decision.eligible_fund_codes or ()),
        "default_restriction_keys": list(
            decision.default_restriction_keys or ()
        ),
        "approved_tag_any": list(decision.approved_tag_any or ()),
        "decision_fingerprint": decision.decision_fingerprint,
        "validation_errors": list(decision.validation_errors or ()),
        "reason_codes": list(decision.reason_codes or ()),
        "matched_rule_ids": list(decision.matched_rule_ids or ()),
    }


def approve_draft_for_publish(
    *,
    draft_ulid: str,
    actor_ulid: str,
    review_overrides: dict[str, Any] | None = None,
    governance_decision: gov.GovernanceReviewDecisionDTO | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    row = _get_draft_or_raise(draft_ulid)
    _require_ulid("actor_ulid", actor_ulid)
    _require_draft_status(row, {"governance_review_pending"})

    review_req = _build_governance_review_request(
        row,
        overrides=review_overrides,
    )
    decision = governance_decision or gov.review_calendar_demand(review_req)

    if decision.decision != "approved":
        note = str(decision.governance_note or "").strip()
        errs = "; ".join(decision.validation_errors or ())
        message = note or "Governance did not approve the draft."
        if errs:
            message = f"{message} {errs}"
        raise RuntimeError(message)

    spending_class = (
        decision.approved_spending_class
        or review_req.spending_class_candidate
        or row.spending_class_candidate
    )
    source_profile_key = (
        decision.approved_source_profile_key
        or review_req.source_profile_key_candidate
        or row.source_profile_key
    )
    eligible_fund_codes = list(decision.eligible_fund_codes or ())
    default_restriction_keys = list(decision.default_restriction_keys or ())
    approved_tag_any = _normalize_tags(
        decision.approved_tag_any or review_req.tag_any or row.tag_any_json
    )

    _validate_semantics(
        spending_class=spending_class,
        source_profile_key=source_profile_key,
        eligible_fund_codes=eligible_fund_codes,
    )

    row.status = "approved_for_publish"
    row.governance_note = _clean_text(decision.governance_note)
    row.review_decided_at_utc = now_iso8601_ms()
    row.approved_for_publish_at_utc = row.review_decided_at_utc
    row.approved_semantics_json = _governance_decision_to_json(decision)
    db.session.flush()

    _emit(
        operation="demand_draft_approved_for_publish",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=row.approved_for_publish_at_utc,
        refs={
            "project_ulid": row.project_ulid,
            "budget_snapshot_ulid": row.budget_snapshot_ulid,
        },
        changed={
            "fields": [
                "status",
                "governance_note",
                "review_decided_at_utc",
                "approved_for_publish_at_utc",
                "approved_semantics_json",
            ]
        },
    )
    return demand_draft_view(row.ulid)


def promote_draft_to_funding_demand(
    *,
    draft_ulid: str,
    actor_ulid: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    row = _get_draft_or_raise(draft_ulid)
    project = _get_project_or_raise(row.project_ulid)
    snapshot = _get_snapshot_or_raise(row.budget_snapshot_ulid)
    _require_ulid("actor_ulid", actor_ulid)
    _require_draft_status(row, {"approved_for_publish"})
    _require_locked_snapshot(snapshot)

    existing = db.session.execute(
        select(FundingDemand).where(
            FundingDemand.origin_draft_ulid == row.ulid
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise RuntimeError("draft has already been promoted")

    approved = dict(row.approved_semantics_json or {})
    spending_class = (
        approved.get("approved_spending_class")
        or row.spending_class_candidate
    )
    eligible_fund_codes = list(approved.get("eligible_fund_codes") or ())
    source_profile_key = (
        approved.get("approved_source_profile_key") or row.source_profile_key
    )
    tag_any = _normalize_tags(
        approved.get("approved_tag_any") or row.tag_any_json
    )

    _validate_semantics(
        spending_class=spending_class,
        source_profile_key=source_profile_key,
        eligible_fund_codes=eligible_fund_codes,
    )

    if "published" not in _ALLOWED_FUNDING_STATUSES:
        raise RuntimeError("funding demand taxonomy is missing 'published'")

    published_at_utc = now_iso8601_ms()
    published_context_json = build_canonical_published_context_payload(
        funding_demand_ulid=new_ulid(),
        project_ulid=project.ulid,
        project_title=getattr(project, "project_title", None),
        title=row.title,
        status="published",
        goal_cents=int(row.requested_amount_cents or 0),
        deadline_date=row.deadline_date,
        published_at_utc=published_at_utc,
        demand_draft_ulid=row.ulid,
        budget_snapshot_ulid=snapshot.ulid,
        summary=row.summary,
        scope_summary=row.scope_summary,
        source_profile_key=source_profile_key,
        ops_support_planned=row.ops_support_planned,
        spending_class=spending_class,
        tag_any=tag_any,
        eligible_fund_codes=eligible_fund_codes,
        default_restriction_keys=list(
            approved.get("default_restriction_keys") or ()
        ),
        decision_fingerprint=approved.get("decision_fingerprint"),
        approved_tag_any=approved.get("approved_tag_any") or tag_any,
    )

    funding_demand = FundingDemand(
        ulid=published_context_json["demand"]["funding_demand_ulid"],
        project_ulid=project.ulid,
        origin_draft_ulid=row.ulid,
        title=row.title,
        status="published",
        goal_cents=int(row.requested_amount_cents or 0),
        deadline_date=row.deadline_date,
        spending_class=spending_class,
        eligible_fund_codes_json=eligible_fund_codes,
        tag_any_json=tag_any,
        published_at_utc=published_at_utc,
        closed_at_utc=None,
        published_context_json=published_context_json,
    )
    db.session.add(funding_demand)
    row.promoted_at_utc = published_at_utc
    db.session.flush()

    _emit(
        operation="demand_draft_promoted",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=row.promoted_at_utc,
        refs={
            "project_ulid": project.ulid,
            "budget_snapshot_ulid": snapshot.ulid,
            "funding_demand_ulid": funding_demand.ulid,
        },
        changed={
            "fields": [
                "promoted_at_utc",
                "funding_demand.origin_draft_ulid",
                "funding_demand.status",
            ]
        },
    )
    return {
        "demand_draft": demand_draft_view(row.ulid),
        "funding_demand": {
            "funding_demand_ulid": funding_demand.ulid,
            "project_ulid": funding_demand.project_ulid,
            "title": funding_demand.title,
            "status": funding_demand.status,
            "goal_cents": int(funding_demand.goal_cents or 0),
            "deadline_date": funding_demand.deadline_date,
            "eligible_fund_codes": list(
                funding_demand.eligible_fund_codes_json or ()
            ),
            "published_at_utc": funding_demand.published_at_utc,
        },
    }


__all__ = [
    "approve_draft_for_publish",
    "create_draft_from_snapshot",
    "demand_draft_view",
    "list_demand_drafts",
    "mark_draft_ready_for_review",
    "promote_draft_to_funding_demand",
    "return_draft_for_revision",
    "submit_draft_for_governance_review",
    "update_draft",
]
