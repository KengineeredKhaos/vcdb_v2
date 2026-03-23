# tests/slices/sponsors/test_sponsors_funding_context.py

from __future__ import annotations

from dataclasses import asdict

from app.extensions import db
from app.extensions.contracts import sponsors_v2
from app.slices.calendar.models import Project
from app.slices.calendar.services_funding import (
    create_funding_demand,
    publish_funding_demand,
)
from app.slices.entity.models import Entity, EntityOrg
from app.slices.finance.services_journal import ensure_default_accounts
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services_funding import (
    create_funding_intent,
    get_funding_opportunity,
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


def _create_published_demand() -> str:
    project = Project(
        project_title="Context Project",
        status="planned",
    )
    db.session.add(project)
    db.session.flush()

    row = create_funding_demand(
        {
            "project_ulid": project.ulid,
            "title": "Context Demand",
            "goal_cents": 17500,
            "deadline_date": "2026-04-10",
            "spending_class": "basic_needs",
            "tag_any": "welcome_home_kit,crm_seed",
        },
        actor_ulid=None,
        request_id="req-context-create",
    )
    db.session.flush()

    row = publish_funding_demand(
        row.ulid,
        actor_ulid=None,
        request_id="req-context-publish",
    )
    db.session.flush()
    return row.ulid


def test_get_funding_opportunity_uses_context_packet(app, monkeypatch):
    from app.slices.calendar import services_funding as svc

    monkeypatch.setattr(
        svc,
        "_project_policy_hints",
        lambda project_ulid: svc.ProjectPolicyHints(
            source_profile_key="mission_local_veterans_cash",
            ops_support_planned=False,
        ),
    )

    with app.app_context():
        demand_ulid = _create_published_demand()
        sponsor = _create_sponsor("Context Sponsor")

        create_funding_intent(
            {
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "intent_kind": "pledge",
                "amount_cents": 9000,
                "status": "committed",
                "note": "crm context",
            },
            actor_ulid=None,
            request_id="req-intent-context",
        )
        db.session.flush()

        detail = get_funding_opportunity(demand_ulid)

        assert detail.planning.project_title == "Context Project"
        assert detail.planning.source_profile_key
        assert detail.workflow.allowed_realization_modes
        assert detail.policy.eligible_fund_keys
        assert detail.totals.pledged_cents == 9000
        assert detail.money.received_cents == 0
        assert detail.money.remaining_goal_cents == 17500
        assert detail.money.uncovered_pipeline_gap_cents == 8500


def test_realize_funding_intent_defaults_from_context(app, monkeypatch):
    from app.slices.calendar import services_funding as svc

    monkeypatch.setattr(
        svc,
        "_project_policy_hints",
        lambda project_ulid: svc.ProjectPolicyHints(
            source_profile_key="mission_local_veterans_cash",
            ops_support_planned=False,
        ),
    )

    with app.app_context():
        ensure_default_accounts()
        demand_ulid = _create_published_demand()
        sponsor = _create_sponsor("Default Sponsor")

        intent = create_funding_intent(
            {
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "intent_kind": "donation",
                "amount_cents": 17500,
                "status": "committed",
                "note": "default realization",
            },
            actor_ulid=None,
            request_id="req-intent-defaults",
        )
        db.session.flush()

        detail = get_funding_opportunity(demand_ulid)
        fund_key = detail.policy.eligible_fund_keys[0]

        out = sponsors_v2.realize_funding_intent(
            sponsors_v2.FundingRealizationRequestDTO(
                intent_ulid=intent.ulid,
                amount_cents=17500,
                happened_at_utc="2026-03-20T10:00:00Z",
                fund_key=fund_key,
                receipt_method="bank",
                request_id="req-realize-defaults",
            )
        )
        db.session.flush()

        assert out.status == "fulfilled"
