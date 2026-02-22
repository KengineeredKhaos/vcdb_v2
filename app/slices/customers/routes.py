# app/slices/customers/routes.py
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from flask import Blueprint, jsonify, redirect, url_for

from app.extensions.contracts import customers_v2
from app.extensions.errors import ContractError
from app.lib.request_ctx import ensure_request_id

bp = Blueprint(
    "customers",
    __name__,
    template_folder="templates",
    static_folder=None,
    url_prefix="/customers",
)

"""
TODO:

In all Intake/Update routes:

Invariant: if created is True, noop must be False.
Invariant: if noop is True, changed_fields must be empty.

Enforce that in a small constructor helper.

@dataclass(frozen=True, slots=True)
class ChangeSetDTO:
    entity_ulid: str
    created: bool
    noop: bool
    changed_fields: tuple[str, ...]
    next_step: str | None

Typical route behavior becomes mechanical:

if stale nonce → redirect (no call)
call service → get ChangeSetDTO

if dto.noop → commit/redirect, no ledger
else → commit, ledger emit with changed_fields, redirect

Minimal Canonical Route Set:

Start / resume
GET /customers/intake/start/<entity_ulid>
calls ensure_customer_facets(...)
commit
redirect to wizard_next_step(entity_ulid)

Step: eligibility
GET /customers/intake/<entity_ulid>/eligibility
POST /customers/intake/<entity_ulid>/eligibility

Steps: needs tier blocks
GET/POST /customers/intake/<entity_ulid>/needs/tier1
GET/POST /customers/intake/<entity_ulid>/needs/tier2
GET/POST /customers/intake/<entity_ulid>/needs/tier3

plus optional:

POST /customers/intake/<entity_ulid>/needs/skip
POST /customers/intake/<entity_ulid>/needs/complete

Review
GET /customers/intake/<entity_ulid>/review
POST /customers/intake/<entity_ulid>/confirm

Customer card view
GET /customers/<entity_ulid>
uses get_customer_dashboard(...) and list_customer_history(...)
renders template (not JSON)

Remove each route from this docstring after it is ewstablished.

"""

# -----------------
# JSON API Helpers
# -----------------


def _ok(*, request_id: str, data: Any = None, status: int = 200, **extra):
    payload = {"ok": True, "request_id": request_id, "data": data, **extra}
    return jsonify(payload), status


def _err(*, request_id: str, exc: Exception | str, code: int = 500):
    if isinstance(exc, ContractError):
        payload = {
            "ok": False,
            "request_id": request_id,
            "error": exc.message,
            "code": exc.code,
            "where": exc.where,
        }
        if getattr(exc, "data", None):
            payload["data"] = exc.data
        return jsonify(payload), exc.http_status

    if isinstance(exc, NotImplementedError):
        return (
            jsonify(
                {
                    "ok": False,
                    "request_id": request_id,
                    "error": "not implemented",
                }
            ),
            501,
        )
    if isinstance(exc, PermissionError):
        return (
            jsonify(
                {"ok": False, "request_id": request_id, "error": str(exc)}
            ),
            403,
        )
    if isinstance(exc, LookupError):
        return (
            jsonify(
                {"ok": False, "request_id": request_id, "error": str(exc)}
            ),
            404,
        )
    if isinstance(exc, ValueError):
        return (
            jsonify(
                {"ok": False, "request_id": request_id, "error": str(exc)}
            ),
            400,
        )

    return (
        jsonify({"ok": False, "request_id": request_id, "error": str(exc)}),
        code,
    )


def _dto_to_dict(dto: Any) -> Any:
    if dto is None:
        return None
    if isinstance(dto, dict):
        return dto
    if is_dataclass(dto):
        return asdict(dto)
    return dto


def _reject_legacy_keys(payload: dict[str, Any]) -> None:
    legacy: list[str] = []
    if "customer_ulid" in payload:
        legacy.append("customer_ulid")
    if "ulid" in payload:
        legacy.append("ulid")
    if legacy:
        raise ValueError(
            f"legacy key(s) not allowed: {', '.join(legacy)}; use entity_ulid"
        )


# -----------------
# Wizard Routes
# -----------------


@bp.get("/intake/start/<entity_ulid>")
def intake_start(entity_ulid: str):
    customers_v2.ensure_customer_facets(
        entity_ulid=entity_ulid, request_id=request_id, actor_ulid=actor_ulid
    )

    # later: redirect into your real step route, e.g. eligibility
    return redirect(url_for("customers.intake_step", entity_ulid=entity_ulid))


@bp.get("/<entity_ulid>")
def view_customer(entity_ulid: str):
    from . import services as cust_svc

    req = ensure_request_id()
    try:
        dto = cust_svc.get_dashboard_view(entity_ulid=entity_ulid)
        if not dto:
            raise LookupError("not found")
        return next_template
    except Exception as exc:
        return _err(request_id=req, exc=exc)


@bp.get("/<entity_ulid>/eligibility")
def get_eligibility(entity_ulid: str):
    from . import services as cust_svc

    req = ensure_request_id()
    try:
        dto = cust_svc.get_eligibility_snapshot(entity_ulid=entity_ulid)
        if not dto:
            raise LookupError("not found")
        return _ok(request_id=req, data=_dto_to_dict(dto))
    except Exception as exc:
        return _err(request_id=req, exc=exc)
