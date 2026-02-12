# app/slices/finance/services_grants.py
from __future__ import annotations

from app.extensions import db, event_bus
from app.extensions.contracts.finance_v2 import (
    GrantDTO,
    ReimbursementDTO,
)
from app.lib.chrono import now_iso8601_ms
from app.slices.finance.models import (
    Fund,
    Grant,
    Reimbursement,
)

"""
Canonical Mental Model:
services_grants → Manages grant lifecycle tied to those buckets.

TL;DR:
if it’s we got a grant
        we’re claiming money
        we’re reporting to a sponsor,
it belongs in services_grants.py.

This file should own:
create_grant(payload) -> GrantDTO
Finance representation of a grant commitment
(who, amount, period, restrictions).

prepare_grant_report(payload) -> dict
Pulls journal / balances / stats to build a sponsor-ready report.
It can call into services_report or directly hit the DB.

submit_reimbursement(payload) -> ReimbursementDTO
Represents a “we’re asking the sponsor to reimburse these costs” event;
likely tags journal entries or aggregates them.

mark_disbursed(payload) -> ReimbursementDTO
Mark the reimbursement as paid; may also call post_journal to log
incoming cash if that isn’t already recorded.

All of these are higher-level “grant program” flows that:
talk about a specific sponsor program,
tie together funds + projects + journal entries.

They can call:
services_journal for the actual GL entries,
services_funds for fund/budget info,
and Governance contracts for policy rules
(grant caps, reporting windows, etc.).



"""
# -----------------
# helpers
# -----------------


# -----------------
# Create Grant
# services_grants
# -----------------


def create_grant(payload: dict) -> GrantDTO:
    """
    Slice implementation for finance_v2.create_grant(...).

    This helper records the *configuration* of a grant award:

      * which Fund the grant flows through,
      * which Sponsor awarded it,
      * total award amount and any match requirement,
      * term dates (start/end),
      * reporting cadence,
      * which expense categories are allowable for reimbursement.

    It does **not** post any Journal entries by itself; income and
    expenses are still recorded via ``log_donation`` and ``log_expense``
    using the Fund + Project + flags. Grant rows are the “paperwork
    spine” that Governance and reporting will reference.

    Expected payload keys (from finance_v2 contract):

      Required:
        - fund_id: str
            ULID of finance_fund to associate with this grant.
        - sponsor_ulid: str
            ULID of the Sponsor (from Sponsors slice).
        - amount_awarded_cents: int
            Total award amount in cents (> 0).
        - start_on: str
            YYYY-MM-DD start date of the grant term.
        - end_on: str
            YYYY-MM-DD end date of the grant term.
        - reporting_frequency: str
            One of: 'monthly'|'quarterly'|'semiannual'|'annual'|'end_of_term'.

      Optional:
        - allowable_categories: list[str]
            Expense category labels allowed under this grant.
        - match_required_cents: int
            Required match amount in cents (>= 0).

    Raises:
        LookupError:
            If the referenced fund_id does not exist.
        ValueError:
            If required fields are missing or malformed.

    Returns:
        GrantDTO:
            PII-free summary of the grant configuration.
    """
    fund_id = payload.get("fund_id")
    sponsor_ulid = (payload.get("sponsor_ulid") or "").strip()
    amount_awarded_cents = payload.get("amount_awarded_cents")
    start_on = (payload.get("start_on") or "").strip()
    end_on = (payload.get("end_on") or "").strip()
    reporting_frequency = (payload.get("reporting_frequency") or "").strip()
    allowable_categories = payload.get("allowable_categories") or []
    match_required_cents = int(payload.get("match_required_cents") or 0)

    # Basic validation – heavy shape checking is done in the contract;
    # here we just guard against obviously broken payloads.
    if not fund_id:
        raise ValueError("fund_id is required")
    if not sponsor_ulid:
        raise ValueError("sponsor_ulid is required")
    if not isinstance(amount_awarded_cents, int) or amount_awarded_cents <= 0:
        raise ValueError("amount_awarded_cents must be a positive integer")
    if not start_on or not end_on:
        raise ValueError("start_on and end_on are required")

    allowed_freq = {
        "monthly",
        "quarterly",
        "semiannual",
        "annual",
        "end_of_term",
    }
    if reporting_frequency not in allowed_freq:
        raise ValueError(
            "reporting_frequency must be one of: "
            "monthly|quarterly|semiannual|annual|end_of_term"
        )

    fund = db.session.get(Fund, fund_id)
    if fund is None:
        raise LookupError(f"fund {fund_id!r} not found")

    # Normalise categories to a list of strings
    if not isinstance(allowable_categories, (list, tuple)):
        raise ValueError("allowable_categories must be a list of strings")
    cat_list: list[str] = []
    for c in allowable_categories:
        if not isinstance(c, str):
            raise ValueError(
                "all allowable_categories entries must be strings"
            )
        c_stripped = c.strip()
        if c_stripped:
            cat_list.append(c_stripped)

    # Create the Grant row
    grant = Grant(
        fund_id=fund.ulid,
        sponsor_ulid=sponsor_ulid,
        amount_awarded_cents=amount_awarded_cents,
        match_required_cents=match_required_cents,
        start_on=start_on,
        end_on=end_on,
        reporting_frequency=reporting_frequency,
        active=True,
    )
    grant.allowable_categories = cat_list

    db.session.add(grant)
    db.session.flush()

    # Emit a lightweight event for observability / ledger fan-out
    event_bus.emit(
        domain="finance",
        operation="grant_created",
        entity="grant",
        entity_ulid=grant.ulid,
        meta={
            "fund_id": fund.ulid,
            "sponsor_ulid": sponsor_ulid,
            "amount_awarded_cents": amount_awarded_cents,
            "match_required_cents": match_required_cents,
            "start_on": start_on,
            "end_on": end_on,
            "reporting_frequency": reporting_frequency,
            "allowable_categories": cat_list,
        },
    )

    return GrantDTO(
        id=grant.ulid,
        fund_id=fund.ulid,
        sponsor_ulid=grant.sponsor_ulid,
        amount_awarded_cents=grant.amount_awarded_cents,
        start_on=grant.start_on,
        end_on=grant.end_on,
        reporting_frequency=grant.reporting_frequency,
        allowable_categories=grant.allowable_categories,
        match_required_cents=grant.match_required_cents,
    )


