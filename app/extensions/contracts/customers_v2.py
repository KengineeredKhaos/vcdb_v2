"""
customers_v2 — Stable read/write contract for the Customers slice.

Ethos:
- PII-free. DTOs expose ULIDs, booleans, enums/ints, and ISO-8601 timestamps.
- Skinny contract. validate -> call service -> return DTO, normalize errors.
- Versioned. Once published, breaking changes go to customers_v3.

Raises ContractError with code values:
- bad_argument
- permission_denied
- not_found
- internal_error
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
        message="unexpected error in contract; see logs",
        http_status=500,
        data={"exc_type": exc.__class__.__name__},
    )


# ---------------------------
# DTOs
# ---------------------------


@dataclass(frozen=True)
class NeedsProfileDTO:
    entity_ulid: str
    is_veteran_verified: bool
    veteran_method: str | None
    is_homeless_verified: bool
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    as_of_iso: str


@dataclass(frozen=True)
class CustomerCuesDTO:
    """
    Canonical, PII-free, decision-ready cues for cross-slice gating.
    Intended to be stable and grep-able across slices.
    """

    entity_ulid: str
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    is_veteran_verified: bool
    is_homeless_verified: bool
    flag_tier1_immediate: bool
    watchlist: bool
    watchlist_since_utc: str | None
    as_of_iso: str


@dataclass(frozen=True)
class DashboardDTO:
    entity_ulid: str
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    flag_tier1_immediate: bool
    flag_reason: str | None
    watchlist: bool
    watchlist_since_utc: str | None
    is_veteran_verified: bool
    veteran_method: str | None
    is_homeless_verified: bool
    tier_factors: Mapping[str, Mapping[str, object]]
    status: str
    intake_step: str | None
    first_seen_utc: str | None
    last_touch_utc: str | None
    last_needs_update_utc: str | None
    last_needs_tier_updated: str | None
    as_of_iso: str


@dataclass(frozen=True)
class VerificationResultDTO:
    entity_ulid: str
    is_veteran_verified: bool
    veteran_method: str | None
    approved_by_ulid: str | None
    approved_at_utc: str | None
    as_of_iso: str


@dataclass(frozen=True)
class TierUpdateResultDTO:
    entity_ulid: str
    section: str
    version_ptr: str
    as_of_iso: str


# ---------------------------
# Helpers / Where tags
# ---------------------------

WHERE_GET_CUSTOMER_CUES: Final[str] = "customers_v2.get_customer_cues"
WHERE_GET_DASHBOARD_VIEW: Final[str] = "customers_v2.get_dashboard_view"
WHERE_GET_NEEDS_PROFILE: Final[str] = "customers_v2.get_needs_profile"
WHERE_VERIFY_VETERAN: Final[str] = "customers_v2.verify_veteran"
WHERE_UPDATE_TIER1: Final[str] = "customers_v2.update_tier1"
WHERE_UPDATE_TIER2: Final[str] = "customers_v2.update_tier2"
WHERE_UPDATE_TIER3: Final[str] = "customers_v2.update_tier3"


# ---------------------------
# READ CONTRACT
# ---------------------------


# Hard-fail enforcement
def get_profile(entity_ulid: str):
    raise ContractError(
        code="internal_error",
        where="customers_v2.get_profile",
        message="get_profile is deprecated; use get_dashboard_view/cues",
        http_status=501,
    )


def get_customer_cues(entity_ulid: str) -> CustomerCuesDTO:
    where = WHERE_GET_CUSTOMER_CUES
    try:
        dv = cust_svc.get_dashboard_view(entity_ulid)
        if dv is None:
            raise LookupError("customer not found")

        snap = cust_svc.get_eligibility_snapshot(entity_ulid)
        if snap is None:
            raise LookupError("eligibility not found")

        return CustomerCuesDTO(
            entity_ulid=snap.entity_ulid,
            tier1_min=snap.tier1_min,
            tier2_min=snap.tier2_min,
            tier3_min=snap.tier3_min,
            is_veteran_verified=bool(snap.is_veteran_verified),
            is_homeless_verified=bool(snap.is_homeless_verified),
            flag_tier1_immediate=bool(dv.flag_tier1_immediate),
            watchlist=bool(dv.watchlist),
            watchlist_since_utc=dv.watchlist_since_utc,
            as_of_iso=now_iso8601_ms(),
        )
    except LookupError as exc:
        raise ContractError(
            code="not_found",
            where=where,
            message=str(exc),
            http_status=404,
            data={"entity_ulid": entity_ulid},
        ) from exc
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_needs_profile(entity_ulid: str) -> NeedsProfileDTO:
    where = WHERE_GET_NEEDS_PROFILE
    try:
        dv = cust_svc.get_dashboard_view(entity_ulid)
        if dv is None:
            raise LookupError("customer not found")

        snap = cust_svc.get_eligibility_snapshot(entity_ulid)
        if snap is None:
            raise LookupError("eligibility not found")

        return NeedsProfileDTO(
            entity_ulid=entity_ulid,
            is_veteran_verified=bool(snap.is_veteran_verified),
            veteran_method=snap.veteran_method,
            is_homeless_verified=bool(snap.is_homeless_verified),
            tier1_min=snap.tier1_min,
            tier2_min=snap.tier2_min,
            tier3_min=snap.tier3_min,
            as_of_iso=now_iso8601_ms(),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_dashboard_view(entity_ulid: str) -> DashboardDTO | None:
    """
    Operator-facing aggregated read.

    Returns None if entity_ulid does not exist (non-raising missing semantic).
    """
    dv = cust_svc.get_dashboard_view(entity_ulid)
    if not dv:
        return None

    snap = cust_svc.get_eligibility_snapshot(entity_ulid)

    is_veteran = bool(snap.is_veteran_verified) if snap else False
    is_homeless = bool(snap.is_homeless_verified) if snap else False
    v_method = snap.veteran_method if snap else None

    return DashboardDTO(
        entity_ulid=dv.entity_ulid,
        tier1_min=dv.tier1_min,
        tier2_min=dv.tier2_min,
        tier3_min=dv.tier3_min,
        flag_tier1_immediate=dv.flag_tier1_immediate,
        flag_reason=dv.flag_reason,
        watchlist=dv.watchlist,
        watchlist_since_utc=dv.watchlist_since_utc,
        is_veteran_verified=is_veteran,
        veteran_method=v_method,
        is_homeless_verified=is_homeless,
        tier_factors=dv.tier_factors,
        status=dv.status,
        intake_step=dv.intake_step,
        first_seen_utc=dv.first_seen_utc,
        last_touch_utc=dv.last_touch_utc,
        last_needs_update_utc=dv.last_needs_update_utc,
        last_needs_tier_updated=dv.last_needs_tier_updated,
        as_of_iso=dv.as_of_iso,
    )


# -----------------
# Write contracts
# -----------------


def append_history_entry(
    *,
    target_entity_ulid: str,
    kind: str,
    blob_json: str | Mapping[str, Any],
    actor_ulid: str | None,
    request_id: str | None,
) -> str:
    pass
