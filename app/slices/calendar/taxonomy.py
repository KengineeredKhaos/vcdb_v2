from __future__ import annotations

from typing import Final

# -----------------
# Project-specific
# Taxonomy
# -----------------
"""
The implied transition rules:

Draft side
draft → ready_for_review
ready_for_review → governance_review_pending
governance_review_pending → returned_for_revision
governance_review_pending → approved_for_publish
returned_for_revision → draft or directly back to ready_for_review

Published demand side
published → funding_in_progress
funding_in_progress → funded
funding_in_progress → executing
funded → executing
executing → closed

Operators do not mark "funded”.
Calendar determines "funded" based on recognized support coverage.
"""

PROJECT_STATUSES: Final[tuple[str, ...]] = (
    "draft_planning",
    "tasking_in_progress",
    "budget_under_development",
    "budget_ready",
    "execution_underway",
    "closeout_pending",
    "closed",
)

DEMAND_DRAFT_STATUSES: Final[tuple[str, ...]] = (
    "draft",
    "ready_for_review",
    "governance_review_pending",
    "returned_for_revision",
    "approved_for_publish",
)

# -----------------
# Task-specific
# Taxonomy
# -----------------


# -----------------
# Funding demand &
# OpsFloat taxonomy
# -----------------

FUNDING_DEMAND_STATUSES: Final[tuple[str, ...]] = (
    "published",
    "funding_in_progress",
    "funded",
    "executing",
    "closed",
)

# Compatibility hold-over only. This is Scaffolding-only.
# Do not expand this unless Calendar still has an active consumer that
# truly needs it. Governance now owns the canonical source semantics.
PROJECT_FUNDING_SOURCE_KINDS: Final[tuple[str, ...]] = (
    "operations_seed",
    "operations_backfill",
    "operations_bridge",
    "sponsor_cash",
    "grant_cash",
    "grant_reimbursement",
    "in_kind",
)

# Calendar workflow vocabulary.
# Governance owns the canonical support-mode semantics.
OPS_FLOAT_SUPPORT_MODES: Final[tuple[str, ...]] = (
    "seed",
    "backfill",
    "bridge",
)

OPS_FLOAT_ACTIONS: Final[tuple[str, ...]] = (
    "allocate",
    "repay",
    "forgive",
)

# -----------------
# Task taxonomy
# -----------------

# Fallback advisory value only.
DEFAULT_FINANCE_HINT_EXPENSE_KINDS: Final[tuple[str, ...]] = (
    "direct_program_costs",
)

# Calendar task taxonomy is slice-local workflow vocabulary.
# finance_hints are advisory cues only and must reference canonical
# Governance keys, typically found in policy_finance_taxonomy.
# Calendar does not own finance semantics.
# Calendar task kinds may suggest canonical Governance semantic keys,
# but Governance remains the source of truth for meaning, validation,
# selector behavior, and approvals.
#
# finance_hints shape:
#   default_expense_kind: primary suggested Governance expense key
#   allowed_expense_kinds: bounded alternate Governance expense keys
#   default_spending_class: primary suggested Governance spending class

