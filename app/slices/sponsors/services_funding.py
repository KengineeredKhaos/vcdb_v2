# app/slices/sponsors/services_funding.py

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.extensions import db, event_bus
from app.extensions.contracts import calendar_v2, finance_v2
from app.lib.chrono import now_iso8601_ms

from . import services_crm as crm_svc
from .mapper import (
    calendar_demand_to_opportunity_view,
    funding_context_to_detail_view,
    sponsor_funding_intent_to_view,
)
from .models import Sponsor, SponsorFundingIntent

_ALLOWED_INTENT_STATUS = {
    "draft",
    "committed",
    "withdrawn",
    "fulfilled",
}

_ALLOWED_INTENT_KIND = {
    "pledge",
    "donation",
    "pass_through",
}


def _require_status(status: str) -> str:
    if status not in _ALLOWED_INTENT_STATUS:
        raise ValueError(f"invalid sponsor funding intent status: {status}")
    return status


def _require_intent_kind(intent_kind: str) -> str:
    if intent_kind not in _ALLOWED_INTENT_KIND:
        raise ValueError(
            f"invalid sponsor funding intent kind: {intent_kind}"
        )
    return intent_kind


def _get_sponsor_or_raise(sponsor_entity_ulid: str) -> Sponsor:
    row = db.session.execute(
        select(Sponsor).where(Sponsor.entity_ulid == sponsor_entity_ulid)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"sponsor not found: {sponsor_entity_ulid}")
    return row


def _get_intent_or_raise(intent_ulid: str) -> SponsorFundingIntent:
    row = db.session.execute(
        select(SponsorFundingIntent).where(
            SponsorFundingIntent.ulid == intent_ulid
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"sponsor funding intent not found: {intent_ulid}")
    return row


def list_sponsors_for_form() -> list[tuple[str, str]]:
    rows = db.session.execute(
        select(Sponsor).order_by(Sponsor.entity_ulid.asc())
    ).scalars()
    return [(row.entity_ulid, row.entity_ulid) for row in rows]


def list_open_funding_opportunities() -> list:
    rows = calendar_v2.list_published_funding_demands()
    return [calendar_demand_to_opportunity_view(dto) for dto in rows]


def get_funding_opportunity(funding_demand_ulid: str):
    context = calendar_v2.get_funding_demand_context(funding_demand_ulid)
    totals = get_funding_intent_totals(funding_demand_ulid)
    money = finance_v2.get_funding_demand_money_view(funding_demand_ulid)
    return funding_context_to_detail_view(
        context,
        totals=totals,
        money=money,
    )


def create_funding_intent(
    payload: dict[str, Any],
    *,
    actor_ulid: str | None,
    request_id: str | None,
) -> SponsorFundingIntent:
    sponsor_entity_ulid = str(
        payload.get("sponsor_entity_ulid") or ""
    ).strip()
    funding_demand_ulid = str(
        payload.get("funding_demand_ulid") or ""
    ).strip()
    intent_kind = str(payload.get("intent_kind") or "").strip()
    amount_cents = int(payload.get("amount_cents") or 0)
    status = str(payload.get("status") or "").strip()
    note = payload.get("note")

    if not sponsor_entity_ulid:
        raise ValueError("sponsor_entity_ulid is required")
    if not funding_demand_ulid:
        raise ValueError("funding_demand_ulid is required")
    if amount_cents < 0:
        raise ValueError("amount_cents must be >= 0")

    _get_sponsor_or_raise(sponsor_entity_ulid)
    calendar_v2.get_funding_demand_context(funding_demand_ulid)
    _require_intent_kind(intent_kind)
    _require_status(status)

    row = SponsorFundingIntent(
        sponsor_entity_ulid=sponsor_entity_ulid,
        funding_demand_ulid=funding_demand_ulid,
        intent_kind=intent_kind,
        amount_cents=amount_cents,
        status=status,
        note=(str(note).strip() if note else None),
    )
    db.session.add(row)
    db.session.flush()

    event_bus.emit(
        domain="sponsors",
        operation="sponsor_funding_intent_created",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "sponsor_entity_ulid": row.sponsor_entity_ulid,
            "funding_demand_ulid": row.funding_demand_ulid,
        },
        changed={
            "fields": [
                "sponsor_entity_ulid",
                "funding_demand_ulid",
                "intent_kind",
                "amount_cents",
                "status",
                "note",
            ]
        },
    )
    return row


