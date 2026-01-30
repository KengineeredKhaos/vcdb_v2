# app/extensions/contracts/customers_v2.py
# -*- coding: utf-8 -*-
"""
customers_v2 — Stable read/write contract for the Customer slice.

Ethos:
- PII-free. DTOs expose ULIDs, booleans, enums/ints,
  and ISO-8601 timestamps only.
- Skinny contract. We delegate to slice services and normalize errors.
- Versioned. Keep this file backward-compatible once published;
  add customer_v3 for breaking changes.

Guaranteed fields:
- CustomerCuesDTO: primary cross-slice decision surface (PII-free cues).
- NeedsProfileDTO: legacy coarse decisions surface (kept for now).
- DashboardDTO: quick operator view (denormalized flags + latest tier maps).
- Write calls return ResultDTOs with refs
  (e.g., history version ULID) and never leak values.

Raises ContractError with code values:
- bad_argument
- permission_denied
- not_found
- internal_error

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping, Optional, TypedDict

from app.extensions import db
from app.extensions.errors import ContractError
from app.lib.chrono import now_iso8601_ms
from app.slices.customers import services as cust_svc

# ---------------------------
# Contract-scoped exceptions
# ---------------------------


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    # If we’re already looking at a ContractError, just bubble it up unchanged
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

    # Fallback: unexpected system/runtime error
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


class CustomerProfileDTO(TypedDict):
    customer_ulid: str
    is_veteran_verified: bool
    veteran_method: str
    flags: dict
    tier1: dict


__schema__ = {
    "get_profile": {
        "requires": ["customer_ulid"],
        "returns_keys": [
            "customer_ulid",
            "is_veteran_verified",
            "veteran_method",
            "flags",
            "tier1",
        ],
    }
}


@dataclass(frozen=True)
class NeedsProfileDTO:
    customer_ulid: str
    is_veteran_verified: bool
    veteran_method: Optional[str]
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
    customer_ulid: str
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    is_veteran_verified: bool
    is_homeless_verified: bool
    flag_tier1_immediate: bool
    watchlist: bool
    watchlist_since_utc: Optional[str]
    as_of_iso: str



@dataclass(frozen=True)
class DashboardDTO:
    customer_ulid: str
    entity_ulid: str
    tier1_min: int | None
    tier2_min: int | None
    tier3_min: int | None
    flag_tier1_immediate: bool
    flag_reason: Optional[str]
    watchlist: bool
    watchlist_since_utc: Optional[str]
    is_veteran_verified: bool
    veteran_method: Optional[str]
    is_homeless_verified: bool
    tier_factors: Mapping[str, Mapping[str, object]]
    status: str
    first_seen_utc: Optional[str]
    last_touch_utc: Optional[str]
    last_needs_update_utc: Optional[str]
    last_needs_tier_updated: Optional[str]
    as_of_iso: str


@dataclass(frozen=True)
class VerificationResultDTO:
    customer_ulid: str
    is_veteran_verified: bool
    veteran_method: Optional[str]
    approved_by_ulid: Optional[str]
    approved_at_utc: Optional[str]
    as_of_iso: str


@dataclass(frozen=True)
class TierUpdateResultDTO:
    customer_ulid: str
    section: str  # e.g., "profile:needs:tier1"
    version_ptr: str  # ULID of CustomerHistory row
    as_of_iso: str


# ---------------------------
# Helpers
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


def get_profile(customer_ulid: str) -> CustomerProfileDTO:
    # stub; replace with real read-path later
    return {
        "customer_ulid": customer_ulid,
        "is_veteran_verified": False,
        "veteran_method": "self_attested",
        "flags": {"is_homeless": False},
        "tier1": {"housing": 0, "food": 0, "clothing": 0},
    }


def get_customer_cues(customer_ulid: str) -> CustomerCuesDTO:
    """
    Primary cross-slice read: decision-ready, PII-free cues for gating.

    This is the single surface Logistics (and other slices) should consume for
    SKU filtering and eligibility gates.

    Returns:
        CustomerCuesDTO

    Raises:
        ContractError (404) if customer_ulid not found.
    """
    where = WHERE_GET_CUSTOMER_CUES
    try:
        dv = cust_svc.get_dashboard_view(customer_ulid)
        if dv is None:
            raise LookupError("customer not found")

        snap = cust_svc.get_eligibility_snapshot(customer_ulid)
        if snap is None:
            raise LookupError("eligibility not found")

        return CustomerCuesDTO(
            customer_ulid=snap.customer_ulid,
            tier1_min=snap.tier1_min,
            tier2_min=snap.tier2_min,
            tier3_min=snap.tier3_min,
            is_veteran_verified=bool(snap.is_veteran_verified),
            is_homeless_verified=bool(snap.is_homeless_verified),
            flag_tier1_immediate=bool(getattr(dv, "flag_tier1_immediate", False)),
            watchlist=bool(getattr(dv, "watchlist", False)),
            watchlist_since_utc=getattr(dv, "watchlist_since_utc", None),
            as_of_iso=now_iso8601_ms(),
        )
    except LookupError as exc:
        raise ContractError(
            code="not_found",
            where=where,
            message=str(exc),
            http_status=404,
            data={"customer_ulid": customer_ulid},
        ) from exc
    except Exception as exc:
        raise _as_contract_error(where, exc)


def get_needs_profile(customer_ulid: str) -> NeedsProfileDTO:
    where = WHERE_GET_NEEDS_PROFILE
    try:
        dv = cust_svc.get_dashboard_view(customer_ulid)
        if dv is None:
            raise LookupError("customer not found")

        snap = cust_svc.get_eligibility_snapshot(customer_ulid)
        return NeedsProfileDTO(
            customer_ulid=snap.customer_ulid,
            is_veteran_verified=snap.is_veteran_verified,
            is_homeless_verified=snap.is_homeless_verified,
            tier1_min=snap.tier1_min,
            tier2_min=snap.tier2_min,
            tier3_min=snap.tier3_min,
            veteran_method=veteran_method or getattr(dv, 'veteran_method', None),
            as_of_iso=now_iso8601_ms(),
        )
    except Exception as e:
        raise _as_contract_error(where, e)


def get_dashboard_view(customer_ulid: str) -> DashboardDTO | None:
    """
    Operator-facing aggregated read.

    Returns None if the customer_ulid does not exist.
    NOTE: This function is intentionally non-raising for 'missing customer' semantics.

    DashboardView is allowed to be a lightweight projection; eligibility fields
    are sourced from the canonical typed eligibility snapshot.
    """
    dv = cust_svc.get_dashboard_view(customer_ulid)
    if not dv:
        return None

    snap = cust_svc.get_eligibility_snapshot(customer_ulid)

    is_veteran_verified = bool(snap.is_veteran_verified) if snap else False
    is_homeless_verified = bool(snap.is_homeless_verified) if snap else False
    veteran_method = snap.veteran_method if snap else None

    return DashboardDTO(
        customer_ulid=dv.customer_ulid,
        entity_ulid=dv.entity_ulid,
        tier1_min=dv.tier1_min,
        tier2_min=dv.tier2_min,
        tier3_min=dv.tier3_min,
        flag_tier1_immediate=dv.flag_tier1_immediate,
        flag_reason=dv.flag_reason,
        watchlist=dv.watchlist,
        watchlist_since_utc=dv.watchlist_since_utc,
        is_veteran_verified=is_veteran_verified,
        veteran_method=veteran_method or getattr(dv, "veteran_method", None),
        is_homeless_verified=is_homeless_verified,
        tier_factors=dv.tier_factors,
        status=dv.status,
        first_seen_utc=dv.first_seen_utc,
        last_touch_utc=dv.last_touch_utc,
        last_needs_update_utc=dv.last_needs_update_utc,
        last_needs_tier_updated=dv.last_needs_tier_updated,
        as_of_iso=dv.as_of_iso,
    )


def verify_veteran(
    *,
    customer_ulid: str,
    method: str,  # "dd214" | "va_id" | "state_dl_veteran" | "other"
    verified: bool,
    actor_ulid: str | None,
    actor_has_governor: bool,
    request_id: str,
) -> VerificationResultDTO:
    """
    Update veteran verification state (write) and return a lightweight result DTO.

    Allowed methods and governor-only exceptions are enforced in Customers services
    via Governance policy (governance_v2).
    """
    where = WHERE_VERIFY_VETERAN
    try:
        snap = cust_svc.set_veteran_verification(
            customer_ulid=customer_ulid,
            method=method,
            verified=verified,
            actor_ulid=actor_ulid,
            actor_has_governor=actor_has_governor,
            request_id=request_id,
        )

        return VerificationResultDTO(
            customer_ulid=customer_ulid,
            is_veteran_verified=bool(snap.is_veteran_verified),
            veteran_method=snap.veteran_method or (method if verified else None),
            approved_by_ulid=snap.approved_by_ulid,
            approved_at_utc=snap.approved_at_utc,
            as_of_iso=now_iso8601_ms(),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc)


def update_tier1(
    *,
    customer_ulid: str,
    payload: dict,
    request_id: str,
    actor_ulid: str | None,
) -> TierUpdateResultDTO:
    where = WHERE_UPDATE_TIER1
    try:
        vptr = cust_svc.update_tier1(
            customer_ulid=customer_ulid,
            payload=payload,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return TierUpdateResultDTO(
            customer_ulid=customer_ulid,
            section="profile:needs:tier1",
            version_ptr=vptr,
            as_of_iso=now_iso8601_ms(),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc)


def update_tier2(
    *,
    customer_ulid: str,
    payload: dict,
    request_id: str,
    actor_ulid: str | None,
) -> TierUpdateResultDTO:
    where = WHERE_UPDATE_TIER2
    try:
        vptr = cust_svc.update_tier2(
            customer_ulid=customer_ulid,
            payload=payload,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return TierUpdateResultDTO(
            customer_ulid=customer_ulid,
            section="profile:needs:tier2",
            version_ptr=vptr,
            as_of_iso=now_iso8601_ms(),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc)


def update_tier3(
    *,
    customer_ulid: str,
    payload: dict,
    request_id: str,
    actor_ulid: str | None,
) -> TierUpdateResultDTO:
    where = WHERE_UPDATE_TIER3
    try:
        vptr = cust_svc.update_tier3(
            customer_ulid=customer_ulid,
            payload=payload,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return TierUpdateResultDTO(
            customer_ulid=customer_ulid,
            section="profile:needs:tier3",
            version_ptr=vptr,
            as_of_iso=now_iso8601_ms(),
        )
    except Exception as exc:
        raise _as_contract_error(where, exc)