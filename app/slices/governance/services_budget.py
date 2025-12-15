# app/slices/governance/services_budget.py

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.extensions.policies import (
    load_policy_budget,
    load_policy_funding,
    load_policy_journal_flags,
)

# -----------------
# DataClass Objects
# -----------------


@dataclass
class DonationIntent:
    sponsor_ulid: str
    amount_cents: int
    fund_archetype_key: Optional[str] = None
    period_label: Optional[str] = None
    source: Optional[str] = None  # e.g. 'grant:ELKS_FREEDOM'
    prospect_ulid: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class DonationClassification:
    ok: bool
    reason: str
    fund_archetype_key: str
    journal_flags: List[str]
    reporting_tags: List[str]
    restricted_project_type_keys: List[str]


@dataclass
class ProjectBudgetDemand:
    """
    Governance view of a single project's *planned* funding needs.

    This is derived from Calendar.Project and Calendar.ProjectFundingPlan
    via the calendar_v2 contract and contains no PII.
    """

    project_ulid: str
    project_title: str
    project_type_key: Optional[str]
    period_label: Optional[str]
    total_expected_cents: int
    monetary_expected_cents: int
    in_kind_expected_cents: int
    by_fund_archetype: dict[str, int]


# -----------------
# Budget / Spend semantics — skeletons
# -----------------


@dataclass
class BudgetPosition:
    """
    Read-side snapshot of a single budget “slot” from Governance’s point
    of view.

    For now this is deliberately simple and PII-free. It describes:

      * which fund archetype we are looking at,
      * which project_type (if any),
      * which period (if any),
      * the configured cap from policy_budget.json (if known),
      * the amount already spent (as provided by the caller),
      * the remaining budget (cap - spent, when both are known).

    Governance does **not** currently query Finance directly; callers are
    expected to supply `spent_cents` until we introduce a read-only
    Finance contract for “spend-to-date”.
    """

    fund_archetype_key: str
    project_type_key: Optional[str]
    period_label: Optional[str]
    cap_cents: Optional[int]
    spent_cents: Optional[int]
    remaining_cents: Optional[int]


@dataclass
class SpendIntent:
    """
    Proposed spend, as seen by Governance.

    Callers (typically Finance) construct this when they want to know
    “does this proposed spend fit within Governance budget policy?”

    All fields are PII-free and should already be validated/coerced at
    the contract boundary.
    """

    fund_archetype_key: str
    project_type_key: Optional[str]
    period_label: Optional[str]
    amount_cents: int


@dataclass
class SpendDecision:
    """
    Governance decision about a proposed spend.

    MVP behaviour:

      * ok=True, requires_override=False when either no cap is found,
        or we do not yet have a `spent_cents` view.
      * ok=False, requires_override=True when amount_cents would push
        us over the cap (once wired to policy_budget + spend-to-date).

    This is intentionally conservative: the “safety” work happens at
    the Finance layer (which can treat requires_override as a hard stop
    or a “needs admin approval” flag).
    """

    ok: bool
    reason: str

    fund_archetype_key: str
    project_type_key: Optional[str]
    period_label: Optional[str]

    amount_cents: int
    cap_cents: Optional[int]
    spent_cents: Optional[int]
    remaining_cents: Optional[int]

    requires_override: bool


# -----------------
# Donation Semantics
# -----------------


