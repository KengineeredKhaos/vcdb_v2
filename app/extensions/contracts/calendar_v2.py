# app / extensions / contracts / calendar_v2.py

# ------------------
# NOTE:
#
# Do not rely on this module for policy decisions.
# The policy itself still lives in calendar.services.is_blackout,
# which reads policy_calendar.json
# ------------------

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, TypedDict

from app.extensions.errors import ContractError

# -----------------
# ContractError Handling
# -----------------


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


def _require_str(name: str, value: str | None) -> str:
    if not value or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _require_ulid(name: str, value: str | None) -> str:
    v = _require_str(name, value)
    if len(v) != 26:
        raise ValueError(f"{name} must be a 26-char ULID")
    return v


def _require_int_ge(name: str, value: Any, minval: int = 0) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an int")
    if value < minval:
        raise ValueError(f"{name} must be >= {minval}")
    return value


# -----------------
# DTO's & Helpers
# (new paradigm)
# -----------------


@dataclass(frozen=True)
class FundingDemandDTO:
    funding_demand_ulid: str
    project_ulid: str
    title: str
    status: str
    goal_cents: int
    deadline_date: str | None
    eligible_fund_keys: tuple[str, ...]


# -----------------
# Old Paradigm
# DTO's
# -----------------


class ProjectDTO(TypedDict):
    ulid: str
    title: str
    status: str
    fund_profile_key: str
    phase_code: str | None
    owner_ulid: str | None
    created_at_utc: str
    updated_at_utc: str


class TaskDTO(TypedDict):
    pass


class CalendarGateDTO(TypedDict):
    ok: bool
    label: str | None
    reason: str  # ok|calendar_blackout|calendar_unavailable


class ProjectFundingPlanDTO(TypedDict):
    ulid: str
    project_ulid: str
    label: str
    source_kind: str | None
    expected_amount_cents: int | None
    is_in_kind: bool
    expected_sponsor_hint: str | None
    notes: str | None
    created_at_utc: str
    updated_at_utc: str


class ProjectBudgetSummaryDTO(TypedDict):
    pass


__schema__ = {
    "blackout_ok": {
        "requires": ["when_iso?"],
        "returns_keys": ["ok", "label", "reason"],
    }
}


# -----------------
# Funding Demand
# New Paradigm
# -----------------


def _load_provider(where: str):
    """
    Calendar slice must provide a read-only function with this signature:

        get_funding_demand(funding_demand_ulid: str) -> dict[str, Any]

    Expected keys:
      funding_demand_ulid, project_ulid, title, status, goal_cents,
      deadline_date, eligible_fund_keys
    """
    try:
        mod = importlib.import_module("app.slices.calendar.services_funding")
        fn = getattr(mod, "get_funding_demand")
        return fn
    except Exception as exc:  # noqa: BLE001
        raise ContractError(
            code="provider_missing",
            where=where,
            message=(
                "Calendar provider missing: "
                "app.slices.calendar.services_funding.get_funding_demand"
            ),
            http_status=500,
        ) from exc


def get_funding_demand(funding_demand_ulid: str) -> FundingDemandDTO:
    where = "calendar_v2.get_funding_demand"
    try:
        provider = _load_provider(where)
        raw = provider(funding_demand_ulid)

        eligible = tuple(raw.get("eligible_fund_keys") or ())
        return FundingDemandDTO(
            funding_demand_ulid=str(raw["funding_demand_ulid"]),
            project_ulid=str(raw["project_ulid"]),
            title=str(raw.get("title") or ""),
            status=str(raw.get("status") or "unknown"),
            goal_cents=int(raw.get("goal_cents") or 0),
            deadline_date=raw.get("deadline_date"),
            eligible_fund_keys=eligible,
        )
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


# -----------------
# Old Paradigm
# below this line
# -----------------


# -----------------
# Provider:
# Calendar slice
# Blackout Check
# -----------------


def blackout_ok(when_iso: str | None = None) -> CalendarGateDTO:
    where = "calendar_v2.blackout_ok"
    try:
        from app.slices.calendar import services as svc

        when = when_iso.strip() if isinstance(when_iso, str) else None
        if when == "":
            raise ValueError("when_iso must be non-empty if provided")

        blocked = svc.is_blackout(
            when_iso=when
        )  # <-- service should accept None
        return {
            "ok": not blocked,
            "label": "blackout" if blocked else None,
            "reason": "calendar_blackout" if blocked else "ok",
        }
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


# -----------------
# Project Context
# -----------------


