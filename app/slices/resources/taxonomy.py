from __future__ import annotations

from typing import Final

# Resources taxonomy (slice-local; not Governance).

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
RESOURCE_CAPABILITY_KEYS_BY_DOMAIN: Final[dict[str, tuple[str, ...]]] = {'basic_needs': ('food_pantry',
                 'mobile_shower',
                 'shelter_temp_men',
                 'shelter_temp_women_children',
                 'clothing',
                 'barber'),
 'counseling_services': ('employment_counseling',
                         'education_counseling',
                         'behavioral_psychological',
                         'substance_abuse',
                         'domestic_violence',
                         'peer_group',
                         'financial_counseling',
                         'legal_criminal',
                         'legal_civil'),
 'events': ('event_coordination',
            'promotions_print_radio',
            'promotions_social_media',
            'artwork_signage_fliers',
            'facility_rental',
            'equipment_rental',
            'food_service',
            'security_service',
            'staffing_coordination',
            'branded_swag'),
 'health_wellness': ('urgent_care',
                     'hospital',
                     'dental',
                     'vision',
                     'audiology',
                     'mobility_aids',
                     'in_home_health_care',
                     'service_animals'),
 'housing': ('public_housing_coordination',
             'rent_assistance',
             'utilities_assistance',
             'household_goods',
             'internet_phone',
             'childcare_assistance',
             'handyman_general',
             'yard_maintenance',
             'weed_abatement',
             'junk_trash_removal'),
 'meta': ('unclassified',),
 'quartermaster': ('dmro',
                   'regional_depot',
                   'regional_stand_down',
                   'local_civil_donations',
                   'local_commercial_discounts'),
 'transportation': ('public_transit',
                    'ride_share',
                    'medical_transport',
                    'auto_repair'),
 'veterans_affairs': ('federal', 'state', 'local')}
