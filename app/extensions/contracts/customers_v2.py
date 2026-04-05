"""
customers_v2 — Stable read/write contract for the Customers slice.

Ethos:
- PII-free. DTOs expose ULIDs, booleans, enums/ints, and ISO-8601 timestamps.
- Skinny contract. Validate -> call service -> return DTO, normalize errors.
- Small, boring, brutally honest. Publish only current proven Customer truth.
- Versioned. Once published, breaking changes go to customers_v3.

Published surface in this refit:
- get_customer_summary(...)
- get_customer_cues(...)
- get_eligibility_snapshot(...)
- get_assessment_snapshot(...)
- append_history_entry(...)

CustomerCuesDTO is the cross-slice decision packet. It should publish
current, Customer-owned readiness truth directly rather than reconstructing
older semantics from eligibility fields. Downstream slices such as Resources
consume these cues without reaching into Customer internals.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from app.extensions.errors import ContractError
from app.lib.chrono import now_iso8601_ms
from app.slices.customers import services as cust_svc

# ---------------------------
# Contract-scoped exceptions
# ---------------------------


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    if isinstance(exc, ContractError):
        return exc

    msg = str(exc) or exc.__class__.__name__

    if isinstance(exc, ValueError):
        return ContractError(
            code="bad_argument",
            where=where,
            message=msg,
            http_status=400,
        )
    if isinstance(exc, PermissionError):
        return ContractError(
            code="permission_denied",
            where=where,
            message=msg,
            http_status=403,
        )
    if isinstance(exc, LookupError):
        return ContractError(
            code="not_found",
            where=where,
            message=msg,
            http_status=404,
        )

    return ContractError(
        code="internal_error",
        where=where,
        message="unexpected error in customers contract; see logs",
        http_status=500,
        data={"exc_type": exc.__class__.__name__},
    )


def _require_text(value: str, *, field: str, where: str) -> str:
    out = str(value or "").strip()
    if not out:
        raise ContractError(
            code="bad_argument",
            where=where,
            message=f"{field} is required",
            http_status=400,
        )
    return out


def _is_veteran_verified(status: str | None) -> bool:
    return str(status or "").strip().lower() == "verified"


def _is_homeless_verified(status: str | None) -> bool:
    return str(status or "").strip().lower() == "unhoused"


@dataclass(frozen=True)
class CustomerSummaryDTO:
    entity_ulid: str
    status: str
    intake_step: str | None
    intake_completed_at_iso: str | None
    watchlist: bool
    veteran_status: str
    housing_status: str
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    flag_tier1_immediate: bool
    assessment_version: int
    last_assessed_at_iso: str | None
    as_of_iso: str

    @property
    def customer_ulid(self) -> str:
        return self.entity_ulid


@dataclass(frozen=True)
class CustomerCuesDTO:
    """

    Primary downstream matching signals are:
    - eligibility_complete
    - tierN_unlocked
    - tierN_min

    Advisory-only signals such as entity_package_incomplete remain present so
    other consumers can surface them without re-reading Customer internals.
    """

    entity_ulid: str
    eligibility_complete: bool
    entity_package_incomplete: bool
    is_veteran_verified: bool
    is_homeless_verified: bool
    veteran_method: str | None
    housing_status: str
    tier1_unlocked: bool
    tier2_unlocked: bool
    tier3_unlocked: bool
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    flag_tier1_immediate: bool
    watchlist: bool
    status: str
    intake_step: str | None
    as_of_iso: str

    @property
    def customer_ulid(self) -> str:
        return self.entity_ulid


@dataclass(frozen=True)
class EligibilitySnapshotDTO:
    entity_ulid: str
    veteran_status: str
    veteran_method: str | None
    branch: str | None
    era: str | None
    housing_status: str
    approved_by_ulid: str | None
    approved_at_iso: str | None
    as_of_iso: str

    @property
    def customer_ulid(self) -> str:
        return self.entity_ulid


@dataclass(frozen=True)
class AssessmentSnapshotDTO:
    entity_ulid: str
    status: str
    intake_step: str | None
    watchlist: bool
    assessment_version: int
    last_assessed_at_iso: str | None
    veteran_status: str
    veteran_method: str | None
    housing_status: str
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    flag_tier1_immediate: bool
    as_of_iso: str

    @property
    def customer_ulid(self) -> str:
        return self.entity_ulid


# ---------------------------
# Helpers / Where tags
# ---------------------------

WHERE_GET_CUSTOMER_SUMMARY: Final[str] = "customers_v2.get_customer_summary"
WHERE_GET_CUSTOMER_CUES: Final[str] = "customers_v2.get_customer_cues"
WHERE_GET_ELIGIBILITY_SNAPSHOT: Final[
    str
] = "customers_v2.get_eligibility_snapshot"
WHERE_GET_ASSESSMENT_SNAPSHOT: Final[
    str
] = "customers_v2.get_assessment_snapshot"
WHERE_APPEND_HISTORY_ENTRY: Final[str] = "customers_v2.append_history_entry"


# ---------------------------
# Read contracts
# ---------------------------


def get_customer_summary(entity_ulid: str) -> CustomerSummaryDTO:
    where = WHERE_GET_CUSTOMER_SUMMARY
    ent = _require_text(entity_ulid, field="entity_ulid", where=where)
    try:
        dash = cust_svc.get_customer_dashboard(ent)
        elig = cust_svc.get_customer_eligibility(ent)
        return CustomerSummaryDTO(
            entity_ulid=dash.entity_ulid,
            status=dash.status,
            intake_step=dash.intake_step,
            intake_completed_at_iso=dash.intake_completed_at_iso,
            watchlist=bool(dash.watchlist),
            veteran_status=elig.veteran_status,
            housing_status=elig.housing_status,
            tier1_min=dash.tier1_min,
            tier2_min=dash.tier2_min,
            tier3_min=dash.tier3_min,
            flag_tier1_immediate=bool(dash.flag_tier1_immediate),
            assessment_version=int(dash.assessment_version),
            last_assessed_at_iso=dash.last_assessed_at_iso,
            as_of_iso=now_iso8601_ms(),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_customer_cues(entity_ulid: str) -> CustomerCuesDTO:
    where = WHERE_GET_CUSTOMER_CUES
    ent = _require_text(entity_ulid, field="entity_ulid", where=where)
    try:
        dash = cust_svc.get_customer_dashboard(ent)
        elig = cust_svc.get_customer_eligibility(ent)
        return CustomerCuesDTO(
            entity_ulid=ent,
            eligibility_complete=bool(dash.eligibility_complete),
            entity_package_incomplete=bool(dash.entity_package_incomplete),
            is_veteran_verified=_is_veteran_verified(elig.veteran_status),
            is_homeless_verified=(
                str(elig.housing_status or "").strip().lower() == "unhoused"
            ),
            veteran_method=elig.veteran_method,
            housing_status=elig.housing_status,
            tier1_unlocked=bool(dash.tier1_unlocked),
            tier2_unlocked=bool(dash.tier2_unlocked),
            tier3_unlocked=bool(dash.tier3_unlocked),
            tier1_min=dash.tier1_min,
            tier2_min=dash.tier2_min,
            tier3_min=dash.tier3_min,
            flag_tier1_immediate=bool(dash.flag_tier1_immediate),
            watchlist=bool(dash.watchlist),
            status=dash.status,
            intake_step=dash.intake_step,
            as_of_iso=now_iso8601_ms(),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_eligibility_snapshot(entity_ulid: str) -> EligibilitySnapshotDTO:
    where = WHERE_GET_ELIGIBILITY_SNAPSHOT
    ent = _require_text(entity_ulid, field="entity_ulid", where=where)
    try:
        snap = cust_svc.get_customer_eligibility(ent)
        return EligibilitySnapshotDTO(
            entity_ulid=snap.entity_ulid,
            veteran_status=snap.veteran_status,
            veteran_method=snap.veteran_method,
            branch=snap.branch,
            era=snap.era,
            housing_status=snap.housing_status,
            approved_by_ulid=snap.approved_by_ulid,
            approved_at_iso=snap.approved_at_iso,
            as_of_iso=now_iso8601_ms(),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_assessment_snapshot(entity_ulid: str) -> AssessmentSnapshotDTO:
    where = WHERE_GET_ASSESSMENT_SNAPSHOT
    ent = _require_text(entity_ulid, field="entity_ulid", where=where)
    try:
        dash = cust_svc.get_customer_dashboard(ent)
        elig = cust_svc.get_customer_eligibility(ent)
        return AssessmentSnapshotDTO(
            entity_ulid=ent,
            status=dash.status,
            intake_step=dash.intake_step,
            watchlist=bool(dash.watchlist),
            assessment_version=int(dash.assessment_version),
            last_assessed_at_iso=dash.last_assessed_at_iso,
            veteran_status=elig.veteran_status,
            veteran_method=elig.veteran_method,
            housing_status=elig.housing_status,
            tier1_min=dash.tier1_min,
            tier2_min=dash.tier2_min,
            tier3_min=dash.tier3_min,
            flag_tier1_immediate=bool(dash.flag_tier1_immediate),
            as_of_iso=now_iso8601_ms(),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Write contracts
# -----------------


def append_history_entry(
    *,
    target_entity_ulid: str,
    kind: str,
    blob_json: str | Mapping[str, Any],
    actor_ulid: str,
    request_id: str,
) -> str:
    where = WHERE_APPEND_HISTORY_ENTRY
    ent = _require_text(
        target_entity_ulid,
        field="target_entity_ulid",
        where=where,
    )
    kind_val = _require_text(kind, field="kind", where=where)
    act = _require_text(actor_ulid, field="actor_ulid", where=where)
    rid = _require_text(request_id, field="request_id", where=where)

    if not isinstance(blob_json, (str, Mapping)):
        raise ContractError(
            code="bad_argument",
            where=where,
            message="blob_json must be a JSON string or mapping",
            http_status=400,
        )

    try:
        return cust_svc.append_history_entry(
            target_entity_ulid=ent,
            kind=kind_val,
            blob_json=blob_json,
            actor_ulid=act,
            request_id=rid,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


__all__ = [
    "AssessmentSnapshotDTO",
    "CustomerCuesDTO",
    "CustomerSummaryDTO",
    "EligibilitySnapshotDTO",
    "append_history_entry",
    "get_assessment_snapshot",
    "get_customer_cues",
    "get_customer_summary",
    "get_eligibility_snapshot",
]