def classify_donation_intent(
    intent: DonationIntent,
) -> DonationClassification:
    """
    Apply Governance policies to a proposed donation.

    MVP behaviour:

      * Ensure fund_archetype_key is known in policy_funding.fund_archetypes.
      * Attach zero or more journal flags based on policy_journal_flags and
        the fund archetype / source token.
      * Record any coarse restriction hints (e.g. project_type) based on
        policy_budget (optional in MVP).

    This function does **not** touch Finance or Sponsors tables. It
    operates purely on policy JSON and the given intent.
    """
    if intent.amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")

    # --- funding policy ---
    funding = load_policy_funding()
    archetypes = {a["key"]: a for a in funding.get("fund_archetypes", [])}

    # Default fund archetype if caller omitted it (configurable later)
    key = intent.fund_archetype_key or "general_unrestricted"
    if key not in archetypes:
        return DonationClassification(
            ok=False,
            reason=f"unknown fund_archetype_key {key!r}",
            fund_archetype_key=key,
            journal_flags=[],
            reporting_tags=[],
            restricted_project_type_keys=[],
        )

    # --- journal flags policy ---
    flags_policy = load_policy_journal_flags()
    valid_flag_keys = {f["key"] for f in flags_policy.get("flags", [])}

    journal_flags: list[str] = []
    reporting_tags: list[str] = []

    # MVP: simple pattern — if source looks like 'grant:XYZ', and there's a
    # matching flag key 'grant_xyz', attach it.
    if intent.source and intent.source.startswith("grant:"):
        suffix = intent.source.split(":", 1)[1].lower()
        candidate = f"grant_{suffix}"
        if candidate in valid_flag_keys:
            journal_flags.append(candidate)
            reporting_tags.append(intent.source)

    # You can teach more nuanced rules later (per-archetype defaults, etc.).
    restricted_project_types: list[str] = []

    # Optional: derive a coarse restriction hint from budget policy. For MVP
    # we can leave this empty and flesh it out when Calendar is ready.
    # Example future logic:
    #
    #   budget = load_policy_budget()
    #   ... scan for lines with this fund_archetype_key to infer a set of
    #   project_type_keys to which this fund is typically applied.

    return DonationClassification(
        ok=True,
        reason="ok",
        fund_archetype_key=key,
        journal_flags=journal_flags,
        reporting_tags=reporting_tags,
        restricted_project_type_keys=restricted_project_types,
    )


def compute_budget_position(
    *,
    fund_archetype_key: str,
    project_type_key: Optional[str] = None,
    period_label: Optional[str] = None,
    current_spent_cents: Optional[int] = None,
) -> BudgetPosition:
    """
    Compute a simple budget position for a fund/project/period.

    MVP semantics:

      * Reads policy_budget.json so future code can derive a cap, but does
        not yet assume a specific schema. Until that schema is finalized,
        cap_cents will generally be None.
      * Uses `current_spent_cents` as the “already spent” view. Governance
        does not query Finance directly in v2; callers are expected to
        compute that and pass it in.
      * remaining_cents is computed when both cap_cents and spent_cents
        are known; otherwise it is None.

    This function is pure / side-effect free.
    """
    cap_cents: Optional[int] = None

    try:
        _budget = load_policy_budget()
        # TODO: when policy_budget.json is finalized, derive `cap_cents`
        # for the (fund_archetype_key, project_type_key, period_label)
        # combination from `_budget`.
    except Exception:
        # Policy read errors should not explode callers; we simply leave
        # `cap_cents` as None and let the contract layer decide how
        # conservative to be.
        cap_cents = None

    spent_cents = current_spent_cents
    remaining_cents: Optional[int] = None

    if cap_cents is not None and spent_cents is not None:
        remaining_cents = cap_cents - spent_cents

    return BudgetPosition(
        fund_archetype_key=fund_archetype_key,
        project_type_key=project_type_key,
        period_label=period_label,
        cap_cents=cap_cents,
        spent_cents=spent_cents,
        remaining_cents=remaining_cents,
    )