def update_funding_intent(
    intent_ulid: str,
    payload: dict[str, Any],
    *,
    actor_ulid: str | None,
    request_id: str | None,
) -> SponsorFundingIntent:
    row = _get_intent_or_raise(intent_ulid)

    sponsor_entity_ulid = str(
        payload.get("sponsor_entity_ulid") or ""
    ).strip()
    funding_demand_ulid = str(
        payload.get("funding_demand_ulid") or ""
    ).strip()
    intent_kind = str(payload.get("intent_kind") or "").strip()
    amount_cents = int(payload.get("amount_cents") or 0)
    status = str(payload.get("status") or "").strip()
    note = payload.get("note")

    if not sponsor_entity_ulid:
        raise ValueError("sponsor_entity_ulid is required")
    if not funding_demand_ulid:
        raise ValueError("funding_demand_ulid is required")
    if amount_cents < 0:
        raise ValueError("amount_cents must be >= 0")

    _get_sponsor_or_raise(sponsor_entity_ulid)
    calendar_v2.get_funding_demand_context(funding_demand_ulid)
    _require_intent_kind(intent_kind)
    _require_status(status)

    row.sponsor_entity_ulid = sponsor_entity_ulid
    row.funding_demand_ulid = funding_demand_ulid
    row.intent_kind = intent_kind
    row.amount_cents = amount_cents
    row.status = status
    row.note = str(note).strip() if note else None

    db.session.flush()

    event_bus.emit(
        domain="sponsors",
        operation="sponsor_funding_intent_updated",
        actor_ulid=actor_ulid,
        target_ulid=row.ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "sponsor_entity_ulid": row.sponsor_entity_ulid,
            "funding_demand_ulid": row.funding_demand_ulid,
        },
        changed={
            "fields": [
                "sponsor_entity_ulid",
                "funding_demand_ulid",
                "intent_kind",
                "amount_cents",
                "status",
                "note",
            ]
        },
    )
    return row


def get_funding_intent_view(intent_ulid: str):
    row = _get_intent_or_raise(intent_ulid)
    return sponsor_funding_intent_to_view(row)


def list_funding_intents_for_demand(funding_demand_ulid: str) -> list:
    rows = db.session.execute(
        select(SponsorFundingIntent)
        .where(
            SponsorFundingIntent.funding_demand_ulid == funding_demand_ulid
        )
        .order_by(
            SponsorFundingIntent.status.asc(),
            SponsorFundingIntent.created_at_utc.desc(),
        )
    ).scalars()
    return [sponsor_funding_intent_to_view(row) for row in rows]


def list_funding_intents_for_sponsor(sponsor_entity_ulid: str) -> list:
    rows = db.session.execute(
        select(SponsorFundingIntent)
        .where(
            SponsorFundingIntent.sponsor_entity_ulid == sponsor_entity_ulid
        )
        .order_by(
            SponsorFundingIntent.status.asc(),
            SponsorFundingIntent.created_at_utc.desc(),
        )
    ).scalars()
    return [sponsor_funding_intent_to_view(row) for row in rows]


def get_funding_intent_totals(
    funding_demand_ulid: str,
) -> dict[str, object]:
    pledged_statuses = ("committed", "fulfilled")
    pledge_kinds = ("pledge", "donation", "pass_through")

    rows = (
        db.session.execute(
            select(SponsorFundingIntent).where(
                SponsorFundingIntent.funding_demand_ulid
                == funding_demand_ulid,
                SponsorFundingIntent.status.in_(pledged_statuses),
                SponsorFundingIntent.intent_kind.in_(pledge_kinds),
            )
        )
        .scalars()
        .all()
    )

    pledged_cents = sum(int(row.amount_cents or 0) for row in rows)

    by_sponsor: dict[str, int] = {}
    for row in rows:
        sponsor_ulid = row.sponsor_entity_ulid
        if not sponsor_ulid:
            continue
        by_sponsor[sponsor_ulid] = by_sponsor.get(sponsor_ulid, 0) + int(
            row.amount_cents or 0
        )

    pledged_by_sponsor = [
        {
            "key": sponsor_ulid,
            "amount_cents": amount_cents,
        }
        for sponsor_ulid, amount_cents in sorted(by_sponsor.items())
    ]

    pledge_ulids = [
        row.ulid
        for row in rows
        if row.intent_kind in ("pledge", "pass_through")
    ]

    donation_ulids = [
        row.ulid for row in rows if row.intent_kind == "donation"
    ]

    return {
        "funding_demand_ulid": funding_demand_ulid,
        "pledged_cents": pledged_cents,
        "pledged_by_sponsor": pledged_by_sponsor,
        "pledge_ulids": pledge_ulids,
        "donation_ulids": donation_ulids,
    }


def list_opportunity_matches_for_demand(funding_demand_ulid: str):
    return crm_svc.list_opportunity_matches(funding_demand_ulid)
