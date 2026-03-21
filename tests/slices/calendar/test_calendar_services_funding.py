# tests/slices/calendar/test_calendar_services_funding.py

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from app.extensions import db
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

    def fake_hints(project_ulid: str) -> ProjectPolicyHints:
        return ProjectPolicyHints(
            source_profile_key="welcome_home_reimbursement_bridgeable",
            ops_support_planned=None,
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
