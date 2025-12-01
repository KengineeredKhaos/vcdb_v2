# app/slices/logistics/issuance_services.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy import select

from app.extensions import db, enforcers, event_bus
from app.extensions.contracts import governance_v2
from app.extensions.policies import load_policy, load_policy_sku_constraints
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.lib.jsonutil import pretty_dumps
from app.slices.logistics.sku import (
    classification_key_for,
    parse_sku,
    validate_sku,
)

from .models import (
    InventoryBatch,
    InventoryItem,
    Issue,
)
from .services import (
    attach_issue_decision,
    issue_inventory_lowlevel,
)

_SKU_POLICY = load_policy_sku_constraints()
_ALLOWED_UNITS = set(_SKU_POLICY.get("allowed_units") or [])
_ALLOWED_SOURCES = set(_SKU_POLICY.get("allowed_sources") or [])


@dataclass
class IssueContext:
    """
    DTO used as a shared context for issuance-related checks:
    calendar enforcers and governance_v2.decide_issue.

    It only carries data (no behavior) and can be safely serialized
    to JSON if needed.
    """

    customer_ulid: str
    sku_code: Optional[str]
    classification_key: Optional[str]
    when_iso: str
    project_ulid: Optional[str]
    sku_parts: Optional[Dict[str, Any]] = None
    cost_cents: Optional[int] = None
    force_blackout: bool = False  # harmless if not used


@dataclass(frozen=True)
class IssueResult:
    """
    Lightweight result DTO for policy-only issuances and
    CLI/reporting surfaces.
    """

    ok: bool
    reason: str
    issue_ulid: Optional[str] = None
    decision: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None


def issue_inventory(
    customer_ulid: str,
    sku_code: str,
    *,
    when_iso: str | None = None,
    project_ulid: str | None = None,
    quantity: int = 1,
    actor_ulid: str | None = None,
    location_ulid: str | None = None,
    batch_ulid: str | None = None,
) -> dict:
    """
    Canonical issuance surface.
    Delegates to decide_and_issue_one and returns its dict:
    {'ok', 'reason', 'movement_ulid'?, 'issue_ulid'?, 'decision': {...}, ...}
    """
    return decide_and_issue_one(
        customer_ulid=customer_ulid,
        sku_code=sku_code,
        quantity=quantity,
        when_iso=when_iso,
        project_ulid=project_ulid,
        actor_ulid=actor_ulid,
        location_ulid=location_ulid,
        batch_ulid=batch_ulid,
    )


# -----------------
# Issue (high-level):
# enforcer → policy → resolve batch → low-level issue → attach decision
# -----------------

# FLOW: issuance — enforcer + governance + stock + ledger


