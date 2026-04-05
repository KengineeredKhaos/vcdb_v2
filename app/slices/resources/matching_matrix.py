# app/slices/resources/matching_matrix.py

from __future__ import annotations

from typing import Final

MATCHING_EXCLUDED_CAPABILITIES = {
    "events.event_coordination": "not a direct customer need match",
    "events.promotions_print_radio": "not a customer service capability",
    "events.promotions_social_media": "not a direct customer need match",
    "events.artwork_signage_fliers": "not a direct customer need match",
    "events.facility_rental": "not a direct customer need match",
    "events.equipment_rental": "not a direct customer need match",
    "events.food_service": "not a direct customer need match",
    "events.security_service": "not a direct customer need match",
    "events.staffing_coordination": "not a direct customer need match",
    "events.branded_swag": "not a direct customer need match",
    "partnering.offers_partner_discounts": "advisory/relationship capability",
    "meta.unclassified": "never match automatically",
    "emergency_response.emergency_relief_support": "Diaster relief only",
    "emergency_response.disaster_relief_coordination": "Diaster relief only",
    "emergency_response.community_relief_supplies": "Diaster relief only",
    "emergency_response.emergency_shelter_coordination": "Diaster relief only",
    "emergency_response.animal_livestock_hosting": "Diaster relief only",
}

NEED_MATCH_MATRIX: Final[dict[str, dict[str, object]]] = {
    # -------------------------
    # Tier 1
    # -------------------------
    "food": {
        "tier": 1,
        "exact": ("basic_needs.food_pantry",),
        "adjacent": (),
        "review": (),
        "notes": "Direct food assistance first; broad relief support is secondary.",
    },
    "hygiene": {
        "tier": 1,
        "exact": (
            "basic_needs.mobile_shower",
            "basic_needs.barber",
        ),
        "adjacent": ("basic_needs.clothing",),
        "review": (),
        "notes": "Keep this practical and direct.",
    },
    "health": {
        "tier": 1,
        "exact": (
            "health_wellness.urgent_care",
            "health_wellness.hospital",
            "health_wellness.dental",
            "health_wellness.vision",
            "health_wellness.audiology",
            "health_wellness.mobility_aids",
            "health_wellness.in_home_health_care",
            "health_wellness.service_animals",
        ),
        "adjacent": (
            "transportation.medical_transport",
            "counseling_services.behavioral_psychological",
            "counseling_services.substance_abuse",
        ),
        "review": ("counseling_services.domestic_violence",),
        "notes": "Medical transport and behavioral support help, but are not the same as core health treatment.",
    },
    "housing": {
        "tier": 1,
        "exact": (
            "basic_needs.shelter_temp_men",
            "basic_needs.shelter_temp_women_children",
            "housing.public_housing_coordination",
            "housing.rent_assistance",
            "housing.utilities_assistance",
            "housing.household_goods",
        ),
        "adjacent": (
            "housing.internet_phone",
            "housing.childcare_assistance",
            "employment_services.handyman_general",
            "employment_services.yard_maintenance",
            "employment_services.weed_abatement",
            "employment_services.junk_trash_removal",
        ),
        "review": (),
        "notes": "Exact = placement/stability. Adjacent = support for maintaining or restoring housing.",
    },
    "clothing": {
        "tier": 1,
        "exact": ("basic_needs.clothing",),
        "adjacent": (),
        "review": (
            "quartermaster.dmro",
            "quartermaster.regional_depot",
            "quartermaster.regional_stand_down",
        ),
        "notes": "Quartermaster may help in some real-world cases, but do not auto-match it yet.",
    },
    # -------------------------
    # Tier 2
    # -------------------------
    "income": {
        "tier": 2,
        "exact": ("counseling_services.financial_counseling",),
        "adjacent": (
            "veterans_affairs.federal",
            "veterans_affairs.state",
            "veterans_affairs.local",
        ),
        "review": (
            "counseling_services.legal_civil",
            "counseling_services.legal_criminal",
        ),
        "notes": "Income is broad; benefits and employment support are adjacent, not the same thing.",
    },
    "employment": {
        "tier": 2,
        "exact": (
            "counseling_services.employment_counseling",
            "employment_services.temporary_staffing_service",
            "employment_services.casual_labor",
            "employment_services.union_hall",
            "employment_services.handyman_general",
            "employment_services.yard_maintenance",
            "employment_services.weed_abatement",
            "employment_services.junk_trash_removal",
        ),
        "adjacent": (
            "counseling_services.education_counseling",
            "transportation.public_transit",
            "transportation.ride_share",
            "transportation.auto_repair",
            "counseling_services.financial_counseling",
        ),
        "review": (
            "veterans_affairs.federal",
            "veterans_affairs.state",
            "veterans_affairs.local",
        ),
        "notes": "Keep direct job support separate from support that only reduces employment barriers.",
    },
    "transportation": {
        "tier": 2,
        "exact": (
            "transportation.public_transit",
            "transportation.ride_share",
            "transportation.medical_transport",
            "transportation.auto_repair",
        ),
        "adjacent": (),
        "review": (),
        "notes": "One of the cleanest mappings in the whole matrix.",
    },
    "education": {
        "tier": 2,
        "exact": ("counseling_services.education_counseling",),
        "adjacent": (
            "veterans_affairs.federal",
            "veterans_affairs.state",
            "veterans_affairs.local",
            "transportation.public_transit",
            "transportation.ride_share",
        ),
        "review": (),
        "notes": "VA-related educational benefits are adjacent support, not core education counseling itself.",
    },
    # -------------------------
    # Tier 3
    # -------------------------
    "family": {
        "tier": 3,
        "exact": (),
        "adjacent": (
            "housing.childcare_assistance",
            "counseling_services.domestic_violence",
            "counseling_services.legal_civil",
            "counseling_services.peer_group",
        ),
        "review": (),
        "notes": "No honest exact mapping yet. Keep this explicitly adjacent-only for now.",
    },
    "peergroup": {
        "tier": 3,
        "exact": ("counseling_services.peer_group",),
        "adjacent": (
            "counseling_services.behavioral_psychological",
            "counseling_services.substance_abuse",
        ),
        "review": (),
        "notes": "Direct peer support is exact; other counseling support remains adjacent.",
    },
    "tech": {
        "tier": 3,
        "exact": (),
        "adjacent": ("housing.internet_phone",),
        "review": (
            "veterans_affairs.federal",
            "veterans_affairs.state",
            "veterans_affairs.local",
        ),
        "notes": "Tech is still weakly represented in current Resources taxonomy. Keep it honest.",
    },
}


