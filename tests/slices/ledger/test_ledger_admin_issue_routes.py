# tests/slices/ledger/test_ledger_admin_issue_routes.py

from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.extensions import db
from app.lib.ids import new_ulid
from app.slices.ledger import admin_issue_services as issue_svc
from app.slices.ledger import services as svc
from app.slices.ledger.models import (
    LedgerAdminIssue,
    LedgerHashchainCheck,
    LedgerHashchainRepair,
)


@pytest.fixture
def admin_client(client):
    client.environ_base.update({"HTTP_X_AUTH_STUB": "admin"})
    return client


@pytest.fixture
def auditor_client(client):
    client.environ_base.update({"HTTP_X_AUTH_STUB": "auditor"})
    return client


@pytest.fixture
def staff_client(client):
    client.environ_base.update({"HTTP_X_AUTH_STUB": "staff"})
    return client


def _csrf(client, path: str) -> str:
    resp = client.get(path)
    assert resp.status_code == 200
    text_body = resp.get_data(as_text=True)
    marker = 'name="csrf_token" value="'
    start = text_body.find(marker)
    assert start >= 0
    start += len(marker)
    end = text_body.find('"', start)
    assert end > start
    return text_body[start:end]


def _chain_key(prefix: str) -> str:
    return f"{prefix}_{new_ulid()[:12]}"


def _dirty_two_event_chain(chain_key: str) -> str:
    svc.append_event(
        domain="ledger",
        operation="route_first",
        request_id=new_ulid(),
        actor_ulid=None,
        target_ulid=None,
        chain_key=chain_key,
    )
    second = svc.append_event(
        domain="ledger",
        operation="route_second",
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


def _seed_issue_and_check() -> tuple[str, str]:
    chain_key = _chain_key("ledger_route")
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

    check = db.session.execute(
        select(LedgerHashchainCheck)
        .where(LedgerHashchainCheck.chain_key == chain_key)
        .order_by(LedgerHashchainCheck.created_at_utc.desc())
        .limit(1)
    ).scalar_one()

    db.session.commit()
    return issue.ulid, check.ulid


def _seed_issue_check_and_repair() -> tuple[str, str, str]:
    issue_ulid, check_ulid = _seed_issue_and_check()
    result = issue_svc.repair_hashchain_for_issue(
        issue_ulid=issue_ulid,
        actor_ulid=None,
        request_id=new_ulid(),
    )
    db.session.commit()

    repair = db.session.get(LedgerHashchainRepair, result["repair_ulid"])
    assert repair is not None
    return issue_ulid, check_ulid, repair.ulid


def test_ledger_admin_issue_index_allows_admin_and_auditor(
    app,
    admin_client,
    auditor_client,
):
    with app.app_context():
        _seed_issue_and_check()

    resp = admin_client.get("/ledger/admin/issues")
    assert resp.status_code == 200
    assert "Ledger integrity drill-down" in resp.get_data(as_text=True)

    resp = auditor_client.get("/ledger/admin/issues")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Ledger integrity drill-down" in body
    assert "Read-only auditor view" in body
    assert "Recent checks" in body
    assert "Recent repairs" in body
    assert "Run ledger verification now" not in body

def test_ledger_admin_issue_detail_is_readable_by_auditor(
    app,
    auditor_client,
):
    with app.app_context():
        issue_ulid, _check_ulid = _seed_issue_and_check()

    resp = auditor_client.get(f"/ledger/admin/issues/{issue_ulid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Read-only auditor view" in body
    assert "Ledger issue facts" in body
    assert "Related checks" in body
    assert "Diagnostics" in body
    assert "Run verify for this issue" not in body
    assert "Repair hash-chain" not in body


def test_ledger_hashchain_check_detail_is_readable_by_auditor(
    app,
    auditor_client,
):
    with app.app_context():
        _issue_ulid, check_ulid = _seed_issue_and_check()

    resp = auditor_client.get(f"/ledger/admin/checks/{check_ulid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Ledger check —" in body
    assert "Read-only auditor view" in body
    assert "Check facts" in body
    assert "Backup gate posture" in body
    assert "Check details" in body


def test_ledger_admin_issue_index_shows_manual_verify_button_for_admin(
    admin_client,
):
    resp = admin_client.get("/ledger/admin/issues")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Run ledger verification now" in body


def test_ledger_admin_manual_verify_route_records_check(
    app,
    admin_client,
):
    with app.app_context():
        chain_key = _chain_key("ledger_manual_verify")
        svc.append_event(
            domain="ledger",
            operation="manual_verify_seed",
            request_id=new_ulid(),
            actor_ulid=None,
            target_ulid=None,
            chain_key=chain_key,
        )
        db.session.commit()

    csrf = _csrf(admin_client, "/ledger/admin/issues")
    resp = admin_client.post(
        "/ledger/admin/run-verify",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        check = db.session.execute(
            select(LedgerHashchainCheck)
            .where(
                LedgerHashchainCheck.check_kind
                == svc.CHECK_KIND_MANUAL_VERIFY
            )
            .order_by(LedgerHashchainCheck.created_at_utc.desc())
            .limit(1)
        ).scalar_one()
        assert check.check_kind == svc.CHECK_KIND_MANUAL_VERIFY


def test_ledger_admin_manual_verify_route_is_admin_only(
    auditor_client,
):
    csrf = _csrf(auditor_client, "/ledger/admin/issues")
    resp = auditor_client.post(
        "/ledger/admin/run-verify",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_ledger_hashchain_repair_detail_is_readable_by_auditor(
    app,
    auditor_client,
):
    with app.app_context():
        _issue_ulid, _check_ulid, repair_ulid = _seed_issue_check_and_repair()

    resp = auditor_client.get(f"/ledger/admin/repairs/{repair_ulid}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Ledger repair evidence" in body
    assert "Read-only auditor view" in body
    assert "Repair facts" in body
    assert "Affected events" in body
    assert "Before" in body
    assert "After" in body


def test_ledger_admin_issue_post_routes_are_admin_only(
    app,
    staff_client,
    auditor_client,
):
    with app.app_context():
        issue_ulid, _check_ulid = _seed_issue_and_check()

    path = f"/ledger/admin/issues/{issue_ulid}"
    csrf = _csrf(auditor_client, path)

    resp = auditor_client.post(
        f"/ledger/admin/issues/{issue_ulid}/run-verify",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403

    csrf = _csrf(staff_client, path)
    resp = staff_client.post(
        f"/ledger/admin/issues/{issue_ulid}/run-verify",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403