# -----------------
# Submit Reimbursement
# services_grants
# -----------------


def submit_reimbursement(payload: dict) -> ReimbursementDTO:
    """
    Slice implementation for finance_v2.submit_reimbursement(...).

    Paperwork-only: records a reimbursement request against a Grant.
    No Journal entries are posted here; when the Sponsor actually
    pays, cash is recorded separately via ``log_donation(...)``
    (typically referencing this reimbursement via an external_ref).

    Expected payload keys (from finance_v2 contract):

      Required:
        - grant_id: str
            ULID of the Grant this reimbursement is tied to.
        - submitted_on: str
            YYYY-MM-DD date when the request is submitted.
        - period_start: str
            YYYY-MM-DD start date of the covered period.
        - period_end: str
            YYYY-MM-DD end date of the covered period.
        - amount_cents: int
            Requested amount in cents (> 0).

      Optional:
        - status: str
            Initial workflow state; usually 'submitted' (default) or 'draft'.
        - actor_ulid: str
            Actor ULID for audit/ledger purposes.
        - request_id: str
            Request ULID (e.g. HTTP correlation id); if omitted,
            the reimbursement ULID will be used as request_id.

    Raises:
        LookupError:
            If the grant_id does not exist or is inactive.
        ValueError:
            If required fields are missing or malformed
            (bad dates, non-positive amount, bad status).
    """
    grant_id = payload.get("grant_id")
    submitted_on = (payload.get("submitted_on") or "").strip()
    period_start = (payload.get("period_start") or "").strip()
    period_end = (payload.get("period_end") or "").strip()
    amount_cents = payload.get("amount_cents")
    status = (payload.get("status") or "submitted").strip() or "submitted"

    actor_ulid = payload.get("actor_ulid")
    request_id = payload.get("request_id")

    if not grant_id:
        raise ValueError("grant_id is required")
    if not submitted_on:
        raise ValueError("submitted_on is required")
    if not period_start or not period_end:
        raise ValueError("period_start and period_end are required")

    if not isinstance(amount_cents, int) or amount_cents <= 0:
        raise ValueError("amount_cents must be a positive integer")

    allowed_status = {"draft", "submitted", "approved", "paid", "void"}
    if status not in allowed_status:
        raise ValueError(
            "status must be one of: draft|submitted|approved|paid|void"
        )

    grant = db.session.get(Grant, grant_id)
    if grant is None or not grant.active:
        raise LookupError(f"grant {grant_id!r} not found or inactive")

    # You *can* add date-order checks here later
    # (e.g. ensure period_start <= period_end), but for now we just
    # require non-empty strings; Governance can enforce semantics.

    reimbursement = Reimbursement(
        grant_id=grant.ulid,
        submitted_on=submitted_on,
        period_start=period_start,
        period_end=period_end,
        amount_cents=amount_cents,
        status=status,
    )

    db.session.add(reimbursement)
    db.session.flush()

    # Ledger hook – paperwork-only, no money moves here.
    # event_bus signature is canonical: (domain, operation, request_id, actor_ulid, target_ulid, ...)
    event_bus.emit(
        domain="finance",
        operation="grant_reimbursement_submitted",
        request_id=request_id or reimbursement.ulid,
        actor_ulid=actor_ulid,
        target_ulid=reimbursement.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={"grant_id": grant.ulid},
        meta={
            "amount_cents": amount_cents,
            "submitted_on": submitted_on,
            "period_start": period_start,
            "period_end": period_end,
            "status": status,
        },
        chain_key="finance.grant",
    )

    return ReimbursementDTO(
        id=reimbursement.ulid,
        grant_id=grant.ulid,
        submitted_on=reimbursement.submitted_on,
        period_start=reimbursement.period_start,
        period_end=reimbursement.period_end,
        amount_cents=reimbursement.amount_cents,
        status=reimbursement.status,
    )