def decide_and_issue_one(
    *,
    customer_ulid: str,
    sku_code: str,
    quantity: int = 1,
    when_iso: str | None = None,
    project_ulid: str | None = None,
    actor_ulid: str | None = None,
    location_ulid: str,  # where stock will be pulled from
    batch_ulid: str | None = None,  # optional: choose a specific batch
    request_id: str | None = None,  # correlation id for ledger/event_bus
) -> dict:
    """
    End-to-end issuance that gates on blackout + policy,
    locates stock, performs the low-level issue,
    and stores the decision trace.

    High-level "one-shot" issuance:
      - Calendar blackout (fast gate)
      - Policy decision (Governance)
      - Resolve item/batch
      - Call low-level issue_inventory_lowlevel(...)
      - Persist decision_json on Issue

    Returns a dict:
      {ok, reason, decision, movement_ulid?, request_id}
    """
    as_of = when_iso or now_iso8601_ms()
    req_id = request_id or new_ulid()

    # derive classification key from SKU once
    parts = parse_sku(sku_code)
    classification_key = classification_key_for(parts)

    def _emit(
        operation: str,
        reason: str,
        decision_payload: dict | None = None,
        stage: str | None = None,
        refs_extra: dict | None = None,
    ) -> None:
        """Helper to emit a single logistics issuance ledger event."""
        refs = {
            "sku_code": sku_code,
            "location_ulid": location_ulid,
            "project_ulid": project_ulid,
        }
        if refs_extra:
            refs.update(refs_extra)

        meta = {
            "stage": stage,
            "reason": reason,
        }
        if decision_payload is not None:
            meta["decision"] = decision_payload

        event_bus.emit(
            domain="logistics",
            operation=operation,
            request_id=req_id,
            actor_ulid=actor_ulid,
            target_ulid=customer_ulid,  # subject: the customer
            refs=refs,
            changed={"quantity": quantity},
            meta=meta,
            happened_at_utc=as_of,
            chain_key="logistics",
        )

    # 1) Enforcer: calendar blackout quick gate
    enforcer_ctx = type(
        "IssueContext",
        (),
        {
            "customer_ulid": customer_ulid,
            "sku_code": sku_code,
            "classification_key": classification_key,
            "sku_parts": parts,
            "when_iso": as_of,
            "project_ulid": project_ulid,
        },
    )
    ok, meta = enforcers.calendar_blackout_ok(enforcer_ctx)
    if not ok:
        decision = {
            "ok": False,
            "reason": meta.get("reason", "calendar_blackout"),
            "enforcer": meta,
            "policy": None,
        }
        _emit(
            operation="issue.denied",
            reason=decision["reason"],
            decision_payload=decision,
            stage="enforcer",
        )
        return {
            "ok": False,
            "reason": decision["reason"],
            "decision": decision,
            "request_id": req_id,
        }

    # 2) Governance policy decision
    gov_ctx = type(
        "IssueContext",
        (),
        {
            "customer_ulid": customer_ulid,
            "sku_code": sku_code,
            "classification_key": classification_key,
            "sku_parts": parts,
            "when_iso": as_of,
            "project_ulid": project_ulid,
        },
    )
    dec = governance_v2.decide_issue(gov_ctx)

    decision = {
        "ok": bool(getattr(dec, "allowed", getattr(dec, "ok", False))),
        "reason": getattr(dec, "reason", None),
        "approver_required": getattr(dec, "approver_required", None),
        "limit_window_label": getattr(dec, "limit_window_label", None),
        "next_eligible_at_iso": getattr(dec, "next_eligible_at_iso", None),
    }
    if not decision["ok"]:
        _emit(
            operation="issue.denied",
            reason=decision["reason"] or "denied",
            decision_payload=decision,
            stage="policy",
        )
        return {
            "ok": False,
            "reason": decision["reason"] or "denied",
            "decision": decision,
            "request_id": req_id,
        }

    # 3) Resolve item + batch if batch_ulid not supplied
    item = db.session.execute(
        select(InventoryItem).where(InventoryItem.sku == sku_code)
    ).scalar_one_or_none()
    if not item:
        reason = "item_not_found"
        _emit(
            operation="issue.failed",
            reason=reason,
            decision_payload=decision,
            stage="resolve_item",
        )
        return {
            "ok": False,
            "reason": reason,
            "decision": decision,
            "request_id": req_id,
        }

    it_ulid = item.ulid
    unit = item.unit  # canonical unit from InventoryItem

    b_ulid = batch_ulid
    if not b_ulid:
        b_ulid = db.session.execute(
            select(InventoryBatch.ulid)
            .where(
                InventoryBatch.item_ulid == it_ulid,
                InventoryBatch.location_ulid == location_ulid,
            )
            .order_by(InventoryBatch.ulid.desc())
        ).scalar_one_or_none()
        if not b_ulid:
            reason = "no_batch_at_location"
            _emit(
                operation="issue.failed",
                reason=reason,
                decision_payload=decision,
                stage="resolve_batch",
                refs_extra={"item_ulid": it_ulid},
            )
            return {
                "ok": False,
                "reason": reason,
                "decision": decision,
                "request_id": req_id,
            }

    # 4) Low-level issuance
    mv_ulid = issue_inventory_lowlevel(
        batch_ulid=b_ulid,
        item_ulid=it_ulid,
        quantity=quantity,
        unit=unit,
        location_ulid=location_ulid,
        happened_at_utc=as_of,
        target_ref_ulid=customer_ulid,
        note=None,
        actor_ulid=actor_ulid,
    )

    # 5) Attach decision trace to Issue
    attach_issue_decision(mv_ulid, decision)

    # 6) Emit audit spine event (immutable, success)
    _emit(
        operation="issue.created",
        reason="ok",
        decision_payload=decision,
        stage="success",
        refs_extra={"movement_ulid": mv_ulid},
    )

    return {
        "ok": True,
        "reason": "ok",
        "decision": decision,
        "movement_ulid": mv_ulid,
        "request_id": req_id,
    }


# -----------------
# Policy-only Issue:
# evaluate enforcer+policy,
# insert Issue (no stock/movement)
# -----------------

# FLOW: policy-only issuance (no stock)


