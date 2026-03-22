# tests/slices/calendar/test_calendar_services_funding.py

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.extensions.contracts import calendar_v2
from app.slices.calendar.models import Project
from app.slices.calendar.services_funding import (
    create_funding_demand,
    get_spending_class_choices,
    publish_funding_demand,
    unpublish_funding_demand,
)


@dataclass(frozen=True)
class ProjectPolicyHints:
    source_profile_key: str | None = None
    ops_support_planned: bool | None = None


def _patch_publishable_hints(
    monkeypatch,
    *,
    source_profile_key="restricted_project_grant_return_unused",
    ops_support_planned=False,
):
    from app.slices.calendar import services_funding as svc

    monkeypatch.setattr(
        svc,
        "_project_policy_hints",
        lambda project_ulid: svc.ProjectPolicyHints(
            source_profile_key=source_profile_key,
            ops_support_planned=ops_support_planned,
        ),
    )


@pytest.fixture(autouse=True)
def _default_publishable_hints(monkeypatch):
    _patch_publishable_hints(monkeypatch)


def test_create_publish_unpublish_funding_demand(app):
    with app.app_context():
        project = Project(
            project_title="Test Project",
            status="planned",
        )
        db.session.add(project)
        db.session.commit()

        row = create_funding_demand(
            {
                "project_ulid": project.ulid,
                "title": "Kitchen starter kit",
                "goal_cents": 12000,
                "deadline_date": "2026-03-31",
                "spending_class": "admin",
                "tag_any": "",
            },
            actor_ulid=None,
            request_id="req-test-1",
        )
        db.session.commit()

        assert row.status == "draft"
        assert row.goal_cents == 12000
        assert row.project_ulid == project.ulid

        row = publish_funding_demand(
            row.ulid,
            actor_ulid=None,
            request_id="req-test-2",
        )
        db.session.commit()

        assert row.status == "published"
        assert row.published_at_utc is not None
        assert isinstance(row.eligible_fund_keys_json, list)

        row = unpublish_funding_demand(
            row.ulid,
            actor_ulid=None,
            request_id="req-test-3",
        )
        db.session.commit()

        assert row.status == "draft"
        assert row.published_at_utc is None


def test_publish_funding_demand_forwards_source_profile_hint(
    app, monkeypatch
):
    from app.slices.calendar import services_funding as svc

    captured: dict[str, object] = {}

    def fake_hints(project_ulid: str):
        return svc.ProjectPolicyHints(
            source_profile_key="welcome_home_reimbursement_bridgeable",
            ops_support_planned=True,
        )

    def fake_preview(req):
        captured["source_profile_key"] = req.source_profile_key
        return SimpleNamespace(
            eligible_fund_keys=("general_unrestricted",),
            decision_fingerprint="fp-publish",
            required_approvals=(),
        )

    with app.app_context():
        project = Project(
            project_title="Hinted Publish Project",
            status="planned",
        )
        db.session.add(project)
        db.session.commit()

        row = create_funding_demand(
            {
                "project_ulid": project.ulid,
                "title": "Hinted Demand",
                "goal_cents": 9000,
                "deadline_date": "2026-03-31",
                "spending_class": "basic_needs",
                "tag_any": "welcome_home_kit",
            },
            actor_ulid=None,
            request_id="req-hinted-publish-create",
        )
        db.session.commit()

        monkeypatch.setattr(svc, "_project_policy_hints", fake_hints)
        monkeypatch.setattr(svc.gov, "preview_funding_decision", fake_preview)

        publish_funding_demand(
            row.ulid,
            actor_ulid=None,
            request_id="req-hinted-publish",
        )

        assert (
            captured["source_profile_key"]
            == "welcome_home_reimbursement_bridgeable"
        )


def test_encumber_project_funds_uses_encumber_op(app, monkeypatch):
    from app.slices.calendar import services_finance_bridge as svc

    captured: dict[str, object] = {}

    class DummyPreview:
        allowed = True
        eligible_fund_keys = ("general_unrestricted",)
        required_approvals = ()
        reason_codes = ()
        matched_rule_ids = ()
        decision_fingerprint = "fp-test"

    def fake_preview(req):
        captured["op"] = req.op
        return DummyPreview()

    monkeypatch.setattr(
        svc.governance_v2,
        "preview_funding_decision",
        fake_preview,
    )

    # patch downstream side effects as needed here


