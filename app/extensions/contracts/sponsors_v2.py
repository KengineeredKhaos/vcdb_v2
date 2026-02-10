# app/extensions/contracts/sponsors_v2.py
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.extensions.errors import ContractError
from app.lib.ids import new_ulid

# -----------------------------------------------------------------------------
# error helper (tolerate minor ContractError signature drift)
# -----------------------------------------------------------------------------


def _ce(code: str, msg: str, http_status: int | None = None) -> Exception:
    try:
        if http_status is None:
            return ContractError(code, msg)
        return ContractError(code, msg, http_status=http_status)
    except TypeError:
        try:
            if http_status is None:
                return ContractError("sponsors_v2", code, msg)
            return ContractError(
                "sponsors_v2", code, msg, http_status=http_status
            )
        except TypeError:
            if code == "not_found":
                return LookupError(msg)
            return ValueError(msg)


def _wrap(where: str, fn):
    try:
        return fn()
    except ContractError:
        raise
    except LookupError as exc:
        raise _ce("not_found", f"{where}: {exc}", http_status=404)
    except ValueError as exc:
        raise _ce("invalid_input", f"{where}: {exc}", http_status=400)
    except Exception as exc:
        raise _ce(
            "internal_error",
            f"{where}: unexpected error: {exc}",
            http_status=500,
        )


# -----------------------------------------------------------------------------
# contract surface
# -----------------------------------------------------------------------------

WHERE_ENSURE_SPONSOR = "sponsors_v2.ensure_sponsor"
WHERE_UPSERT_CAPS = "sponsors_v2.upsert_capabilities"
WHERE_PROMOTE = "sponsors_v2.promote_if_clean"
WHERE_CUES = "sponsors_v2.get_sponsor_cues"
WHERE_UPSERT_PLEDGE = "sponsors_v2.upsert_pledge"
WHERE_SET_PLEDGE_STATUS = "sponsors_v2.set_pledge_status"


def ensure_sponsor(
    *,
    entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> dict[str, Any]:
    def _run():
        from app.slices.sponsors import services as sp_svc  # local import

        return {
            "ok": True,
            "data": sp_svc.ensure_sponsor(
                entity_ulid=entity_ulid,
                actor_ulid=(actor_ulid or "system"),
                request_id=(request_id or "").strip() or new_ulid(),
            ),
        }

    return _wrap(WHERE_ENSURE_SPONSOR, _run)


def upsert_capabilities(
    *,
    sponsor_ulid: str,
    capabilities: Mapping[str, Any],
    note: str | None,
    request_id: str,
    actor_ulid: str | None,
) -> dict[str, Any]:
    def _run():
        caps = capabilities or {}
        codes = [k for (k, v) in caps.items() if bool(v)]
        from app.slices.sponsors import services as sp_svc  # local import

        return {
            "ok": True,
            "data": sp_svc.upsert_capabilities(
                sponsor_ulid=sponsor_ulid,
                codes=codes,
                note=(note or "").strip() or None,
                actor_ulid=(actor_ulid or "system"),
                request_id=(request_id or "").strip() or new_ulid(),
            ),
        }

    return _wrap(WHERE_UPSERT_CAPS, _run)


def promote_if_clean(
    *,
    sponsor_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> dict[str, Any]:
    def _run():
        from app.slices.sponsors import services as sp_svc  # local import

        return {
            "ok": True,
            "data": sp_svc.promote_if_clean(
                sponsor_ulid=sponsor_ulid,
                actor_ulid=(actor_ulid or "system"),
                request_id=(request_id or "").strip() or new_ulid(),
            ),
        }

    return _wrap(WHERE_PROMOTE, _run)


def get_sponsor_cues(
    *,
    sponsor_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> dict[str, Any]:
    def _run():
        from app.slices.sponsors import services as sp_svc  # local import

        # request_id/actor_ulid currently unused, but kept for contract uniformity
        return {"ok": True, "data": sp_svc.get_sponsor_cues(sponsor_ulid)}

    return _wrap(WHERE_CUES, _run)


def upsert_pledge(
    *,
    sponsor_ulid: str,
    payload: Mapping[str, Any],
    request_id: str,
    actor_ulid: str | None,
) -> dict[str, Any]:
    def _run():
        p = payload or {}
        pledge_type = (p.get("pledge_type") or "").strip()
        amount_cents = int(p.get("amount_cents") or 0)
        currency = (p.get("currency") or "USD").strip()
        status = (p.get("status") or "proposed").strip()
        note = (p.get("notes") or p.get("note") or "").strip() or None

        from app.slices.sponsors import services as sp_svc  # local import

        return {
            "ok": True,
            "data": sp_svc.upsert_pledge(
                sponsor_ulid=sponsor_ulid,
                pledge_type=pledge_type,
                amount_cents=amount_cents,
                currency=currency,
                status=status,
                note=note,
                actor_ulid=(actor_ulid or "system"),
                request_id=(request_id or "").strip() or new_ulid(),
            ),
        }

    return _wrap(WHERE_UPSERT_PLEDGE, _run)


def set_pledge_status(
    *,
    sponsor_ulid: str,
    pledge_ulid: str,
    status: str,
    request_id: str,
    actor_ulid: str | None,
) -> dict[str, Any]:
    def _run():
        from app.slices.sponsors import services as sp_svc  # local import

        return {
            "ok": True,
            "data": sp_svc.set_pledge_status(
                sponsor_ulid=sponsor_ulid,
                pledge_ulid=pledge_ulid,
                status=status,
                actor_ulid=(actor_ulid or "system"),
                request_id=(request_id or "").strip() or new_ulid(),
            ),
        }

    return _wrap(WHERE_SET_PLEDGE_STATUS, _run)


__all__ = [
    "ensure_sponsor",
    "upsert_capabilities",
    "promote_if_clean",
    "get_sponsor_cues",
    "upsert_pledge",
    "set_pledge_status",
]
