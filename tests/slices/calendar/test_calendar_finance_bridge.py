from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.extensions import db
from app.extensions.contracts import calendar_v2, finance_v2, governance_v2
from app.slices.calendar.models import FundingDemand
from app.slices.entity.models import Entity, EntityOrg
from app.slices.finance.models import Encumbrance, Journal
from app.slices.finance.services_journal import ensure_default_accounts
from app.slices.ledger.models import LedgerEvent
from app.slices.sponsors.models import Sponsor
from app.slices.sponsors.services_funding import create_funding_intent

# -----------------
# Local test helpers
# -----------------


def _pick_approval_free_fund(eligible_fund_codes: tuple[str, ...]) -> str:
    if "general_unrestricted" in eligible_fund_codes:
        return "general_unrestricted"
    return eligible_fund_codes[0]


def _derive_restriction_type(
    restriction_keys: tuple[str, ...],
    archetype: str,
) -> str:
    keys = {str(k).strip().lower() for k in restriction_keys}
    arch = (archetype or "").strip().lower()

    if {"perm", "permanent", "permanently_restricted"} & keys or arch in {
        "perm",
        "permanent",
        "permanently_restricted",
    }:
        return "permanently_restricted"
    if {"temp", "temporary", "temporarily_restricted"} & keys or arch in {
        "temp",
        "temporary",
        "temporarily_restricted",
    }:
        return "temporarily_restricted"
    return "unrestricted"


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
    amount_cents: int = 12000,
    demand_title: str = "Bridge Demand",
    source_profile_key: str = "ops_bridge_preapproved",
    eligible_fund_codes: tuple[str, ...] = ("general_unrestricted",),
) -> tuple[str, str]:
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
    from app.slices.calendar.models import Project

    project = Project(
        project_title="Calendar Finance Bridge",
        status="draft_planning",
        funding_profile_key=source_profile_key,
    )
    db.session.add(project)
    db.session.flush()

    actor_ulid = project.ulid

    snap = create_working_snapshot(
        project_ulid=project.ulid,
        actor_ulid=actor_ulid,
        snapshot_label="Working Budget",
        scope_summary="Full project scope",
    )
    add_budget_line(
        snapshot_ulid=snap["ulid"],
        actor_ulid=actor_ulid,
        label="Estimated project cost",
        line_kind="materials",
        estimated_total_cents=amount_cents,
    )
    locked = lock_snapshot(
        snapshot_ulid=snap["ulid"],
        actor_ulid=actor_ulid,
    )

    draft = create_draft_from_snapshot(
        project_ulid=project.ulid,
        snapshot_ulid=locked["ulid"],
        actor_ulid=actor_ulid,
        title=demand_title,
        summary=demand_title,
        scope_summary="Full project scope",
        requested_amount_cents=amount_cents,
        spending_class_candidate="basic_needs",
        source_profile_key=source_profile_key,
        tag_any="",
    )
    mark_draft_ready_for_review(
        draft_ulid=draft["ulid"],
        actor_ulid=actor_ulid,
    )
    submit_draft_for_governance_review(
        draft_ulid=draft["ulid"],
        actor_ulid=actor_ulid,
    )
    approve_draft_for_publish(
        draft_ulid=draft["ulid"],
        actor_ulid=actor_ulid,
        governance_decision=governance_v2.GovernanceReviewDecisionDTO(
            decision="approved",
            governance_note="Governance semantics approved for publish.",
            approved_spending_class="basic_needs",
            approved_source_profile_key=source_profile_key,
            eligible_fund_codes=tuple(eligible_fund_codes),
            default_restriction_keys=(),
            approved_tag_any=(),
            decision_fingerprint="fp-calendar-finance-bridge",
            validation_errors=(),
            reason_codes=(),
            matched_rule_ids=(),
        ),
    )
    promoted = promote_draft_to_funding_demand(
        draft_ulid=draft["ulid"],
        actor_ulid=actor_ulid,
    )
    db.session.flush()

    funding = promoted["funding_demand"]
    demand_ulid = funding.get("funding_demand_ulid") or funding.get("ulid")
    assert demand_ulid
    return project.ulid, demand_ulid


