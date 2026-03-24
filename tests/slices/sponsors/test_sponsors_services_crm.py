# tests/slices/sponsors/test_sponsors_services_crm.py

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.extensions import db
from app.slices.entity.models import Entity, EntityOrg
from app.slices.ledger.models import LedgerEvent
from app.slices.sponsors.models import (
    Sponsor,
    SponsorCRMFactorIndex,
    SponsorHistory,
)
from app.slices.sponsors.services_crm import (
    CRM_SECTION,
    get_crm_factors,
    set_crm_factors,
)


def _create_sponsor(name: str) -> Sponsor:
    entity = Entity(kind="org")
    db.session.add(entity)
    db.session.flush()

    db.session.add(
        EntityOrg(
            entity_ulid=entity.ulid,
            legal_name=name,
        )
    )

    sponsor = Sponsor(entity_ulid=entity.ulid)
    db.session.add(sponsor)
    db.session.flush()
    return sponsor


def _history_rows(sponsor_entity_ulid: str) -> list[SponsorHistory]:
    return (
        db.session.execute(
            select(SponsorHistory)
            .where(
                SponsorHistory.sponsor_entity_ulid == sponsor_entity_ulid,
                SponsorHistory.section == CRM_SECTION,
            )
            .order_by(SponsorHistory.version.asc())
        )
        .scalars()
        .all()
    )


def _factor_rows(
    sponsor_entity_ulid: str,
) -> list[SponsorCRMFactorIndex]:
    return (
        db.session.execute(
            select(SponsorCRMFactorIndex)
            .where(
                SponsorCRMFactorIndex.sponsor_entity_ulid
                == sponsor_entity_ulid
            )
            .order_by(
                SponsorCRMFactorIndex.bucket.asc(),
                SponsorCRMFactorIndex.key.asc(),
            )
        )
        .scalars()
        .all()
    )


def test_set_crm_factors_writes_history_and_projection(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Storage Sponsor")

        hist_ulid = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_housing": True,
                "style_reimbursement": {
                    "has": True,
                    "strength": "recurring",
                    "source": "observed",
                    "note": "Usually prefers receipts-backed requests.",
                },
                "friction_board_review": {
                    "has": True,
                    "strength": "observed",
                    "source": "operator",
                },
            },
            actor_ulid=None,
            request_id="req-crm-write-1",
        )
        db.session.flush()

        assert hist_ulid is not None

        rows = _history_rows(sponsor.entity_ulid)
        assert len(rows) == 1
        assert rows[0].section == CRM_SECTION
        assert rows[0].version == 1

        data = json.loads(rows[0].data_json)
        assert data["mission_housing"]["has"] is True
        assert data["mission_housing"]["strength"] == "observed"
        assert data["mission_housing"]["source"] == "operator"

        assert data["style_reimbursement"]["has"] is True
        assert data["style_reimbursement"]["strength"] == "recurring"
        assert data["style_reimbursement"]["source"] == "observed"
        assert "note" in data["style_reimbursement"]

        idx = _factor_rows(sponsor.entity_ulid)
        assert len(idx) == 3

        by_key = {row.key: row for row in idx}

        assert by_key["mission_housing"].bucket == "mission"
        assert by_key["mission_housing"].active is True
        assert by_key["mission_housing"].strength == "observed"
        assert by_key["mission_housing"].source == "operator"

        assert by_key["style_reimbursement"].bucket == "style"
        assert by_key["style_reimbursement"].active is True
        assert by_key["style_reimbursement"].strength == "recurring"
        assert by_key["style_reimbursement"].source == "observed"

        assert by_key["friction_board_review"].bucket == "friction"
        assert by_key["friction_board_review"].active is True

        sponsor_row = db.session.get(Sponsor, sponsor.entity_ulid)
        assert sponsor_row is not None
        assert sponsor_row.last_touch_utc is not None

        ledger_row = (
            db.session.execute(
                select(LedgerEvent).where(
                    LedgerEvent.target_ulid == sponsor.entity_ulid,
                    LedgerEvent.event_type == "sponsors.crm_factors_update",
                )
            )
            .scalars()
            .one_or_none()
        )
        assert ledger_row is not None


def test_set_crm_factors_boolean_payload_uses_defaults(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Boolean Defaults Sponsor")

        hist_ulid = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_local_veterans": True,
            },
            actor_ulid=None,
            request_id="req-crm-bool-defaults",
        )
        db.session.flush()

        assert hist_ulid is not None

        snap = get_crm_factors(sponsor.entity_ulid)
        assert snap["mission_local_veterans"]["has"] is True
        assert snap["mission_local_veterans"]["strength"] == "observed"
        assert snap["mission_local_veterans"]["source"] == "operator"

        idx = _factor_rows(sponsor.entity_ulid)
        assert len(idx) == 1
        assert idx[0].key == "mission_local_veterans"
        assert idx[0].bucket == "mission"
        assert idx[0].strength == "observed"
        assert idx[0].source == "operator"


