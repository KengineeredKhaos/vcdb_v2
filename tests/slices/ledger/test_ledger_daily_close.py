from __future__ import annotations

import pytest

from app.lib.ids import new_ulid
from app.slices.ledger import services as svc
from app.slices.ledger.errors import LedgerBackupGateBlocked


def _chain_key(prefix: str) -> str:
    return f"{prefix}_{new_ulid()[:12]}"


def test_daily_close_clean_allows_routine_backup(app):
    chain_key = _chain_key("dailyclose")

    with app.app_context():
        svc.append_event(
            domain="ledger",
            operation="daily_close_test_event",
            request_id=new_ulid(),
            actor_ulid=None,
            target_ulid=None,
            chain_key=chain_key,
        )

        result = svc.run_daily_close(
            request_id=new_ulid(),
            actor_ulid=None,
            chain_key=chain_key,
        )

        assert result["ok"] is True
        assert result["reason_code"] == svc.REASON_ADVISORY_HASHCHAIN
        assert result["routine_backup_allowed"] is True
        assert result["dirty_forensic_backup_only"] is False

        gate = svc.require_routine_backup_allowed(chain_key=chain_key)
        assert gate["routine_backup_allowed"] is True


def test_cron_ledgercheck_clean_records_cron_advisory(app):
    chain_key = _chain_key("croncheck")

    with app.app_context():
        svc.append_event(
            domain="ledger",
            operation="cron_check_test_event",
            request_id=new_ulid(),
            actor_ulid=None,
            target_ulid=None,
            chain_key=chain_key,
        )

        result = svc.run_daily_close(
            request_id=new_ulid(),
            actor_ulid=None,
            chain_key=chain_key,
            check_kind=svc.CHECK_KIND_CRON_LEDGERCHECK,
        )

        assert result["ok"] is True
        assert result["reason_code"] == svc.REASON_ADVISORY_CRON_LEDGERCHECK
        assert result["routine_backup_allowed"] is True
        assert result["dirty_forensic_backup_only"] is False


def test_backup_gate_blocks_without_daily_close(app):
    chain_key = _chain_key("noclose")

    with app.app_context():
        status = svc.backup_gate_status(chain_key=chain_key)

        assert status["has_daily_close"] is False
        assert status["routine_backup_allowed"] is False
        assert status["dirty_forensic_backup_only"] is True

        with pytest.raises(LedgerBackupGateBlocked):
            svc.require_routine_backup_allowed(chain_key=chain_key)
