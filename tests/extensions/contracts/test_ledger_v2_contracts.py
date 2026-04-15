# tests/extensions/contracts/test_ledger_v2_contracts.py

from __future__ import annotations

import pytest

from app.extensions.contracts import ledger_v2
from app.extensions.errors import ContractError
from app.slices.ledger.errors import (
    LedgerBadArgument,
    LedgerUnavailable,
)


def test_emit_returns_emit_result(monkeypatch):
    class _Row:
        ulid = "01LEDGERROWROWROWROWROWRO"
        event_type = "entity.operator_core_created"
        chain_key = "entity"

    monkeypatch.setattr(
        ledger_v2.ledger_svc,
        "append_event",
        lambda **kwargs: _Row(),
    )

    result = ledger_v2.emit(
        domain="entity",
        operation="operator_core_created",
        request_id="01REQREQREQREQREQREQREQRE",
        actor_ulid="01ACTORACTORACTORACTORACT",
        target_ulid="01TARGETTARGETTARGETTARGET",
    )

    assert result.ok is True
    assert result.event_id == "01LEDGERROWROWROWROWROWRO"
    assert result.event_type == "entity.operator_core_created"
    assert result.chain_key == "entity"


def test_emit_maps_bad_argument(monkeypatch):
    def _boom(**kwargs):
        raise LedgerBadArgument("request_id must be non-empty")

    monkeypatch.setattr(ledger_v2.ledger_svc, "append_event", _boom)

    with pytest.raises(ContractError) as excinfo:
        ledger_v2.emit(
            domain="entity",
            operation="operator_core_created",
            request_id="",
            actor_ulid=None,
            target_ulid=None,
        )

    exc = excinfo.value
    assert exc.code == "bad_argument"
    assert exc.where == "ledger_v2.emit"
    assert exc.http_status == 400


def test_emit_maps_unavailable(monkeypatch):
    def _boom(**kwargs):
        raise LedgerUnavailable("ledger storage unavailable during append")

    monkeypatch.setattr(ledger_v2.ledger_svc, "append_event", _boom)

    with pytest.raises(ContractError) as excinfo:
        ledger_v2.emit(
            domain="entity",
            operation="operator_core_created",
            request_id="01REQREQREQREQREQREQREQRE",
            actor_ulid=None,
            target_ulid=None,
        )

    exc = excinfo.value
    assert exc.code == "ledger_unavailable"
    assert exc.where == "ledger_v2.emit"
    assert exc.http_status == 503


def test_verify_maps_unavailable(monkeypatch):
    def _boom(**kwargs):
        raise LedgerUnavailable("ledger storage unavailable during verify")

    monkeypatch.setattr(ledger_v2.ledger_svc, "verify_chain", _boom)

    with pytest.raises(ContractError) as excinfo:
        ledger_v2.verify(chain_key="ledger_test")

    exc = excinfo.value
    assert exc.code == "ledger_unavailable"
    assert exc.where == "ledger_v2.verify"
    assert exc.http_status == 503
