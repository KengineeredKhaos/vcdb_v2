from __future__ import annotations

from typing import Final

# -----------------
# Funding demand &
# OpsFloat taxonomy
# -----------------

FUNDING_DEMAND_STATUSES: Final[tuple[str, ...]] = (
    "draft",
    "published",
    "funding_in_progress",
    "funded",
    "executing",
    "closed",
)

PROJECT_FUNDING_SOURCE_KINDS: Final[tuple[str, ...]] = (
    "operations_seed",
    "operations_backfill",
    "operations_bridge",
    "sponsor_cash",
    "grant_cash",
    "grant_reimbursement",
    "in_kind",
)
"""
DRIFT RISK -> PROJECT_FUNDING_SOURCE_KINDS
This is close in spirit to the Governance-side source_kinds / support_modes
split, so it has drift risk. Not broken right now, but flagged for
cleanup later so Calendar does not maintain a second near-duplicate
funding-source language.
"""

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


# Calendar/Operations taxonomy (slice-local).
# This used to live in Governance as policy_operations.json.

DEFAULT_FINANCE_HINT_EXPENSE_KINDS: Final[tuple[str, ...]] = (
    "direct_program_costs",
)

# Task kinds: stable keys and human labels.
# finance_hints are advisory tags for Finance/Reporting integrations.
TASK_KINDS: Final[dict[str, dict]] = {
    "event_catering": {
        "finance_hints": {"expense_kinds": ["event_food", "event_expense"]},
        "label": "Catering/food service",
    },
    "event_equipment_rental": {
        "finance_hints": {"expense_kinds": ["event_expense"]},
        "label": "Equipment rental",
    },
    "event_insurance": {
        "finance_hints": {"expense_kinds": ["insurance"]},
        "label": "Insurance (event)",
    },
    "event_marketing": {
        "finance_hints": {"expense_kinds": ["market_cultivation"]},
        "label": "Event marketing/ads",
    },
    "event_permits": {
        "finance_hints": {"expense_kinds": ["event_expense"]},
        "label": "Permits",
    },
    "event_printing": {
        "finance_hints": {
            "expense_kinds": [
                "event_expense",
                "printing",
                "market_cultivation",
            ]
        },
        "label": "Event printing",
    },
    "event_sanitation": {
        "finance_hints": {"expense_kinds": ["event_expense"]},
        "label": "Sanitation",
    },
    "event_security": {
        "finance_hints": {"expense_kinds": ["event_expense"]},
        "label": "Security",
    },
    "event_signage": {
        "finance_hints": {
            "expense_kinds": ["event_expense", "market_cultivation"]
        },
        "label": "Signage/banners",
    },
    "event_venue_rental": {
        "finance_hints": {"expense_kinds": ["event_expense"]},
        "label": "Venue rental",
    },
    "fundraising_design": {
        "finance_hints": {"expense_kinds": ["market_cultivation"]},
        "label": "Fundraising design",
    },
    "fundraising_postage": {
        "finance_hints": {
            "expense_kinds": ["market_cultivation", "postage_shipping"]
        },
        "label": "Fundraising postage",
    },
    "fundraising_printing": {
        "finance_hints": {"expense_kinds": ["market_cultivation"]},
        "label": "Fundraising printing",
    },
    "fundraising_supplies": {
        "finance_hints": {"expense_kinds": ["market_cultivation"]},
        "label": "Fundraising supplies",
    },
    "inbound_freight": {
        "finance_hints": {"expense_kinds": ["postage_shipping", "cogs"]},
        "label": "Inbound freight",
    },
    "insurance_annual": {
        "finance_hints": {"expense_kinds": ["insurance"]},
        "label": "Insurance (annual)",
    },
    "internet_office": {
        "finance_hints": {"expense_kinds": ["occupancy"]},
        "label": "Internet service",
    },
    "merch_inventory_purchase": {
        "finance_hints": {"expense_kinds": ["cogs"]},
        "label": "Merch inventory purchase",
    },
    "merchant_fees": {
        "finance_hints": {"expense_kinds": ["bank_merchant_fees"]},
        "label": "Bank/merchant processing fees",
    },
    "office_supplies": {
        "finance_hints": {"expense_kinds": ["supplies"]},
        "label": "Office supplies",
    },
    "packaging_supplies": {
        "finance_hints": {"expense_kinds": ["supplies", "cogs"]},
        "label": "Packaging supplies",
    },
    "phone_office": {
        "finance_hints": {"expense_kinds": ["occupancy"]},
        "label": "Phone service",
    },
    "postage_shipping": {
        "finance_hints": {"expense_kinds": ["postage_shipping"]},
        "label": "Postage & shipping",
    },
    "professional_services": {
        "finance_hints": {"expense_kinds": ["professional_fees"]},
        "label": "Professional services",
    },
    "program_medical_supplies": {
        "finance_hints": {
            "expense_kinds": ["supplies", "direct_program_costs"]
        },
        "label": "Medical/first-aid supplies",
    },
    "program_transport": {
        "finance_hints": {
            "expense_kinds": ["direct_program_costs", "fuel", "travel"]
        },
        "label": "Fuel/transport",
    },
    "rent_office": {
        "finance_hints": {"expense_kinds": ["occupancy"]},
        "label": "Office rent",
    },
    "software_subscriptions": {
        "finance_hints": {"expense_kinds": ["software_it"]},
        "label": "Software subscriptions",
    },
    "unclassified": {
        "finance_hints": {"expense_kinds": ["other_expense"]},
        "label": "Unclassified / admin review",
    },
    "utilities_office": {
        "finance_hints": {"expense_kinds": ["occupancy"]},
        "label": "Utilities",
    },
    "volunteer_swag": {
        "finance_hints": {
            "expense_kinds": ["market_cultivation", "supplies"]
        },
        "label": "Volunteer swag",
    },
}
