# app/slices/resources/taxonomy.py

from __future__ import annotations

from typing import Final

__all__ = [
    "is_valid_readiness_status",
    "is_valid_mou_status",
    "all_capability_codes",
    "RESOURCE_READINESS_STATES",
    "RESOURCE_MOU_STATUSES",
    "RESOURCE_CAPABILITY_NOTE_MAX",
    # POC constraints
    "POC_SCOPES",
    "DEFAULT_POC_SCOPE",
    "POC_MAX_RANK",
]

# -----------------
# Notes Length Knob
# -----------------

# how long a capability note can be (operator hint)
RESOURCE_CAPABILITY_NOTE_MAX: int = 240  # pick your number

# -----------------
# Helper/Prep
# Functions
# -----------------


def is_valid_readiness_status(v: str) -> bool:
    return v in RESOURCE_READINESS_STATES


def is_valid_mou_status(v: str) -> bool:
    return v in RESOURCE_MOU_STATUSES


def all_capability_codes() -> list[str]:
    out: list[str] = []
    for domain, keys in RESOURCE_CAPABILITY_KEYS_BY_DOMAIN.items():
        for key in keys:
            out.append(f"{domain}.{key}")
    return sorted(out)


# -----------------
# Resources taxonomy
# slice-local
# (not Governance)
# -----------------


RESOURCE_READINESS_STATES: Final[tuple[str, ...]] = (
    "draft",
    "review",
    "active",
    "suspended",
)

RESOURCE_MOU_STATUSES: Final[tuple[str, ...]] = (
    "none",
    "pending",
    "active",
    "expired",
    "terminated",
)

# Capability keys by domain.
# Governance may reference these keys by name, but the enum lives here.
RESOURCE_CAPABILITY_KEYS_BY_DOMAIN: Final[dict[str, tuple[str, ...]]] = {
    "basic_needs": (
        "food_pantry",
        "mobile_shower",
        "shelter_temp_men",
        "shelter_temp_women_children",
        "clothing",
        "barber",
    ),
    "counseling_services": (
        "employment_counseling",
        "education_counseling",
        "behavioral_psychological",
        "substance_abuse",
        "domestic_violence",
        "peer_group",
        "financial_counseling",
        "legal_criminal",
        "legal_civil",
    ),
    "employment_services": (
        "temporary_staffing_service",
        "casual_labor",
        "union_hall",
        "handyman_general",
        "yard_maintenance",
        "weed_abatement",
        "junk_trash_removal",
    ),
    "events": (
        "event_coordination",
        "promotions_print_radio",
        "promotions_social_media",
        "artwork_signage_fliers",
        "facility_rental",
        "equipment_rental",
        "food_service",
        "security_service",
        "staffing_coordination",
        "branded_swag",
    ),
    "health_wellness": (
        "urgent_care",
        "hospital",
        "dental",
        "vision",
        "audiology",
        "mobility_aids",
        "in_home_health_care",
        "service_animals",
    ),
    "housing": (
        "public_housing_coordination",
        "rent_assistance",
        "utilities_assistance",
        "household_goods",
        "internet_phone",
        "childcare_assistance",
    ),
    "meta": ("unclassified",),
    "quartermaster": (
        "dmro",
        "regional_depot",
        "regional_stand_down",
    ),
    "transportation": (
        "public_transit",
        "ride_share",
        "medical_transport",
        "auto_repair",
    ),
    "veterans_affairs": ("federal", "state", "local"),
    "partnering": ("offers_partner_discounts",),
    "emergency_response": (
        "emergency_relief_support",
        "disaster_relief_coordination",
        "community_relief_supplies",
        "emergency_shelter_coordination",
        "animal_livestock_hosting",
    ),
}

# -----------------
# POC taxonomy
# -----------------

POC_SCOPES: Final[tuple[str, ...]] = (
    "default",
    "admin",
    "intake",
    "scheduling",
    "after_hours",
    "finance",
    "logistics",
    "marketing",
    "volunteer",
)

DEFAULT_POC_SCOPE: Final[str] = "default"
POC_MAX_RANK: Final[int] = 99