def collect_capability_code_refs() -> dict[str, set[str]]:
    """
    Return capability codes referenced by the matching matrix, grouped by
    bucket, so drift tests can prove taxonomy coverage explicitly.
    """
    refs = {
        "exact": set(),
        "adjacent": set(),
        "review": set(),
        "excluded": set(MATCHING_EXCLUDED_CAPABILITIES.keys()),
    }
    for row in NEED_MATCH_MATRIX.values():
        refs["exact"].update(str(v) for v in row.get("exact", ()))
        refs["adjacent"].update(str(v) for v in row.get("adjacent", ()))
        refs["review"].update(str(v) for v in row.get("review", ()))
    return refs


def get_need_row(need_key: str) -> dict[str, object]:
    key = str(need_key or "").strip().lower()
    if not key or key not in NEED_MATCH_MATRIX:
        raise ValueError(f"unknown need_key: {need_key!r}")
    row = NEED_MATCH_MATRIX[key]
    return {
        "tier": int(row.get("tier", 0) or 0),
        "exact": tuple(str(v) for v in row.get("exact", ())),
        "adjacent": tuple(str(v) for v in row.get("adjacent", ())),
        "review": tuple(str(v) for v in row.get("review", ())),
        "notes": str(row.get("notes", "") or ""),
    }


def flat_codes_to_pairs(codes: tuple[str, ...] | list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for code in codes:
        flat = str(code or "").strip()
        if not flat:
            continue
        if "." not in flat:
            raise ValueError(f"invalid capability code: {flat!r}")
        domain, key = flat.split(".", 1)
        domain = domain.strip()
        key = key.strip()
        if not domain or not key:
            raise ValueError(f"invalid capability code: {flat!r}")
        out.append((domain, key))
    return out