def create_project(
    *,
    project_title: str,
    fund_profile_key: str | None = None,
    owner_ulid: str | None = None,
    phase_code: str | None = None,
    status: str | None = None,
    actor_ulid: str,
    request_id: str,
) -> ProjectDTO:
    """
    Contract entry point for creating a Calendar project.

    This is a thin, versioned wrapper around the Calendar slice's
    ``services.create_project(...)`` implementation. It:

      * validates argument shape (ULIDs, non-empty strings),
      * builds a payload dictionary that the slice service expects,
      * forwards ``actor_ulid`` and ``request_id`` for auditing,
      * wraps any slice errors as :class:`ContractError` via
        :func:`_as_contract_error`.

    All policy decisions (blackouts, funding rules, precedence, etc.)
    are expected to be handled by higher-level flows (Governance /
    Admin) before calling this contract. This call only creates the
    project record and emits a Calendar domain event.

    Arguments:
        project_title:
            Human-facing title for the project (e.g. "Stand Down 2026").
        fund_ulid:
            Optional ULID of a Finance fund to associate as the
            "primary" fund for this project. May be ``None`` for
            projects that don't yet have a chosen fund.
        owner_ulid:
            Optional Entity ULID representing the project owner
            (person or org).
        phase_code:
            Optional short code describing the phase (e.g. "planning",
            "execution"); semantics are defined by Governance/UI.
        status:
            Optional initial status. If omitted, defaults to
            ``"planned"``.

        actor_ulid:
            Entity ULID of the actor creating the project. Used for
            event_bus / ledger attribution.
        request_id:
            Correlation id for the call (ULID or other unique token);
            propagated into emitted events for traceability.

    Returns:
        ProjectDTO:
            PII-free projection of the newly created project, including
            a resolved Fund summary (if a fund was attached).

    Raises:
        ContractError:
            - code="bad_argument" for malformed inputs (bad ULID,
              empty title, etc.).
            - code="not_found" if the referenced fund does not exist
              (when the slice chooses to enforce that).
            - code="internal_error" for unexpected failures; the
              underlying exception type is attached in ``data``.
    """
    where = "calendar_v2.create_project"
    try:
        project_title = _require_str("project_title", project_title)
        if owner_ulid is not None:
            owner_ulid = _require_ulid("owner_ulid", owner_ulid)
        if status is None:
            status = "planned"
        else:
            status = _require_str("status", status)

        from app.slices.calendar import services as svc

        payload = {
            "project_title": project_title,
            "fund_profile_key": fund_profile_key,
            "owner_ulid": owner_ulid,
            "phase_code": phase_code,
            "status": status,
        }

        return svc.create_project(
            payload,
            actor_ulid=actor_ulid,
            request_id=request_id,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def create_project_funding_plan(
    *,
    project_ulid: str,
    label: str,
    source_kind: str | None = None,
    fund_archetype_key: str | None = None,
    expected_amount_cents: int | None = None,
    is_in_kind: bool = False,
    expected_sponsor_hint: str | None = None,
    notes: str | None = None,
    actor_ulid: str | None = None,
    request_id: str | None = None,
) -> ProjectFundingPlanDTO:
    """
    Create a ProjectFundingPlan row for a Calendar Project.

    Thin contract wrapper around
    :func:`app.slices.calendar.services.create_project_funding_plan`.

    Responsibilities:
      * Validate argument shapes (ULIDs, strings, ints where applicable).
      * Shape arguments into a payload dict for the Calendar slice.
      * Delegate to the Calendar service implementation.
      * Map any underlying errors into a canonical ContractError.
    """
    where = "calendar_v2.create_project_funding_plan"
    try:
        project_ulid = _require_ulid("project_ulid", project_ulid)
        label = _require_str("label", label)

        if source_kind is not None:
            source_kind = _require_str("source_kind", source_kind)
        if fund_archetype_key is not None:
            fund_archetype_key = _require_str(
                "fund_archetype_key", fund_archetype_key
            )

        if expected_amount_cents is not None:
            expected_amount_cents = _require_int_ge(
                "expected_amount_cents", expected_amount_cents, minval=0
            )

        from app.slices.calendar import services as svc

        payload: dict[str, Any] = {
            "project_ulid": project_ulid,
            "label": label,
            "source_kind": source_kind,
            "fund_archetype_key": fund_archetype_key,
            "expected_amount_cents": expected_amount_cents,
            "is_in_kind": bool(is_in_kind),
            "expected_sponsor_hint": expected_sponsor_hint,
            "notes": notes,
            "actor_ulid": actor_ulid,
            "request_id": request_id,
        }

        return svc.create_project_funding_plan(
            payload, actor_ulid=actor_ulid, request_id=request_id
        )

    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def list_project_funding_plans(
    *, project_ulid: str
) -> list[ProjectFundingPlanDTO]:
    """
    Contract entry point: list all funding plan lines for a project.

    This is a read-only view over Calendar.ProjectFundingPlan, used
    by Governance and Sponsors to understand planned funding sources.

    Args:
        project_ulid:
            ULID of the Calendar project.

    Returns:
        list[ProjectFundingPlanDTO]

    Raises:
        ContractError:
            - code="bad_argument" if project_ulid is malformed.
            - code="internal_error" for unexpected failures.
    """
    where = "calendar_v2.list_project_funding_plans"
    try:
        project_ulid = _require_ulid("project_ulid", project_ulid)

        from app.slices.calendar import services as svc

        return svc.list_funding_plans_for_project(project_ulid)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def list_projects_for_period(*, period_label: str) -> list[ProjectDTO]:
    """
    Contract entry point: list projects for a given period.

    Calendar owns the semantics of period_label (e.g. "2026",
    "FY2026"). Governance and Sponsors treat it as an opaque key.

    Args:
        period_label:
            Period/budget label used by Calendar & Governance.

    Returns:
        list[ProjectDTO]

    Raises:
        ContractError:
            - code="bad_argument" if period_label is blank.
            - code="internal_error" for unexpected failures.
    """
    where = "calendar_v2.list_projects_for_period"
    try:
        period_label = _require_str("period_label", period_label)

        from app.slices.calendar import services as svc

        return svc.list_projects_for_period(period_label)
    except Exception as exc:  # noqa: BLE001
        raise _as_contract_error(where, exc) from exc


__all__ = [
    "blackout_ok",
    "create_project",
    "create_project_funding_plan",
    "list_project_funding_plans",
    "list_projects_for_period",
]
