# app/extensions/contracts/sponsors_v2.py
# -*- coding: utf-8 -*-
"""
Sponsors v2 — typed, PII-free contract.

This contract is the stable interface other slices/CLIs should import:
    from app.extensions.contracts import sponsors_v2 as sponsors

It validates basic argument presence/shape (lightly), calls slice services,
and shapes PII-free return dicts. All DB changes + ledger emits happen
inside the Sponsors services layer.

Breaking changes should ship as sponsors_v3; leave v2 callable.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, TypedDict

from sqlalchemy.orm import Session

from app.extensions.contracts.entity_v2 import get_entity_card
from app.extensions.errors import ContractError
from app.slices.sponsors import services as svc
from app.slices.sponsors.models import SponsorPOC

# ---------- classes ----------


class SponsorPolicyDTO(TypedDict):
    sponsor_ulid: str
    constraints: dict
    caps: dict
    expiry_days: int


__schema__ = {
    "get_policy": {
        "requires": ["sponsor_ulid"],
        "returns_keys": [
            "sponsor_ulid",
            "constraints",
            "caps",
            "expiry_days",
        ],
    }
}


# -------- ContractError ------


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


# ---------- helpers ----------


def _ok(payload: Mapping[str, Any] | None = None) -> dict:
    return {"ok": True, "data": {} if payload is None else dict(payload)}


def _one(name: str, value: Any) -> dict:
    return {"ok": True, "data": {name: value}}


def _require_str(name: str, value: Optional[str]) -> str:
    if not value or not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _require_ulid(name: str, value: Optional[str]) -> str:
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


# ---------- v2 API (typed, keyword-only) ----------


def get_policy(sponsor_ulid: str) -> SponsorPolicyDTO:
    return {
        "sponsor_ulid": sponsor_ulid,
        "constraints": {
            "veteran_only": False,
            "homeless_only": False,
            "local_only": False,
        },
        "caps": {"total_cents": 0, "food_cap_cents": 0},
        "expiry_days": 45,
    }


def create_sponsor(
    *, entity_ulid: str, request_id: str, actor_ulid: Optional[str]
) -> dict:
    where = "sponsors_v2.create_sponsor"
    try:
        entity_ulid = _require_ulid("entity_ulid", entity_ulid)
        request_id = _require_ulid("request_id", request_id)
        sid = svc.ensure_sponsor(
            entity_ulid=entity_ulid,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return _one("sponsor_ulid", sid)
    except Exception as exc:
        raise _as_contract_error(where, exc)


def upsert_capabilities(
    *,
    sponsor_ulid: str,
    capabilities: dict,
    request_id: str,
    actor_ulid: Optional[str],
) -> dict:
    where = "sponsors_v2.upsert_capabilities"
    try:
        sponsor_ulid = _require_ulid("sponsor_ulid", sponsor_ulid)
        request_id = _require_ulid("request_id", request_id)
        if not isinstance(capabilities, dict):
            raise ValueError(
                "capabilities must be an object mapping 'domain.key' -> {has[,note]}"
            )
        hist = svc.upsert_capabilities(
            sponsor_ulid=sponsor_ulid,
            payload=capabilities,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        view = svc.sponsor_view(sponsor_ulid)
        return _ok({"history_ulid": hist, "sponsor": view})
    except Exception as exc:
        raise _as_contract_error(where, exc)


def patch_capabilities(
    *,
    sponsor_ulid: str,
    capabilities: dict,
    request_id: str,
    actor_ulid: Optional[str],
) -> dict:
    where = "sponsors_v2.patch_capabilities"
    try:
        sponsor_ulid = _require_ulid("sponsor_ulid", sponsor_ulid)
        request_id = _require_ulid("request_id", request_id)
        if not isinstance(capabilities, dict):
            raise ValueError(
                "capabilities must be an object mapping 'domain.key' -> {has[,note]}"
            )
        hist = svc.patch_capabilities(
            sponsor_ulid=sponsor_ulid,
            payload=capabilities,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        view = svc.sponsor_view(sponsor_ulid)
        return _ok({"history_ulid": hist, "sponsor": view})
    except Exception as exc:
        raise _as_contract_error(where, exc)


def pledge_upsert(
    *,
    sponsor_ulid: str,
    pledge: dict,
    request_id: str,
    actor_ulid: Optional[str],
) -> dict:
    where = "sponsors_v2.pledge_upsert"
    try:
        sponsor_ulid = _require_ulid("sponsor_ulid", sponsor_ulid)
        request_id = _require_ulid("request_id", request_id)
        if not isinstance(pledge, dict):
            raise ValueError("pledge must be an object")
        pid = svc.upsert_pledge(
            sponsor_ulid=sponsor_ulid,
            pledge=pledge,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        view = svc.sponsor_view(sponsor_ulid)
        return _ok({"pledge_ulid": pid, "sponsor": view})
    except Exception as exc:
        raise _as_contract_error(where, exc)


def pledge_set_status(
    *,
    pledge_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: Optional[str],
) -> dict:
    where = "sponsors_v2.pledge_set_status"
    try:
        pledge_ulid = _require_ulid("pledge_ulid", pledge_ulid)
        status = _require_str("status", status).lower()
        request_id = _require_ulid("request_id", request_id)
        svc.set_pledge_status(
            pledge_ulid=pledge_ulid,
            status=status,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return _ok({})
    except Exception as exc:
        raise _as_contract_error(where, exc)


def get_profile(*, sponsor_ulid: str) -> dict:
    where = "sponsors_v2.get_profile"
    try:
        sponsor_ulid = _require_ulid("sponsor_ulid", sponsor_ulid)
        view = svc.sponsor_view(sponsor_ulid)
        if view is None:
            raise ValueError("sponsor not found")
        return _ok(view)
    except Exception as exc:
        raise _as_contract_error(where, exc)


# ---------------- Sponsor POC workings -------------------


def get_org_poc_cards(sess: Session, org_ulid: str) -> list[dict]:
    rows = (
        sess.query(SponsorPOC)
        .filter(SponsorPOC.org_ulid == org_ulid, SponsorPOC.relation == "poc")
        .order_by(
            SponsorPOC.active.desc(),
            SponsorPOC.scope.asc(),
            SponsorPOC.rank.asc(),
        )
        .all()
    )
    cards = []
    for r in rows:
        person = get_entity_card(sess, r.person_entity_ulid)
        cards.append(
            {
                "link": {
                    "org_ulid": r.org_ulid,
                    "person_entity_ulid": r.person_entity_ulid,
                    "relation": r.relation,
                    "scope": r.scope,
                    "rank": r.rank,
                    "is_primary": r.is_primary,
                    "org_role": r.org_role,
                    "valid_from_utc": r.valid_from_utc,
                    "valid_to_utc": r.valid_to_utc,
                    "active": r.active,
                },
                "person": person.__dict__,
            }
        )
    return cards