# -----------------
# Mark Disbursement
# services_grants
# -----------------


def mark_disbursed(payload: dict) -> ReimbursementDTO:
    """
    Slice implementation for finance_v2.mark_disbursed(...).

    Paperwork-only: updates the status of a Reimbursement to reflect that
    the Sponsor has paid (or that the request has been voided).

    **No Journal entries are posted here.** When actual cash arrives, it
    is recorded separately via ``log_donation(...)``, typically with an
    external_ref pointing back to this reimbursement.

    Expected payload keys (from finance_v2 contract):

      Required:
        - reimbursement_id: str
            ULID of the Reimbursement row to update.

      Optional:
        - status: str
            New workflow status. For mark_disbursed we intentionally
            keep this narrow to:
                * "paid"  – Sponsor has paid the reimbursement
                * "void"  – cancelled / written off
            Default is "paid".
        - actor_ulid: str
            Actor ULID for audit/ledger purposes.
        - request_id: str
            Request ULID (e.g. HTTP correlation id); if omitted, the
            reimbursement ULID will be used as request_id.

    Raises:
        LookupError:
            If the reimbursement_id does not exist.
        ValueError:
            If required fields are missing or malformed, or if status
            is not one of the allowed values.
    """
    reimbursement_id = payload.get("reimbursement_id")
    new_status = (payload.get("status") or "paid").strip() or "paid"

    actor_ulid = payload.get("actor_ulid")
    request_id = payload.get("request_id")

    if not reimbursement_id:
        raise ValueError("reimbursement_id is required")

    allowed_status = {"paid", "void"}
    if new_status not in allowed_status:
        raise ValueError("status must be 'paid' or 'void' for mark_disbursed")

    reimbursement = db.session.get(Reimbursement, reimbursement_id)
    if reimbursement is None:
        raise LookupError(f"reimbursement {reimbursement_id!r} not found")

    old_status = reimbursement.status
    if old_status == new_status:
        # Idempotent; still emit an event so the ledger shows the call.
        pass
    else:
        reimbursement.status = new_status
        db.session.flush()

    # Ledger hook – status change only; no money moves here.
    event_bus.emit(
        domain="finance",
        operation="grant_reimbursement_status_changed",
        request_id=request_id or reimbursement.ulid,
        actor_ulid=actor_ulid,
        target_ulid=reimbursement.ulid,
        happened_at_utc=now_iso8601_ms(),
        refs={"grant_id": reimbursement.grant_id},
        meta={
            "from_status": old_status,
            "to_status": new_status,
        },
        chain_key="finance.grant",
    )

    return ReimbursementDTO(
        id=reimbursement.ulid,
        grant_id=reimbursement.grant_id,
        submitted_on=reimbursement.submitted_on,
        period_start=reimbursement.period_start,
        period_end=reimbursement.period_end,
        amount_cents=reimbursement.amount_cents,
        status=reimbursement.status,
    )


# -----------------
# Prepare Grant Report
# services_grants
# -----------------


def prepare_grant_report(payload: dict) -> dict:
    """
    Placeholder for finance_v2.prepare_grant_report(...).

    Post-MVP hook for generating a PII-free summary of activity for a
    given Grant and reporting period. Intended to feed grant reporting
    packets and dashboards, *not* to move money.

    Tentative payload shape:

        {
            "grant_id": "<ULID of Grant>",
            "period_start": "YYYY-MM-DD",
            "period_end": "YYYY-MM-DD",
        }

    Expected return shape (to be finalised later):

        {
            "grant": { ... basic GrantDTO-ish fields ... },
            "period": {
                "start": "YYYY-MM-DD",
                "end": "YYYY-MM-DD",
            },
            "totals": {
                "expenses_cents": int,
                "by_category": { "FOOD": 12345, ... },
            },
        }

    For now this is deliberately *not* implemented; calling it will
    raise NotImplementedError so we don’t accidentally rely on a
    half-built report.
    """
    raise NotImplementedError(
        "Grant reporting is post-MVP and not implemented yet"
    )