def _realize_funding_into_demand(
    *,
    funding_demand_ulid: str,
    amount_cents: int,
    fund_code: str,
) -> None:
    sponsor = _create_sponsor("Bridge Sponsor")
    intent = create_funding_intent(
        {
            "sponsor_entity_ulid": sponsor.entity_ulid,
            "funding_demand_ulid": funding_demand_ulid,
            "intent_kind": "donation",
            "amount_cents": amount_cents,
            "status": "committed",
            "note": "bridge receipt",
        },
        actor_ulid=None,
        request_id="req-intent-bridge",
    )
    db.session.flush()

    tx = governance_v2.get_finance_taxonomy()
    income_kind = tx.income_kinds[0].key

    from app.extensions.contracts import sponsors_v2

    sponsors_v2.realize_funding_intent(
        sponsors_v2.FundingRealizationRequestDTO(
            intent_ulid=intent.ulid,
            amount_cents=amount_cents,
            happened_at_utc="2026-03-16T10:00:00Z",
            fund_code=fund_code,
            income_kind=income_kind,
            receipt_method="bank",
            reserve_on_receive=True,
            request_id="req-realize-bridge",
        )
    )
    db.session.flush()


def _create_realized_demand(
    *,
    eligible_fund_codes: tuple[str, ...] = ("general_unrestricted",),
    source_profile_key: str = "ops_bridge_preapproved",
) -> tuple[str, str, str]:
    project_ulid, demand_ulid = _create_published_demand(
        amount_cents=12000,
        demand_title="Bridge Demand",
        source_profile_key=source_profile_key,
        eligible_fund_codes=eligible_fund_codes,
    )

    demand = calendar_v2.get_funding_demand(demand_ulid)
    fund_code = _pick_approval_free_fund(demand.eligible_fund_codes)
    _realize_funding_into_demand(
        funding_demand_ulid=demand_ulid,
        amount_cents=12000,
        fund_code=fund_code,
    )
    return project_ulid, demand_ulid, fund_code


def _seed_reserve_for_fund(
    *,
    funding_demand_ulid: str,
    fund_code: str,
    amount_cents: int,
) -> None:
    demand = calendar_v2.get_funding_demand(funding_demand_ulid)
    fund_meta = governance_v2.get_fund_code(fund_code)
    restriction_keys = governance_v2.apply_fund_defaults(
        fund_code=fund_code,
        restriction_keys=(),
    )
    fund_restriction_type = _derive_restriction_type(
        restriction_keys,
        fund_meta.archetype,
    )

    finance_v2.reserve_funds(
        finance_v2.ReserveRequestDTO(
            funding_demand_ulid=funding_demand_ulid,
            fund_code=fund_code,
            amount_cents=amount_cents,
            source="tests",
            fund_label=fund_meta.label,
            fund_restriction_type=fund_restriction_type,
            project_ulid=demand.project_ulid,
            source_ref_ulid=None,
            memo="seed reserve for approval test",
            actor_ulid=None,
            request_id="req-seed-restricted-reserve",
            dry_run=False,
        )
    )
    db.session.flush()


# -----------------
# Tests
# -----------------


def test_encumber_project_funds_happy_path(app):
    with app.app_context():
        ensure_default_accounts()
        _project_ulid, demand_ulid, fund_code = _create_realized_demand()
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[12].key

        out = calendar_v2.encumber_project_funds(
            calendar_v2.ProjectEncumbranceRequestDTO(
                funding_demand_ulid=demand_ulid,
                amount_cents=8000,
                fund_code=fund_code,
                expense_kind=expense_kind,
                happened_at_utc="2026-03-16T11:00:00Z",
                request_id="req-encumber-1",
            )
        )
        db.session.flush()

        demand = db.session.get(FundingDemand, demand_ulid)
        assert demand is not None
        assert demand.status == "funding_in_progress"

        enc = db.session.get(Encumbrance, out.encumbrance_ulid)
        assert enc is not None
        assert enc.funding_demand_ulid == demand_ulid
        assert enc.amount_cents == 8000
        assert enc.status == "active"
        assert out.decision_fingerprint

        money = finance_v2.get_funding_demand_money_view(demand_ulid)
        assert money.reserved_cents == 12000
        assert money.encumbered_cents == 8000

        evt = (
            db.session.execute(
                select(LedgerEvent).where(
                    LedgerEvent.event_type
                    == "calendar.project_funds_encumbered",
                    LedgerEvent.target_ulid == demand_ulid,
                )
            )
            .scalars()
            .one_or_none()
        )
        assert evt is not None


