# tests/slices/ledger/test_ledger_services.py

from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.slices.ledger import services as svc
from app.slices.ledger.errors import LedgerBadArgument, LedgerUnavailable
from app.slices.ledger.models import LedgerEvent


def test_append_event_flushes_row_and_sets_chain_fields(app):
    with app.app_context():
        row = svc.append_event(
            domain="ledger",
            operation="smoke_event",
            request_id="01REQREQREQREQREQREQREQRE",
            actor_ulid="01ACTORACTORACTORACTORACT",
            target_ulid="01TARGETTARGETTARGETTARGET",
            refs={"subject_ulid": "01SUBJECTSUBJECTSUBJECTSUB"},
            changed={"fields": ["status"]},
            meta={"source": "test"},
            chain_key="ledger_smoke",
        )

        stored = db.session.get(LedgerEvent, row.ulid)
        assert stored is not None
        assert stored.event_type == "ledger.smoke_event"
        assert stored.chain_key == "ledger_smoke"


def test_append_event_rejects_blank_request_id(app):
    with app.app_context():
        with pytest.raises(LedgerBadArgument):
            svc.append_event(
                domain="ledger",
                operation="smoke_event",
                request_id="",
                actor_ulid=None,
                target_ulid=None,
            )


def test_append_event_wraps_sqlalchemy_failure(app, monkeypatch):
    with app.app_context():

        def _boom():
            raise SQLAlchemyError("db down")

        monkeypatch.setattr(svc.db.session, "flush", _boom)

        with pytest.raises(LedgerUnavailable):
            svc.append_event(
                domain="ledger",
                operation="smoke_event",
                request_id="01REQREQREQREQREQREQREQRE",
                actor_ulid=None,
                target_ulid=None,
            )


def test_verify_chain_reports_ok_for_filtered_chain(app):
    with app.app_context():
        svc.append_event(
            domain="ledger",
            operation="first_event",
            request_id="01REQREQREQREQREQREQREQ01",
            actor_ulid=None,
            target_ulid=None,
            chain_key="ledger_verify",
        )
        svc.append_event(
            domain="ledger",
            operation="second_event",
            request_id="01REQREQREQREQREQREQREQ02",
            actor_ulid=None,
            target_ulid=None,
            chain_key="ledger_verify",
        )

        result = svc.verify_chain(chain_key="ledger_verify")

        assert result["ok"] is True
        assert result["broken"] is None
        assert result["checked"] == 2
        assert result["chains"] == ["ledger_verify"]