def test_preview_funding_decision_forwards_ops_support_planned(
    app, monkeypatch
):
    from app.extensions.contracts import governance_v2 as gov

    captured: dict[str, object] = {}

    def fake_preview(raw_req: dict[str, object]) -> dict[str, object]:
        captured["ops_support_planned"] = raw_req.get("ops_support_planned")
        return {
            "allowed": True,
            "eligible_fund_keys": ["general_unrestricted"],
            "required_approvals": [],
            "reason_codes": [],
            "matched_rule_ids": [],
            "decision_fingerprint": "fp-test",
        }

    monkeypatch.setattr(
        gov,
        "svc_preview_funding_decision",
        fake_preview,
    )

    req = gov.FundingDecisionRequestDTO(
        op="encumber",
        amount_cents=1000,
        funding_demand_ulid="01TESTTESTTESTTESTTESTTEST",
        project_ulid="01TESTTESTTESTTESTTESTTEST",
        spending_class="events",
        expense_kind="event_expense",
        source_profile_key="ops_bridge_preapproved",
        ops_support_planned=True,
    )

    gov.preview_funding_decision(req)

    assert captured["ops_support_planned"] is True


def test_get_spending_class_choices_uses_key_and_label(app):
    with app.app_context():
        choices = get_spending_class_choices()
        assert choices[0] == ("", "— Select —")
        assert all(
            isinstance(v[0], str) and isinstance(v[1], str)
            for v in choices[1:]
        )
        assert any(value == "events" for value, _label in choices[1:])


def test_publish_funding_demand_writes_published_context_json(app):
    with app.app_context():
        project = Project(project_title="Snapshot Project", status="planned")
        db.session.add(project)
        db.session.commit()

        row = create_funding_demand(
            {
                "project_ulid": project.ulid,
                "title": "Snapshot Demand",
                "goal_cents": 15000,
                "deadline_date": "2026-04-15",
                "spending_class": "basic_needs",
                "tag_any": "housing,kit",
            },
            actor_ulid=None,
            request_id="req-snapshot-create",
        )
        db.session.commit()

        row = publish_funding_demand(
            row.ulid,
            actor_ulid=None,
            request_id="req-snapshot-publish",
        )
        db.session.commit()

        assert isinstance(row.published_context_json, dict)
        assert row.published_context_json["schema_version"] == 1
        assert (
            row.published_context_json["demand"]["funding_demand_ulid"]
            == row.ulid
        )
        assert (
            row.published_context_json["planning"]["project_title"]
            == "Snapshot Project"
        )
        assert row.published_context_json["policy"]["eligible_fund_keys"]
        assert row.published_context_json["workflow"][
            "allowed_realization_modes"
        ]


def test_unpublish_funding_demand_retains_published_context_json(app):
    with app.app_context():
        project = Project(project_title="Retain Packet", status="planned")
        db.session.add(project)
        db.session.commit()

        row = create_funding_demand(
            {
                "project_ulid": project.ulid,
                "title": "Retain Demand",
                "goal_cents": 5000,
                "deadline_date": "2026-05-01",
                "spending_class": "basic_needs",
                "tag_any": "housing",
            },
            actor_ulid=None,
            request_id="req-retain-create",
        )
        db.session.commit()

        row = publish_funding_demand(
            row.ulid,
            actor_ulid=None,
            request_id="req-retain-publish",
        )
        db.session.commit()

        snapshot = row.published_context_json

        row = unpublish_funding_demand(
            row.ulid,
            actor_ulid=None,
            request_id="req-retain-unpublish",
        )
        db.session.commit()

        assert row.status == "draft"
        assert row.published_context_json == snapshot


def test_get_funding_demand_context_returns_snapshot(app):
    from app.extensions import db
    from app.slices.calendar.models import Project
    from app.slices.calendar.services_funding import (
        create_funding_demand,
        publish_funding_demand,
    )

    with app.app_context():
        project = Project(project_title="Contract Context", status="planned")
        db.session.add(project)
        db.session.commit()

        row = create_funding_demand(
            {
                "project_ulid": project.ulid,
                "title": "Contract Demand",
                "goal_cents": 11000,
                "deadline_date": "2026-04-30",
                "spending_class": "basic_needs",
                "tag_any": "welcome_home_kit",
            },
            actor_ulid=None,
            request_id="req-contract-create",
        )
        db.session.commit()

        publish_funding_demand(
            row.ulid,
            actor_ulid=None,
            request_id="req-contract-publish",
        )
        db.session.commit()

        ctx = calendar_v2.get_funding_demand_context(row.ulid)

        assert ctx.schema_version == 1
        assert ctx.demand.funding_demand_ulid == row.ulid
        assert ctx.planning.project_title == "Contract Context"
        assert ctx.policy.eligible_fund_keys
        assert ctx.workflow.allowed_realization_modes