def test_set_crm_factors_rejects_invalid_factor_key(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Invalid Key Sponsor")

        with pytest.raises(ValueError) as exc:
            set_crm_factors(
                sponsor_entity_ulid=sponsor.entity_ulid,
                payload={
                    "mission_space_lasers": True,
                },
                actor_ulid=None,
                request_id="req-crm-invalid-key",
            )

        assert "invalid crm factor keys" in str(exc.value).lower()

        assert _history_rows(sponsor.entity_ulid) == []
        assert _factor_rows(sponsor.entity_ulid) == []


def test_set_crm_factors_rejects_invalid_strength(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Invalid Strength Sponsor")

        with pytest.raises(ValueError) as exc:
            set_crm_factors(
                sponsor_entity_ulid=sponsor.entity_ulid,
                payload={
                    "mission_housing": {
                        "has": True,
                        "strength": "extreme",
                        "source": "operator",
                    }
                },
                actor_ulid=None,
                request_id="req-crm-invalid-strength",
            )

        assert "invalid crm factor strength" in str(exc.value).lower()

        assert _history_rows(sponsor.entity_ulid) == []
        assert _factor_rows(sponsor.entity_ulid) == []


def test_set_crm_factors_rejects_invalid_source(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Invalid Source Sponsor")

        with pytest.raises(ValueError) as exc:
            set_crm_factors(
                sponsor_entity_ulid=sponsor.entity_ulid,
                payload={
                    "mission_housing": {
                        "has": True,
                        "strength": "observed",
                        "source": "tea_leaves",
                    }
                },
                actor_ulid=None,
                request_id="req-crm-invalid-source",
            )

        assert "invalid crm factor source" in str(exc.value).lower()

        assert _history_rows(sponsor.entity_ulid) == []
        assert _factor_rows(sponsor.entity_ulid) == []


def test_set_crm_factors_noop_returns_none_for_identical_payload(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Noop Sponsor")

        payload = {
            "mission_housing": {
                "has": True,
                "strength": "recurring",
                "source": "observed",
            },
            "style_cash_grant": True,
        }

        first = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload=payload,
            actor_ulid=None,
            request_id="req-crm-noop-1",
        )
        db.session.flush()

        second = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload=payload,
            actor_ulid=None,
            request_id="req-crm-noop-2",
        )
        db.session.flush()

        assert first is not None
        assert second is None

        rows = _history_rows(sponsor.entity_ulid)
        assert len(rows) == 1
        assert rows[0].version == 1

        idx = _factor_rows(sponsor.entity_ulid)
        assert len(idx) == 2


def test_set_crm_factors_replacement_removes_dropped_keys_from_index(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Replacement Sponsor")

        first = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_housing": True,
                "style_reimbursement": True,
                "friction_board_review": True,
            },
            actor_ulid=None,
            request_id="req-crm-replace-1",
        )
        db.session.flush()
        assert first is not None

        rows = _factor_rows(sponsor.entity_ulid)
        assert {row.key for row in rows} == {
            "mission_housing",
            "style_reimbursement",
            "friction_board_review",
        }

        second = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_housing": True,
                "style_reimbursement": True,
            },
            actor_ulid=None,
            request_id="req-crm-replace-2",
        )
        db.session.flush()
        assert second is not None

        hist = _history_rows(sponsor.entity_ulid)
        assert len(hist) == 2
        assert hist[-1].version == 2

        rows = _factor_rows(sponsor.entity_ulid)
        assert {row.key for row in rows} == {
            "mission_housing",
            "style_reimbursement",
        }


def test_set_crm_factors_keeps_has_false_in_history_but_marks_index_inactive(
    app,
):
    with app.app_context():
        sponsor = _create_sponsor("CRM Inactive Factor Sponsor")

        hist_ulid = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "friction_manual_review_common": {
                    "has": False,
                    "strength": "observed",
                    "source": "operator",
                    "note": "No longer a common pattern.",
                },
                "relationship_prior_success": True,
            },
            actor_ulid=None,
            request_id="req-crm-inactive-1",
        )
        db.session.flush()

        assert hist_ulid is not None

        snap = get_crm_factors(sponsor.entity_ulid)
        assert "friction_manual_review_common" in snap
        assert snap["friction_manual_review_common"]["has"] is False
        assert snap["relationship_prior_success"]["has"] is True

        rows = _factor_rows(sponsor.entity_ulid)
        assert len(rows) == 2

        by_key = {row.key: row for row in rows}
        assert by_key["friction_manual_review_common"].bucket == "friction"
        assert by_key["friction_manual_review_common"].active is False
        assert by_key["relationship_prior_success"].bucket == "relationship"
        assert by_key["relationship_prior_success"].active is True


def test_crm_factor_rows_cascade_on_sponsor_delete(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Cascade Sponsor")

        hist_ulid = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_housing": True,
                "style_cash_grant": True,
            },
            actor_ulid=None,
            request_id="req-crm-cascade-1",
        )
        db.session.flush()

        assert hist_ulid is not None
        assert len(_history_rows(sponsor.entity_ulid)) == 1
        assert len(_factor_rows(sponsor.entity_ulid)) == 2

        db.session.delete(sponsor)
        db.session.flush()

        assert db.session.get(Sponsor, sponsor.entity_ulid) is None
        assert _history_rows(sponsor.entity_ulid) == []
        assert _factor_rows(sponsor.entity_ulid) == []