def test_spend_project_funds_happy_path(app):
    with app.app_context():
        ensure_default_accounts()
        _project_ulid, demand_ulid, fund_code = _create_realized_demand()
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[0].key

        enc = calendar_v2.encumber_project_funds(
            calendar_v2.ProjectEncumbranceRequestDTO(
                funding_demand_ulid=demand_ulid,
                amount_cents=8000,
                fund_code=fund_code,
                expense_kind=expense_kind,
                happened_at_utc="2026-03-16T11:30:00Z",
                request_id="req-encumber-2",
            )
        )
        db.session.flush()

        out = calendar_v2.spend_project_funds(
            calendar_v2.ProjectSpendRequestDTO(
                encumbrance_ulid=enc.encumbrance_ulid,
                amount_cents=3000,
                expense_kind=expense_kind,
                payment_method="bank",
                happened_at_utc="2026-03-16T12:00:00Z",
                request_id="req-spend-1",
            )
        )
        db.session.flush()

        demand = db.session.get(FundingDemand, demand_ulid)
        assert demand is not None
        assert demand.status == "executing"

        journal = db.session.get(Journal, out.journal_ulid)
        assert journal is not None
        assert journal.funding_demand_ulid == demand_ulid

        enc_row = db.session.get(Encumbrance, enc.encumbrance_ulid)
        assert enc_row is not None
        assert enc_row.relieved_cents == 3000
        assert enc_row.status == "active"

        money = finance_v2.get_funding_demand_money_view(demand_ulid)
        assert money.encumbered_cents == 5000
        assert money.spent_cents == 3000

        evt = (
            db.session.execute(
                select(LedgerEvent).where(
                    LedgerEvent.event_type == "calendar.project_funds_spent",
                    LedgerEvent.target_ulid == demand_ulid,
                )
            )
            .scalars()
            .one_or_none()
        )
        assert evt is not None


def test_get_project_execution_truth_reports_finance_posture(app):
    with app.app_context():
        ensure_default_accounts()
        _project_ulid, demand_ulid, fund_code = _create_realized_demand()
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[0].key

        enc = calendar_v2.encumber_project_funds(
            calendar_v2.ProjectEncumbranceRequestDTO(
                funding_demand_ulid=demand_ulid,
                amount_cents=4000,
                fund_code=fund_code,
                expense_kind=expense_kind,
                happened_at_utc="2026-03-16T11:30:00Z",
                request_id="req-phase4-encumber",
            )
        )
        db.session.flush()

        out = calendar_v2.spend_project_funds(
            calendar_v2.ProjectSpendRequestDTO(
                encumbrance_ulid=enc.encumbrance_ulid,
                amount_cents=1500,
                expense_kind=expense_kind,
                payment_method="bank",
                happened_at_utc="2026-03-16T12:00:00Z",
                request_id="req-phase4-spend",
            )
        )
        db.session.flush()
        assert out.journal_ulid

        truth = calendar_v2.get_project_execution_truth(
            funding_demand_ulid=demand_ulid,
        )

        assert truth.funding_demand_ulid == demand_ulid
        assert truth.received_cents == 12000
        assert truth.reserved_cents == 12000
        assert truth.encumbered_cents == 2500
        assert truth.spent_cents == 1500
        assert truth.remaining_open_cents == 10500
        assert truth.funded_enough is True
        assert truth.support_source_posture in {
            "sponsor_funded",
            "mixed",
        }
        assert truth.reserve_ulids
        assert truth.encumbrance_ulids
        assert truth.expense_journal_ulids


