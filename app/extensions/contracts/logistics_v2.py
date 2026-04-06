# app/extensions/contracts/logistics_v2.py

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict

from app.lib.chrono import parse_iso8601
from app.slices.logistics.issuance_services import available_skus_for_customer
from app.slices.logistics.services import (
    count_issues_in_window,
    nth_oldest_issue_at_in_window,
)


class CadenceGateDTO(TypedDict, total=False):
    eligible: bool
    next_eligible_at_iso: str | None
    rule_id: str
    label: str | None
    status: str
    enforcement: str | None
    requires_override: bool


__schema__ = {
    "get_sku_cadence": {
        "requires": ["customer_ulid", "sku"],
        "returns_keys": [
            "eligible",
            "next_eligible_at_iso",
            "rule_id",
            "label",
            "status",
            "enforcement",
            "requires_override",
        ],
    },
    "preview_customer_issuance_cart": {
        "requires": ["customer_ulid", "location_ulid"],
    },
    "commit_customer_issuance_cart": {
        "requires": [
            "customer_ulid",
            "location_ulid",
            "cart_lines",
            "actor_ulid",
        ],
    },
}


def get_sku_cadence(customer_ulid: str, sku: str) -> CadenceGateDTO:
    from app.slices.logistics.issuance_services import (
        IssueContext,
        decide_issue,
    )

    decision = decide_issue(
        IssueContext(customer_ulid=customer_ulid, sku_code=sku)
    )
    status = "eligible"
    if not decision.allowed and decision.reason == "cadence_advisory":
        status = "advisory_warn"
    elif not decision.allowed:
        status = "blocked"

    return {
        "eligible": bool(decision.allowed),
        "next_eligible_at_iso": decision.next_eligible_at_iso,
        "rule_id": decision.reason,
        "label": decision.limit_window_label,
        "status": status,
        "enforcement": decision.cadence_enforcement,
        "requires_override": decision.reason == "cadence_advisory",
    }


def decide_issue(ctx):
    # thin contract wrapper; Logistics owns the implementation
    from app.slices.logistics.issuance_services import decide_issue as _decide

    return _decide(ctx)


def preview_customer_issuance_cart(
    *, customer_ulid: str, location_ulid: str, as_of_iso: str | None = None
) -> dict[str, Any]:
    from app.slices.logistics.issuance_services import (
        preview_customer_issuance_cart as _preview,
    )

    return _preview(
        customer_ulid=customer_ulid,
        location_ulid=location_ulid,
        as_of_iso=as_of_iso,
    )


def commit_customer_issuance_cart(
    *,
    customer_ulid: str,
    location_ulid: str,
    cart_lines: list[dict[str, Any]],
    actor_ulid: str,
    request_id: str | None = None,
    as_of_dt: datetime | None = None,
    when_iso: str | None = None,
    project_ulid: str | None = None,
    session_note: str | None = None,
    override_cadence: bool = False,
    override_reason: str | None = None,
) -> dict[str, Any]:
    from app.slices.logistics.issuance_services import (
        commit_customer_issuance_cart as _commit,
    )

    effective_as_of_dt = as_of_dt or (
        parse_iso8601(when_iso) if when_iso else None
    )

    return _commit(
        customer_ulid=customer_ulid,
        location_ulid=location_ulid,
        cart_lines=cart_lines,
        actor_ulid=actor_ulid,
        request_id=request_id,
        as_of_dt=effective_as_of_dt,
        project_ulid=project_ulid,
        session_note=session_note,
        override_cadence=override_cadence,
        override_reason=override_reason,
    )


__all__ = [
    "available_skus_for_customer",
    "count_issues_in_window",
    "get_sku_cadence",
    "preview_customer_issuance_cart",
    "commit_customer_issuance_cart",
    "nth_oldest_issue_at_in_window",
    "decide_issue",
]


# 🔗 Bind to provider
