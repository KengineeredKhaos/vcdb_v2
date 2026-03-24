# tests/slices/sponsors/test_sponsors_services_crm_patch.py

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.extensions import db
from app.slices.entity.models import Entity, EntityOrg
from app.slices.sponsors.models import (
    Sponsor,
    SponsorCRMFactorIndex,
    SponsorHistory,
)
from app.slices.sponsors.services_crm import (
    CRM_SECTION,
    get_crm_factors,
    patch_crm_factors,
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


def test_patch_crm_factors_adds_new_factor(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Patch Add Sponsor")

        first = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_housing": True,
            },
            actor_ulid=None,
            request_id="req-crm-patch-add-1",
        )
        db.session.flush()
        assert first is not None

        second = patch_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "style_reimbursement": {
                    "has": True,
                    "strength": "recurring",
                    "source": "observed",
                    "note": "Frequently asks for receipts.",
                }
            },
            actor_ulid=None,
            request_id="req-crm-patch-add-2",
        )
        db.session.flush()
        assert second is not None

        hist = _history_rows(sponsor.entity_ulid)
        assert len(hist) == 2
        assert hist[-1].version == 2

        snap = get_crm_factors(sponsor.entity_ulid)
        assert set(snap.keys()) == {
            "mission_housing",
            "style_reimbursement",
        }

        rows = _factor_rows(sponsor.entity_ulid)
        assert {row.key for row in rows} == {
            "mission_housing",
            "style_reimbursement",
        }


def test_patch_crm_factors_updates_existing_factor_metadata(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Patch Update Sponsor")

        first = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "style_reimbursement": True,
            },
            actor_ulid=None,
            request_id="req-crm-patch-update-1",
        )
        db.session.flush()
        assert first is not None

        second = patch_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "style_reimbursement": {
                    "has": True,
                    "strength": "strong_pattern",
                    "source": "observed",
                    "note": "Very consistent reimbursement history.",
                }
            },
            actor_ulid=None,
            request_id="req-crm-patch-update-2",
        )
        db.session.flush()
        assert second is not None

        snap = get_crm_factors(sponsor.entity_ulid)
        item = snap["style_reimbursement"]
        assert item["has"] is True
        assert item["strength"] == "strong_pattern"
        assert item["source"] == "observed"
        assert item["note"] == "Very consistent reimbursement history."

        row = _factor_rows(sponsor.entity_ulid)[0]
        assert row.key == "style_reimbursement"
        assert row.active is True
        assert row.strength == "strong_pattern"
        assert row.source == "observed"


def test_patch_crm_factors_false_keeps_factor_but_marks_inactive(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Patch Inactive Sponsor")

        first = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "friction_board_review": True,
                "mission_housing": True,
            },
            actor_ulid=None,
            request_id="req-crm-patch-inactive-1",
        )
        db.session.flush()
        assert first is not None

        second = patch_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "friction_board_review": False,
            },
            actor_ulid=None,
            request_id="req-crm-patch-inactive-2",
        )
        db.session.flush()
        assert second is not None

        snap = get_crm_factors(sponsor.entity_ulid)
        assert snap["friction_board_review"]["has"] is False
        assert snap["friction_board_review"]["strength"] == "observed"
        assert snap["friction_board_review"]["source"] == "operator"

        rows = {row.key: row for row in _factor_rows(sponsor.entity_ulid)}
        assert rows["friction_board_review"].active is False
        assert rows["mission_housing"].active is True


def test_patch_crm_factors_none_removes_factor_entirely(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Patch Remove Sponsor")

        first = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_housing": True,
                "style_cash_grant": True,
            },
            actor_ulid=None,
            request_id="req-crm-patch-remove-1",
        )
        db.session.flush()
        assert first is not None

        second = patch_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "style_cash_grant": None,
            },
            actor_ulid=None,
            request_id="req-crm-patch-remove-2",
        )
        db.session.flush()
        assert second is not None

        snap = get_crm_factors(sponsor.entity_ulid)
        assert set(snap.keys()) == {"mission_housing"}
        assert "style_cash_grant" not in snap

        rows = _factor_rows(sponsor.entity_ulid)
        assert {row.key for row in rows} == {"mission_housing"}

        hist = _history_rows(sponsor.entity_ulid)
        latest = json.loads(hist[-1].data_json)
        assert "style_cash_grant" not in latest


def test_patch_crm_factors_noop_returns_none(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Patch Noop Sponsor")

        first = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_local_veterans": {
                    "has": True,
                    "strength": "recurring",
                    "source": "observed",
                }
            },
            actor_ulid=None,
            request_id="req-crm-patch-noop-1",
        )
        db.session.flush()
        assert first is not None

        second = patch_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_local_veterans": {
                    "has": True,
                    "strength": "recurring",
                    "source": "observed",
                }
            },
            actor_ulid=None,
            request_id="req-crm-patch-noop-2",
        )
        db.session.flush()

        assert second is None

        hist = _history_rows(sponsor.entity_ulid)
        assert len(hist) == 1
        assert hist[0].version == 1


def test_patch_crm_factors_rejects_invalid_key(app):
    with app.app_context():
        sponsor = _create_sponsor("CRM Patch Invalid Key Sponsor")

        first = set_crm_factors(
            sponsor_entity_ulid=sponsor.entity_ulid,
            payload={
                "mission_housing": True,
            },
            actor_ulid=None,
            request_id="req-crm-patch-invalid-1",
        )
        db.session.flush()
        assert first is not None

        with pytest.raises(ValueError) as exc:
            patch_crm_factors(
                sponsor_entity_ulid=sponsor.entity_ulid,
                payload={
                    "mission_deep_space": True,
                },
                actor_ulid=None,
                request_id="req-crm-patch-invalid-2",
            )

        assert "invalid crm factor keys" in str(exc.value).lower()

        snap = get_crm_factors(sponsor.entity_ulid)
        assert set(snap.keys()) == {"mission_housing"}
