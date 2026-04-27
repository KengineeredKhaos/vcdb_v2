# tests/slices/ledger/test_ledger_hashchain_repair.py

from __future__ import annotations

from sqlalchemy import select, text

from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.ledger import admin_issue_services as issue_svc
from app.slices.ledger import services as svc
from app.slices.ledger.models import (
    LedgerAdminIssue,
    LedgerHashchainRepair,
)


def _chain_key(prefix: str) -> str:
    return f"{prefix}_{new_ulid()[:12]}"


def _dirty_two_event_chain(chain_key: str) -> str:
    svc.append_event(
        domain="ledger",
        operation="repair_first",
        request_id=new_ulid(),
        actor_ulid=None,
        target_ulid=None,
        chain_key=chain_key,
    )
    second = svc.append_event(
        domain="ledger",
        operation="repair_second",
        request_id=new_ulid(),
        actor_ulid=None,
        target_ulid=None,
        chain_key=chain_key,
    )
    second_ulid = second.ulid
    db.session.commit()

    db.session.execute(
        text(
            "UPDATE ledger_event "
            "SET curr_hash_hex = :bad_hash "
            "WHERE ulid = :event_ulid"
        ),
        {
            "bad_hash": "0" * 64,
            "event_ulid": second_ulid,
        },
    )
    db.session.commit()
    db.session.expire_all()
    return second_ulid


def test_repair_hashchain_recomputes_dirty_hash_and_records_repair(app):
    chain_key = _chain_key("repair")

    with app.app_context():
        dirty_event_ulid = _dirty_two_event_chain(chain_key)
        dirty = svc.verify_chain(chain_key=chain_key)
        assert dirty["ok"] is False
        assert dirty_event_ulid in {
            failure["event_ulid"] for failure in dirty["failures"]
        }

        result = svc.repair_hashchain(
            chain_key=chain_key,
            actor_ulid=None,
            request_id=new_ulid(),
        )

        assert result["ok"] is True
        assert dirty_event_ulid in result["affected_event_ulids"]
        assert svc.verify_chain(chain_key=chain_key)["ok"] is True

        repair = db.session.get(
            LedgerHashchainRepair,
            result["repair_ulid"],
        )
        assert repair is not None
        assert repair.repair_kind == "recompute_hashchain"
        assert repair.source_status == svc.STATUS_RECONCILED
        assert dirty_event_ulid in repair.affected_event_ulids_json
        assert repair.before_json["verify"]["ok"] is False
        assert repair.after_json["verify"]["ok"] is True


def test_repair_hashchain_for_issue_closes_restored_issue(app):
    chain_key = _chain_key("repair_issue")

    with app.app_context():
        _dirty_two_event_chain(chain_key)
        close_result = svc.run_daily_close(
            request_id=new_ulid(),
            actor_ulid=None,
            chain_key=chain_key,
        )
        assert close_result["ok"] is False

        issue = db.session.execute(
            select(LedgerAdminIssue).where(
                LedgerAdminIssue.chain_key == chain_key,
                LedgerAdminIssue.closed_at_utc.is_(None),
            )
        ).scalar_one()

        result = issue_svc.repair_hashchain_for_issue(
            issue_ulid=issue.ulid,
            actor_ulid=None,
            request_id=new_ulid(),
        )
        db.session.commit()

        assert result["ok"] is True

        refreshed = db.session.get(LedgerAdminIssue, issue.ulid)
        assert refreshed.closed_at_utc is not None
        assert refreshed.source_status == issue_svc.SOURCE_STATUS_RESTORED
        assert refreshed.close_reason == "hashchain_repaired"
        assert svc.verify_chain(chain_key=chain_key)["ok"] is True


def test_repair_hashchain_for_issue_reopens_backup_gate(app):
    chain_key = _chain_key("repair_gate")

    with app.app_context():
        _dirty_two_event_chain(chain_key)
        dirty_close = svc.run_daily_close(
            request_id=new_ulid(),
            actor_ulid=None,
            chain_key=chain_key,
        )
        assert dirty_close["ok"] is False

        blocked = svc.backup_gate_status(chain_key=chain_key)
        assert blocked["routine_backup_allowed"] is False
        assert blocked["dirty_forensic_backup_only"] is True

        issue = db.session.execute(
            select(LedgerAdminIssue).where(
                LedgerAdminIssue.chain_key == chain_key,
                LedgerAdminIssue.closed_at_utc.is_(None),
            )
        ).scalar_one()

        result = issue_svc.repair_hashchain_for_issue(
            issue_ulid=issue.ulid,
            actor_ulid=None,
            request_id=new_ulid(),
        )
        db.session.commit()

        assert result["ok"] is True
        assert result["post_repair_check_ulid"]

        gate = svc.backup_gate_status(chain_key=chain_key)
        assert gate["check_ulid"] == result["post_repair_check_ulid"]
        assert gate["reason_code"] == svc.REASON_ADVISORY_HASHCHAIN
        assert gate["source_status"] == svc.STATUS_CLEAN
        assert gate["routine_backup_allowed"] is True
        assert gate["dirty_forensic_backup_only"] is False