def test_encumber_rejects_when_over_reserved(app):
    with app.app_context():
        ensure_default_accounts()
        _project_ulid, demand_ulid, fund_code = _create_realized_demand()
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[0].key

        with pytest.raises(Exception) as exc:
            calendar_v2.encumber_project_funds(
                calendar_v2.ProjectEncumbranceRequestDTO(
                    funding_demand_ulid=demand_ulid,
                    amount_cents=13000,
                    fund_code=fund_code,
                    expense_kind=expense_kind,
                    happened_at_utc="2026-03-16T13:00:00Z",
                    request_id="req-encumber-over",
                )
            )

        assert "reserved" in str(exc.value).lower()


def test_spend_rejects_when_over_open_encumbrance(app):
    with app.app_context():
        ensure_default_accounts()
        _project_ulid, demand_ulid, fund_code = _create_realized_demand()
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[0].key

        enc = calendar_v2.encumber_project_funds(
            calendar_v2.ProjectEncumbranceRequestDTO(
                funding_demand_ulid=demand_ulid,
                amount_cents=4000,
                fund_code=fund_code,
                expense_kind=expense_kind,
                happened_at_utc="2026-03-16T11:45:00Z",
                request_id="req-encumber-3",
            )
        )
        db.session.flush()

        with pytest.raises(Exception) as exc:
            calendar_v2.spend_project_funds(
                calendar_v2.ProjectSpendRequestDTO(
                    encumbrance_ulid=enc.encumbrance_ulid,
                    amount_cents=5000,
                    expense_kind=expense_kind,
                    payment_method="bank",
                    happened_at_utc="2026-03-16T14:00:00Z",
                    request_id="req-spend-over",
                )
            )

        assert "encumbered" in str(exc.value).lower()


def test_encumber_rejects_when_selected_fund_requires_approval(
    app,
    monkeypatch,
):
    with app.app_context():
        ensure_default_accounts()

        _project_ulid, demand_ulid, _fund_code = _create_realized_demand(
            eligible_fund_codes=(
                "general_unrestricted",
                "general_restricted",
            ),
            source_profile_key="restricted_project_grant_return_unused",
        )
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[0].key

        demand = calendar_v2.get_funding_demand(demand_ulid)
        restricted = None
        for key in demand.eligible_fund_codes:
            if key == "general_restricted":
                restricted = key
                break

        if restricted is None:
            pytest.skip("no approval-requiring restricted fund eligible")

        _seed_reserve_for_fund(
            funding_demand_ulid=demand_ulid,
            fund_code=restricted,
            amount_cents=12000,
        )

        with pytest.raises(Exception) as exc:
            calendar_v2.encumber_project_funds(
                calendar_v2.ProjectEncumbranceRequestDTO(
                    funding_demand_ulid=demand_ulid,
                    amount_cents=8000,
                    fund_code=restricted,
                    expense_kind=expense_kind,
                    happened_at_utc="2026-03-16T15:00:00Z",
                    request_id="req-encumber-restricted",
                )
            )

        msg = str(exc.value).lower()
        assert "approval" in msg or "permission" in msg


def test_encumber_project_funds_forwards_source_profile_hint(
    app,
    monkeypatch,
):
    captured: dict[str, object] = {}

    def fake_preview(req):
        captured["source_profile_key"] = req.source_profile_key
        return SimpleNamespace(
            allowed=True,
            required_approvals=(),
            reason_codes=(),
            decision_fingerprint="fp-encumber",
        )

    with app.app_context():
        ensure_default_accounts()
        _project_ulid, demand_ulid, fund_code = _create_realized_demand(
            source_profile_key="restricted_project_grant_return_unused",
        )
        tx = governance_v2.get_finance_taxonomy()
        expense_kind = tx.expense_kinds[0].key

        monkeypatch.setattr(
            governance_v2,
            "preview_funding_decision",
            fake_preview,
        )

        out = calendar_v2.encumber_project_funds(
            calendar_v2.ProjectEncumbranceRequestDTO(
                funding_demand_ulid=demand_ulid,
                amount_cents=4000,
                fund_code=fund_code,
                expense_kind=expense_kind,
                happened_at_utc="2026-03-16T20:00:00Z",
                request_id="req-encumber-source-profile",
            )
        )
        db.session.flush()

        assert out.encumbrance_ulid
        assert (
            captured["source_profile_key"]
            == "restricted_project_grant_return_unused"
        )