def issue_inventory_policy(
    customer_ulid: str,
    sku_code: Optional[str],
    when_iso: Optional[str] = None,
    project_ulid: Optional[str] = None,
    *,
    actor_ulid: Optional[str] = None,  # ← standardized
    quantity: int = 1,
) -> IssueResult:
    """
    Policy-first issuance: enforcer + governance decision, then record an Issue
    (no stock math / movement). Meant for CLI/testing or workflows that don't
    pick a specific batch/location.
    {ok, reason, issue_ulid?, decision, meta?}
    """
    # 0) quick input guardrails
    if quantity <= 0:
        return IssueResult(ok=False, reason="invalid_quantity")

    as_of = when_iso or now_iso8601_ms()

    classification_key: Optional[str] = None
    parts: Optional[dict] = None
    if sku_code:
        if not validate_sku(sku_code):
            return IssueResult(ok=False, reason="invalid_sku")
        parts = parse_sku(sku_code)
        classification_key = classification_key_for(parts)

    ctx = IssueContext(
        customer_ulid=customer_ulid,
        sku_code=sku_code,
        classification_key=classification_key,
        when_iso=as_of,
        project_ulid=project_ulid,
        sku_parts=parts,
    )

    # 1) Enforcer (calendar blackout)
    ok, enf_meta = enforcers.calendar_blackout_ok(ctx)
    if not ok:
        decision = {
            "version": 1,
            "ok": False,
            "reason": enf_meta.get("reason", "calendar_blackout"),
            "enforcer": enf_meta,
            "policy": None,
            "ctx": {
                "customer_ulid": customer_ulid,
                "sku_code": sku_code,
                "classification_key": classification_key,
                "sku_parts": parts,
                "when_iso": as_of,
                "project_ulid": project_ulid,
                "quantity": quantity,
                "actor_ulid": actor_ulid,
            },
        }
        return IssueResult(
            ok=False, reason=decision["reason"], decision=decision
        )

    # 2) Governance (policy decision)
    dec = governance_v2.decide_issue(ctx)
    policy_dec = {
        "allowed": bool(getattr(dec, "allowed", getattr(dec, "ok", False))),
        "reason": getattr(dec, "reason", None),
        "approver_required": getattr(dec, "approver_required", None),
        "limit_window_label": getattr(dec, "limit_window_label", None),
        "next_eligible_at_iso": getattr(dec, "next_eligible_at_iso", None),
    }
    if not policy_dec["allowed"]:
        decision = {
            "version": 1,
            "ok": False,
            "reason": policy_dec["reason"] or "denied",
            "enforcer": {"reason": "ok"},
            "policy": policy_dec,
            "ctx": {
                "customer_ulid": customer_ulid,
                "sku_code": sku_code,
                "classification_key": classification_key,
                "sku_parts": parts,
                "when_iso": as_of,
                "project_ulid": project_ulid,
                "quantity": quantity,
                "actor_ulid": actor_ulid,
            },
        }
        return IssueResult(
            ok=False, reason=decision["reason"], decision=decision
        )

    # 3) Persist Issue row (policy-only)
    #    (If Issue model lacks auto-ULID, uncomment ulid=new_ulid())
    decision = {
        "version": 1,
        "ok": True,
        "reason": policy_dec["reason"] or "ok",
        "enforcer": {"reason": "ok"},
        "policy": policy_dec,
        "ctx": {
            "customer_ulid": customer_ulid,
            "sku_code": sku_code,
            "classification_key": classification_key,
            "sku_parts": parts,
            "when_iso": as_of,
            "project_ulid": project_ulid,
            "quantity": quantity,
            "actor_ulid": actor_ulid,
        },
    }

    row = Issue(
        # ulid=new_ulid(),          # ← enable if your model doesn’t auto-ULID
        customer_ulid=customer_ulid,
        classification_key=classification_key,
        sku_code=sku_code,
        quantity=quantity,
        issued_at=as_of,  # naive UTC ISO is fine if consistent everywhere
        project_ulid=project_ulid,
        movement_ulid=None,
        created_by_actor=actor_ulid,
        decision_json=pretty_dumps(decision),  # richer, self-describing trace
    )
    db.session.add(row)
    db.session.commit()

    return IssueResult(
        ok=True,
        reason="ok",
        issue_ulid=row.ulid,
        decision=decision,
        meta={"policy_only": True},
    )


# -----------------
# List Allowed SKUs
# for Customer at time T
# (ask Governance per SKU)
# -----------------

# FLOW: discovery helper for UIs (ask Governance per SKU)


def available_skus_for_customer(
    customer_ulid: str,
    as_of_iso: str,
    project_ulid: str | None = None,
    cost_cents: int | None = None,
) -> list[str]:
    """
    Iterate known SKUs and include those Governance approves for the given
    customer/time; Logistics defers all rules to Governance.
    """
    from app.extensions.contracts import governance_v2 as govc
    from app.slices.governance.services import decide_issue

    rows = db.session.execute(
        select(InventoryItem.sku, InventoryItem.category)
    ).all()

    allowed: list[str] = []
    for sku, category in rows:
        ctx = govc.RestrictionContext(
            customer_ulid=customer_ulid,
            sku_code=sku,
            classification_key=category,
            as_of_iso=as_of_iso,
            project_ulid=project_ulid,
            cost_cents=cost_cents,
        )
        decision = decide_issue(ctx)
        if getattr(decision, "ok", False):
            allowed.append(sku)
    return allowed