def preview_spend_decision(
    intent: SpendIntent,
    *,
    current_spent_cents: Optional[int] = None,
) -> SpendDecision:
    """
    Evaluate a proposed spend against Governance budget policy.

    MVP behaviour (bones only):

      * Validates that `intent.amount_cents` is > 0.
      * Calls `compute_budget_position(...)` to obtain a (cap, spent,
        remaining) snapshot.
      * If either `cap_cents` or `spent_cents` is None, returns an
        “ok” decision with `requires_override=False`. Budget policy is
        effectively advisory until fully wired.
      * If all three are known and the spend would exceed remaining,
        returns ok=False and requires_override=True with reason
        'over_budget_cap'.

    This function does **not** talk to Finance or Calendar. Callers are
    expected to provide any Finance-derived figures via
    `current_spent_cents`.
    """
    if intent.amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")

    pos = compute_budget_position(
        fund_archetype_key=intent.fund_archetype_key,
        project_type_key=intent.project_type_key,
        period_label=intent.period_label,
        current_spent_cents=current_spent_cents,
    )

    cap_cents = pos.cap_cents
    spent_cents = pos.spent_cents
    remaining_cents = pos.remaining_cents

    ok = True
    requires_override = False
    reason = "ok"

    if cap_cents is not None and spent_cents is not None:
        if remaining_cents is None:
            remaining_cents = cap_cents - spent_cents
        if intent.amount_cents > remaining_cents:
            ok = False
            requires_override = True
            reason = "over_budget_cap"

    return SpendDecision(
        ok=ok,
        reason=reason,
        fund_archetype_key=intent.fund_archetype_key,
        project_type_key=intent.project_type_key,
        period_label=intent.period_label,
        amount_cents=intent.amount_cents,
        cap_cents=cap_cents,
        spent_cents=spent_cents,
        remaining_cents=remaining_cents,
        requires_override=requires_override,
    )


def compute_budget_demands_for_period(
    period_label: str,
) -> list[ProjectBudgetDemand]:
    """
    Aggregate planned funding needs for all projects in a given period.

    This is a *read-only* governance view. It does not touch Finance or
    Sponsors tables; it pulls data from Calendar via the calendar_v2
    contract and combines it with Governance policy as needed.

    Expected calendar_v2 surface (to be implemented / wired separately):

        - calendar_v2.list_projects_for_period(period_label) -> list[ProjectDTO]
        - calendar_v2.list_project_funding_plans(project_ulid=...) ->
              list[ProjectFundingPlanDTO]

    For each project, we sum expected_amount_cents across its funding plan
    lines and break those totals down into:

        - total_expected_cents      (monetary + in-kind)
        - monetary_expected_cents   (is_in_kind == False)
        - in_kind_expected_cents    (is_in_kind == True)
        - by_fund_archetype         (fund_archetype_key -> cents)

    If Calendar has not yet implemented the required contract functions,
    this will raise NotImplementedError with a descriptive message.
    """
    # Import contracts lazily to avoid hard import cycles.
    from app.extensions.contracts import calendar_v2

    if not hasattr(calendar_v2, "list_projects_for_period"):
        raise NotImplementedError(
            "calendar_v2.list_projects_for_period(...) is not wired yet; "
            "cannot compute budget demands"
        )
    if not hasattr(calendar_v2, "list_project_funding_plans"):
        raise NotImplementedError(
            "calendar_v2.list_project_funding_plans(...) is not wired yet; "
            "cannot compute budget demands"
        )

    # Fetch projects for the given period (Calendar decides how to interpret
    # 'period_label' — e.g. '2026', 'FY2026', etc.).
    projects = calendar_v2.list_projects_for_period(period_label=period_label)

    demands: list[ProjectBudgetDemand] = []

    for proj in projects:
        proj_ulid = proj["ulid"]
        proj_title = proj.get("title") or "untitled"
        proj_type = proj.get("project_type_key")  # optional
        proj_period = proj.get("period_label")  # optional; may differ

        plans = calendar_v2.list_project_funding_plans(project_ulid=proj_ulid)

        total = 0
        monetary = 0
        in_kind = 0
        by_fund: dict[str, int] = {}

        for plan in plans:
            amt = plan.get("expected_amount_cents") or 0
            if amt < 0:
                # Defensive guard; shouldn't happen if Calendar enforces >= 0.
                continue

            total += amt

            if plan.get("is_in_kind"):
                in_kind += amt
            else:
                monetary += amt

            key = plan.get("fund_archetype_key") or "unclassified"
            by_fund[key] = by_fund.get(key, 0) + amt

        demands.append(
            ProjectBudgetDemand(
                project_ulid=proj_ulid,
                project_title=proj_title,
                project_type_key=proj_type,
                period_label=proj_period,
                total_expected_cents=total,
                monetary_expected_cents=monetary,
                in_kind_expected_cents=in_kind,
                by_fund_archetype=by_fund,
            )
        )

    return demands
