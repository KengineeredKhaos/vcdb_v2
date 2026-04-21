# tests/slices/sponsors/test_sponsors_funding_realization.py

from __future__ import annotations

import json
from dataclasses import asdict

import pytest
from sqlalchemy import select

from app.extensions import db
from app.extensions.contracts import calendar_v2, governance_v2, sponsors_v2
from app.slices.calendar.models import Project
from app.slices.calendar.services_budget import (
    add_budget_line,
    create_working_snapshot,
    lock_snapshot,
)
from app.slices.calendar.services_drafts import (
    approve_draft_for_publish,
    create_draft_from_snapshot,
    mark_draft_ready_for_review,
    promote_draft_to_funding_demand,
    submit_draft_for_governance_review,
)
from app.slices.entity.models import Entity, EntityOrg
from app.slices.finance.models import Journal, Reserve
from app.slices.finance.services_journal import ensure_default_accounts
from app.slices.ledger.models import LedgerEvent
from app.slices.sponsors.models import Sponsor, SponsorFundingIntent
from app.slices.sponsors.services_funding import create_funding_intent


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


def _create_published_demand(
    *,
    title: str = "Bridge Test Demand",
    amount_cents: int = 12000,
    source_profile_key: str = "mission_local_veterans_cash",
    default_restriction_keys: tuple[str, ...] = (
        "local_only",
        "vet_only",
    ),
    eligible_fund_codes: tuple[str, ...] = ("general_unrestricted",),
) -> str:
    project = Project(
        project_title="Bridge Test Project",
        status="draft_planning",
        funding_profile_key=source_profile_key,
    )
    db.session.add(project)
    db.session.flush()

    snapshot = create_working_snapshot(
        project_ulid=project.ulid,
        actor_ulid=project.ulid,
        snapshot_label="Bridge Basis",
        scope_summary="Bridge funding basis",
    )
    add_budget_line(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=project.ulid,
        label="Bridge cost",
        line_kind="materials",
        estimated_total_cents=amount_cents,
    )
    locked = lock_snapshot(
        snapshot_ulid=snapshot["ulid"],
        actor_ulid=project.ulid,
    )
    db.session.flush()

    draft = create_draft_from_snapshot(
        project_ulid=project.ulid,
        snapshot_ulid=locked["ulid"],
        actor_ulid=project.ulid,
        title=title,
        summary=title,
        scope_summary="Bridge funding basis",
        requested_amount_cents=amount_cents,
        spending_class_candidate="basic_needs",
        source_profile_key=source_profile_key,
        tag_any="",
    )
    draft = mark_draft_ready_for_review(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    draft = submit_draft_for_governance_review(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    draft = approve_draft_for_publish(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
        governance_decision=governance_v2.GovernanceReviewDecisionDTO(
            decision="approved",
            governance_note="Governance semantics approved for publish.",
            approved_spending_class="basic_needs",
            approved_source_profile_key=source_profile_key,
            eligible_fund_codes=tuple(eligible_fund_codes),
            default_restriction_keys=tuple(default_restriction_keys),
            approved_tag_any=(),
            decision_fingerprint="fp-sponsors-realization",
            validation_errors=(),
            reason_codes=(),
            matched_rule_ids=(),
        ),
    )
    promoted = promote_draft_to_funding_demand(
        draft_ulid=draft["ulid"],
        actor_ulid=project.ulid,
    )
    db.session.flush()
    return promoted["funding_demand"]["funding_demand_ulid"]


def test_realize_funding_intent_posts_income_and_reserve(app):
    with app.app_context():
        ensure_default_accounts()

        demand_ulid = _create_published_demand()
        sponsor = _create_sponsor("Sponsor Realization Test")

        intent = create_funding_intent(
            {
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "intent_kind": "donation",
                "amount_cents": 12000,
                "status": "committed",
                "note": "earmarked receipt",
            },
            actor_ulid=None,
            request_id="req-intent-create",
        )
        db.session.flush()

        demand = sponsors_v2.get_funding_intent_totals(demand_ulid)
        assert demand.pledged_cents == 12000

        funding_demand = calendar_v2.get_funding_demand(demand_ulid)
        assert funding_demand.eligible_fund_codes

        income_kind = "donation"

        preview = governance_v2.preview_funding_policy(
            governance_v2.FundingDecisionRequestDTO(
                op="receive",
                amount_cents=12000,
                funding_demand_ulid=funding_demand.funding_demand_ulid,
                project_ulid=funding_demand.project_ulid,
                income_kind=income_kind,
                restriction_keys=(),
                demand_eligible_fund_codes=tuple(
                    funding_demand.eligible_fund_codes
                ),
                selected_fund_code=None,
                actor_rbac_roles=(),
                actor_domain_roles=(),
            )
        )

        assert preview.allowed
        assert preview.eligible_fund_codes
        fund_code = preview.eligible_fund_codes[0]

        out = sponsors_v2.realize_funding_intent(
            sponsors_v2.FundingRealizationRequestDTO(
                intent_ulid=intent.ulid,
                amount_cents=12000,
                happened_at_utc="2026-03-15T14:00:00Z",
                fund_code=fund_code,
                income_kind=income_kind,
                receipt_method="bank",
                reserve_on_receive=True,
                memo="realization bridge test",
                actor_ulid=None,
                request_id="req-realize-1",
            )
        )
        assert out.decision_fingerprint
        assert out.fund_code == fund_code
        db.session.flush()

        refreshed = db.session.get(SponsorFundingIntent, intent.ulid)

        assert refreshed is not None
        assert refreshed.status == "fulfilled"
        assert out.status == "fulfilled"

        journal = db.session.get(Journal, out.journal_ulid)
        assert journal is not None
        assert journal.funding_demand_ulid == demand_ulid

        reserve = db.session.get(Reserve, out.reserve_ulid)
        assert reserve is not None
        assert reserve.funding_demand_ulid == demand_ulid
        assert reserve.amount_cents == 12000

        ledger_row = (
            db.session.execute(
                select(LedgerEvent).where(
                    LedgerEvent.target_ulid == intent.ulid,
                    LedgerEvent.event_type
                    == "sponsors.sponsor_funding_realized",
                )
            )
            .scalars()
            .one_or_none()
        )
        assert ledger_row is not None

        refs = ledger_row.refs_json or {}
        if isinstance(refs, str):
            refs = json.loads(refs)

        assert refs["journal_ulid"] == out.journal_ulid
        assert refs["reserve_ulid"] == out.reserve_ulid


def test_realize_funding_intent_rejects_non_committed(app):
    with app.app_context():
        ensure_default_accounts()

        demand_ulid = _create_published_demand()
        sponsor = _create_sponsor("Sponsor Draft Intent")

        intent = create_funding_intent(
            {
                "sponsor_entity_ulid": sponsor.entity_ulid,
                "funding_demand_ulid": demand_ulid,
                "intent_kind": "donation",
                "amount_cents": 5000,
                "status": "draft",
                "note": None,
            },
            actor_ulid=None,
            request_id="req-intent-draft",
        )
        db.session.flush()

        funding_demand = calendar_v2.get_funding_demand(demand_ulid)
        tx = governance_v2.get_finance_taxonomy()

        with pytest.raises(Exception) as exc:
            sponsors_v2.realize_funding_intent(
                sponsors_v2.FundingRealizationRequestDTO(
                    intent_ulid=intent.ulid,
                    amount_cents=5000,
                    happened_at_utc="2026-03-15T15:00:00Z",
                    fund_code=funding_demand.eligible_fund_codes[0],
                    income_kind=tx.income_kinds[0].key,
                    receipt_method="bank",
                    request_id="req-realize-draft",
                )
            )

        assert "committed" in str(exc.value).lower()
