# app/slices/sponsors/taxonomy_crm.py

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CRMFactorSpec",
    "CRM_FACTOR_STRENGTHS",
    "CRM_FACTOR_SOURCES",
    "CRM_FACTORS",
    "SPONSOR_CRM_FACTOR_NOTE_MAX",
    "all_crm_factor_keys",
    "all_crm_buckets",
    "all_crm_strengths",
    "all_crm_sources",
    "bucket_for_factor",
    "factor_spec",
]

CRM_FACTOR_STRENGTHS = (
    "observed",
    "recurring",
    "strong_pattern",
)

CRM_FACTOR_SOURCES = (
    "operator",
    "observed",
    "inferred",
)

SPONSOR_CRM_FACTOR_NOTE_MAX = 300


@dataclass(frozen=True)
class CRMFactorSpec:
    key: str
    bucket: str
    label: str
    description: str


CRM_FACTORS: tuple[CRMFactorSpec, ...] = (
    CRMFactorSpec(
        "mission_local_veterans",
        "mission",
        "Local veterans",
        "Typically supports local veteran-serving work.",
    ),
    CRMFactorSpec(
        "mission_housing",
        "mission",
        "Housing",
        "Typically supports housing or housing stabilization asks.",
    ),
    CRMFactorSpec(
        "mission_basic_needs",
        "mission",
        "Basic needs",
        "Typically supports basic-needs requests.",
    ),
    CRMFactorSpec(
        "mission_food_support",
        "mission",
        "Food support",
        "Typically supports food or grocery-related requests.",
    ),
    CRMFactorSpec(
        "mission_transportation",
        "mission",
        "Transportation",
        "Typically supports transportation-related requests.",
    ),
    CRMFactorSpec(
        "mission_health_wellness",
        "mission",
        "Health and wellness",
        "Typically supports health and wellness requests.",
    ),
    CRMFactorSpec(
        "mission_events_outreach",
        "mission",
        "Events and outreach",
        "Typically supports events or community outreach.",
    ),
    CRMFactorSpec(
        "mission_emergency_relief",
        "mission",
        "Emergency relief",
        "Typically supports urgent or crisis-response asks.",
    ),
    CRMFactorSpec(
        "mission_general_ops",
        "mission",
        "General operations",
        "Typically supports general operating needs.",
    ),
    CRMFactorSpec(
        "mission_long_term_programs",
        "mission",
        "Long-term programs",
        "Typically supports ongoing or programmatic work.",
    ),
    CRMFactorSpec(
        "mission_one_time_cases",
        "mission",
        "One-time cases",
        "Typically supports one-off case needs.",
    ),
    CRMFactorSpec(
        "restriction_flexible",
        "restriction",
        "Flexible restrictions",
        "Usually flexible about restrictions.",
    ),
    CRMFactorSpec(
        "restriction_purpose_bound",
        "restriction",
        "Purpose-bound",
        "Usually expects a specific purpose or scope.",
    ),
    CRMFactorSpec(
        "restriction_geo_local_only",
        "restriction",
        "Local only",
        "Usually expects local geographic impact.",
    ),
    CRMFactorSpec(
        "restriction_population_veterans_only",
        "restriction",
        "Veterans only",
        "Usually expects veteran-only benefit.",
    ),
    CRMFactorSpec(
        "restriction_docs_required",
        "restriction",
        "Documentation required",
        "Usually expects supporting documentation.",
    ),
    CRMFactorSpec(
        "restriction_receipts_required",
        "restriction",
        "Receipts required",
        "Usually expects receipts or proof of spend.",
    ),
    CRMFactorSpec(
        "restriction_reimbursement_preferred",
        "restriction",
        "Reimbursement preferred",
        "Usually prefers reimbursement over advance funding.",
    ),
    CRMFactorSpec(
        "restriction_advance_funding_rare",
        "restriction",
        "Advance funding rare",
        "Rarely comfortable with advance funding.",
    ),
    CRMFactorSpec(
        "restriction_reporting_sensitive",
        "restriction",
        "Reporting sensitive",
        "Usually expects reporting or formal follow-up.",
    ),
    CRMFactorSpec(
        "style_cash_grant",
        "style",
        "Cash grant",
        "Commonly supports via direct cash grant.",
    ),
    CRMFactorSpec(
        "style_reimbursement",
        "style",
        "Reimbursement",
        "Commonly supports via reimbursement.",
    ),
    CRMFactorSpec(
        "style_in_kind_goods",
        "style",
        "In-kind goods",
        "Commonly supports with goods or materials.",
    ),
    CRMFactorSpec(
        "style_service_support",
        "style",
        "Service support",
        "Commonly supports with services or facilities.",
    ),
    CRMFactorSpec(
        "style_event_sponsorship",
        "style",
        "Event sponsorship",
        "Commonly supports events or event costs.",
    ),
    CRMFactorSpec(
        "style_matching",
        "style",
        "Matching",
        "Commonly supports with a match structure.",
    ),
    CRMFactorSpec(
        "style_recurring_support",
        "style",
        "Recurring support",
        "Commonly supports on a recurring basis.",
    ),
    CRMFactorSpec(
        "style_one_time_support",
        "style",
        "One-time support",
        "Commonly supports as a one-time gift.",
    ),
    CRMFactorSpec(
        "capacity_small_asks",
        "capacity",
        "Small asks",
        "Typically comfortable with smaller asks.",
    ),
    CRMFactorSpec(
        "capacity_medium_asks",
        "capacity",
        "Medium asks",
        "Typically comfortable with medium asks.",
    ),
    CRMFactorSpec(
        "capacity_large_asks",
        "capacity",
        "Large asks",
        "Typically comfortable with larger asks.",
    ),
    CRMFactorSpec(
        "capacity_quick_turnaround",
        "capacity",
        "Quick turnaround",
        "Often able to act quickly.",
    ),
    CRMFactorSpec(
        "capacity_slow_review_cycle",
        "capacity",
        "Slow review cycle",
        "Often requires a slower review cycle.",
    ),
    CRMFactorSpec(
        "capacity_seasonal_giving",
        "capacity",
        "Seasonal giving",
        "Often gives on a seasonal cadence.",
    ),
    CRMFactorSpec(
        "capacity_annual_cycle",
        "capacity",
        "Annual cycle",
        "Often gives on an annual cadence.",
    ),
    CRMFactorSpec(
        "friction_board_review",
        "friction",
        "Board review",
        "Often needs board-level review.",
    ),
    CRMFactorSpec(
        "friction_docs_heavy",
        "friction",
        "Documentation heavy",
        "Often expects substantial supporting documentation.",
    ),
    CRMFactorSpec(
        "friction_receipt_packet_sensitive",
        "friction",
        "Receipt packet sensitive",
        "Often sensitive to receipt-packet completeness.",
    ),
    CRMFactorSpec(
        "friction_follow_up_needed",
        "friction",
        "Follow-up needed",
        "Often needs reminders or follow-up touches.",
    ),
    CRMFactorSpec(
        "friction_slow_response",
        "friction",
        "Slow response",
        "Often slow to respond.",
    ),
    CRMFactorSpec(
        "friction_unclear_decider",
        "friction",
        "Unclear decider",
        "Decision-maker is often unclear.",
    ),
    CRMFactorSpec(
        "friction_manual_review_common",
        "friction",
        "Manual review common",
        "Often merits manual operator review.",
    ),
    CRMFactorSpec(
        "relationship_new_prospect",
        "relationship",
        "New prospect",
        "Little or no prior giving history.",
    ),
    CRMFactorSpec(
        "relationship_prior_success",
        "relationship",
        "Prior success",
        "Has successfully supported work before.",
    ),
    CRMFactorSpec(
        "relationship_repeat_supporter",
        "relationship",
        "Repeat supporter",
        "Has supported repeatedly.",
    ),
    CRMFactorSpec(
        "relationship_recent_contact",
        "relationship",
        "Recent contact",
        "Recent relationship activity exists.",
    ),
    CRMFactorSpec(
        "relationship_lapsed",
        "relationship",
        "Lapsed",
        "Relationship appears lapsed or stale.",
    ),
    CRMFactorSpec(
        "relationship_prior_decline",
        "relationship",
        "Prior decline",
        "Prior decline history exists.",
    ),
    CRMFactorSpec(
        "relationship_follow_through_strong",
        "relationship",
        "Strong follow-through",
        "Good follow-through history exists.",
    ),
    CRMFactorSpec(
        "relationship_follow_through_mixed",
        "relationship",
        "Mixed follow-through",
        "Follow-through history is mixed.",
    ),
)

_BY_KEY = {spec.key: spec for spec in CRM_FACTORS}


def all_crm_factor_keys() -> list[str]:
    return [spec.key for spec in CRM_FACTORS]


def all_crm_buckets() -> list[str]:
    return sorted({spec.bucket for spec in CRM_FACTORS})


def all_crm_strengths() -> list[str]:
    return list(CRM_FACTOR_STRENGTHS)


def all_crm_sources() -> list[str]:
    return list(CRM_FACTOR_SOURCES)


def factor_spec(key: str) -> CRMFactorSpec | None:
    return _BY_KEY.get(str(key or "").strip())


def bucket_for_factor(key: str) -> str | None:
    spec = factor_spec(key)
    return spec.bucket if spec else None