TASK_KINDS: Final[dict[str, dict]] = {
    "fundraising_cultivation": {
        "label": "Sponsor cultivation / outreach",
        "finance_hints": {
            "default_expense_kind": "market_cultivation",
            "allowed_expense_kinds": [
                "market_cultivation",
            ],
            "default_spending_class": "admin",
        },
    },
    "event_catering": {
        "label": "Catering/food service",
        "finance_hints": {
            "default_expense_kind": "event_expense",
            "allowed_expense_kinds": [
                "event_food",
                "event_expense",
            ],
            "default_spending_class": "events",
        },
    },
    "event_equipment_rental": {
        "label": "Equipment rental",
        "finance_hints": {
            "default_expense_kind": "event_expense",
            "allowed_expense_kinds": [
                "event_expense",
                "equipment",
            ],
            "default_spending_class": "events",
        },
    },
    "event_insurance": {
        "label": "Insurance (event)",
        "finance_hints": {
            "default_expense_kind": "insurance",
            "allowed_expense_kinds": [
                "insurance",
                "event_expense",
            ],
            "default_spending_class": "events",
        },
    },
    "event_marketing": {
        "label": "Event marketing/ads",
        "finance_hints": {
            "default_expense_kind": "market_cultivation",
            "allowed_expense_kinds": [
                "market_cultivation",
                "printing",
                "event_expense",
            ],
            "default_spending_class": "events",
        },
    },
    "event_swag": {
        "label": "Event doorprizes & swagbag bitss",
        "finance_hints": {
            "default_expense_kind": "market_cultivation",
            "allowed_expense_kinds": [
                "market_cultivation",
                "event_expense",
            ],
            "default_spending_class": "events",
        },
    },
    "event_permits": {
        "label": "Permits",
        "finance_hints": {
            "default_expense_kind": "event_expense",
            "allowed_expense_kinds": [
                "event_expense",
                "professional_fees",
            ],
            "default_spending_class": "events",
        },
    },
    "event_printing": {
        "label": "Event printing",
        "finance_hints": {
            "default_expense_kind": "printing",
            "allowed_expense_kinds": [
                "printing",
                "event_expense",
                "market_cultivation",
            ],
            "default_spending_class": "events",
        },
    },
    "event_sanitation": {
        "label": "Sanitation",
        "finance_hints": {
            "default_expense_kind": "event_expense",
            "allowed_expense_kinds": [
                "event_expense",
                "supplies",
            ],
            "default_spending_class": "events",
        },
    },
    "event_security": {
        "label": "Security",
        "finance_hints": {
            "default_expense_kind": "event_expense",
            "allowed_expense_kinds": [
                "event_expense",
                "professional_fees",
            ],
            "default_spending_class": "events",
        },
    },
    "event_signage": {
        "label": "Signage/banners",
        "finance_hints": {
            "default_expense_kind": "event_expense",
            "allowed_expense_kinds": [
                "event_expense",
                "printing",
                "market_cultivation",
            ],
            "default_spending_class": "events",
        },
    },
    "event_venue_rental": {
        "label": "Venue rental",
        "finance_hints": {
            "default_expense_kind": "event_expense",
            "allowed_expense_kinds": [
                "event_expense",
                "occupancy",
            ],
            "default_spending_class": "events",
        },
    },
    "fundraising_design": {
        "label": "Fundraising design",
        "finance_hints": {
            "default_expense_kind": "market_cultivation",
            "allowed_expense_kinds": [
                "market_cultivation",
                "printing",
            ],
            "default_spending_class": "admin",
        },
    },
    "fundraising_postage": {
        "label": "Fundraising postage",
        "finance_hints": {
            "default_expense_kind": "postage_shipping",
            "allowed_expense_kinds": [
                "postage_shipping",
                "market_cultivation",
            ],
            "default_spending_class": "admin",
        },
    },
    "fundraising_printing": {
        "label": "Fundraising printing",
        "finance_hints": {
            "default_expense_kind": "printing",
            "allowed_expense_kinds": [
                "printing",
                "market_cultivation",
            ],
            "default_spending_class": "admin",
        },
    },
    "fundraising_supplies": {
        "label": "Fundraising supplies",
        "finance_hints": {
            "default_expense_kind": "market_cultivation",
            "allowed_expense_kinds": [
                "market_cultivation",
                "supplies",
            ],
            "default_spending_class": "admin",
        },
    },
    "inbound_freight": {
        "label": "Inbound freight",
        "finance_hints": {
            "default_expense_kind": "postage_shipping",
            "allowed_expense_kinds": [
                "postage_shipping",
                "cogs",
            ],
            "default_spending_class": "logistics",
        },
    },
    "insurance_annual": {
        "label": "Insurance (annual)",
        "finance_hints": {
            "default_expense_kind": "insurance",
            "allowed_expense_kinds": [
                "insurance",
            ],
            "default_spending_class": "facilities",
        },
    },
    "internet_office": {
        "label": "Internet service",
        "finance_hints": {
            "default_expense_kind": "occupancy",
            "allowed_expense_kinds": [
                "occupancy",
            ],
            "default_spending_class": "facilities",
        },
    },
    "merch_inventory_purchase": {
        "label": "Merch inventory purchase",
        "finance_hints": {
            "default_expense_kind": "cogs",
            "allowed_expense_kinds": [
                "cogs",
                "supplies",
            ],
            "default_spending_class": "logistics",
        },
    },
    "merchant_fees": {
        "label": "Bank/merchant processing fees",
        "finance_hints": {
            "default_expense_kind": "bank_merchant_fees",
            "allowed_expense_kinds": [
                "bank_merchant_fees",
            ],
            "default_spending_class": "admin",
        },
    },
    "office_supplies": {
        "label": "Office supplies",
        "finance_hints": {
            "default_expense_kind": "supplies",
            "allowed_expense_kinds": [
                "supplies",
            ],
            "default_spending_class": "admin",
        },
    },
    "packaging_supplies": {
        "label": "Packaging supplies",
        "finance_hints": {
            "default_expense_kind": "supplies",
            "allowed_expense_kinds": [
                "supplies",
                "cogs",
            ],
            "default_spending_class": "logistics",
        },
    },
    "phone_office": {
        "label": "Phone service",
        "finance_hints": {
            "default_expense_kind": "occupancy",
            "allowed_expense_kinds": [
                "occupancy",
            ],
            "default_spending_class": "facilities",
        },
    },
    "postage_shipping": {
        "label": "Postage & shipping",
        "finance_hints": {
            "default_expense_kind": "postage_shipping",
            "allowed_expense_kinds": [
                "postage_shipping",
            ],
            "default_spending_class": "admin",
        },
    },
    "professional_services": {
        "label": "Professional services",
        "finance_hints": {
            "default_expense_kind": "professional_fees",
            "allowed_expense_kinds": [
                "professional_fees",
            ],
            "default_spending_class": "admin",
        },
    },
    "program_medical_supplies": {
        "label": "Medical/first-aid supplies",
        "finance_hints": {
            "default_expense_kind": "direct_program_costs",
            "allowed_expense_kinds": [
                "direct_program_costs",
                "supplies",
            ],
            "default_spending_class": "basic_needs",
        },
    },
    "program_transport": {
        "label": "Fuel/transport",
        "finance_hints": {
            "default_expense_kind": "direct_program_costs",
            "allowed_expense_kinds": [
                "direct_program_costs",
                "fuel",
                "travel",
                "mileage",
            ],
            "default_spending_class": "basic_needs",
        },
    },
    "rent_office": {
        "label": "Office rent",
        "finance_hints": {
            "default_expense_kind": "occupancy",
            "allowed_expense_kinds": [
                "occupancy",
            ],
            "default_spending_class": "facilities",
        },
    },
    "software_subscriptions": {
        "label": "Software subscriptions",
        "finance_hints": {
            "default_expense_kind": "software_it",
            "allowed_expense_kinds": [
                "software_it",
            ],
            "default_spending_class": "admin",
        },
    },
    "unclassified": {
        "label": "Unclassified / admin review",
        "finance_hints": {
            "default_expense_kind": "other_expense",
            "allowed_expense_kinds": [
                "other_expense",
            ],
            "default_spending_class": "admin",
        },
    },
    "utilities_office": {
        "label": "Utilities",
        "finance_hints": {
            "default_expense_kind": "occupancy",
            "allowed_expense_kinds": [
                "occupancy",
            ],
            "default_spending_class": "facilities",
        },
    },
    "volunteer_swag": {
        "label": "Volunteer recognition & swag",
        "finance_hints": {
            "default_expense_kind": "market_cultivation",
            "allowed_expense_kinds": [
                "market_cultivation",
                "supplies",
            ],
            "default_spending_class": "admin",
        },
    },
}
