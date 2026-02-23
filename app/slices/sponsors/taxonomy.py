from __future__ import annotations

from typing import Final

# Sponsors taxonomy (slice-local; not Governance).

SPONSOR_READINESS_DEFAULT: Final[str] = "draft"
SPONSOR_READINESS_STATUSES: Final[tuple[dict, ...]] = (
    {'can_issue': False, 'code': 'draft', 'label': 'Draft'},
    {'can_issue': False, 'code': 'review', 'label': 'Under review'},
    {'can_issue': True, 'code': 'active', 'label': 'Active'},
    {'can_issue': False, 'code': 'suspended', 'label': 'Suspended'},
)

SPONSOR_MOU_DEFAULT: Final[str] = "none"
SPONSOR_MOU_STATUSES: Final[tuple[dict, ...]] = (
    {'can_issue': False, 'code': 'none', 'label': 'No MOU'},
    {'can_issue': False, 'code': 'pending', 'label': 'MOU pending'},
    {'can_issue': True, 'code': 'active', 'label': 'Active MOU'},
    {'can_issue': False, 'code': 'expired', 'label': 'Expired MOU'},
    {'can_issue': False, 'code': 'terminated', 'label': 'Terminated'},
)

SPONSOR_PLEDGE_STATUSES: Final[tuple[dict, ...]] = (
    {'code': 'proposed', 'label': 'Proposed'},
    {'code': 'active', 'label': 'Active'},
    {'code': 'fulfilled', 'label': 'Fulfilled'},
    {'code': 'cancelled', 'label': 'Cancelled'},
)

SPONSOR_TRANSITIONS: Final[dict[str, dict[str, list[str]]]] = {'mou': {'active': ['expired', 'terminated'],
             'expired': ['active', 'terminated'],
             'none': ['pending'],
             'pending': ['active', 'none']},
     'pledge': {'active': ['fulfilled', 'cancelled'],
                'proposed': ['active', 'cancelled']},
     'readiness': {'active': ['suspended'],
                   'draft': ['review', 'suspended'],
                   'review': ['active', 'suspended'],
                   'suspended': ['review', 'active']}}

# UI pledge type enum (slice taxonomy).
SPONSOR_PLEDGE_TYPES: Final[tuple[dict, ...]] = (
    {'code': 'cash', 'label': 'Cash'},
    {'code': 'in_kind', 'label': 'In-kind'},
)

# Sponsor capabilities taxonomy (slice-local).
SPONSOR_CAPABILITY_META: Final[dict[str, str]] = {'flat_key_prefix': 'sponsor.capability',
     'unclassified_key': 'meta.unclassified'}
SPONSOR_CAPABILITY_DOMAINS: Final[tuple[dict, ...]] = (
    {'code': 'funding',
     'keys': [{'code': 'cash',
               'description': 'Private Party Cash or Check',
               'label': 'Dead Presidents'},
              {'code': 'cash_grant',
               'description': 'Unrestricted or lightly restricted cash awards',
               'label': 'Cash grant'},
              {'code': 'restricted_grant',
               'description': 'Tied to a specific program or use',
               'label': 'Restricted grant'}],
     'label': 'Monetary funding'},
    {'code': 'in_kind',
     'keys': [{'code': 'in_kind_goods',
               'description': 'text placeholder',
               'label': 'Goods'},
              {'code': 'in_kind_services',
               'description': 'text placeholder',
               'label': 'Services'}],
     'label': 'In-kind support'},
    {'code': 'meta',
     'keys': [{'code': 'unclassified',
               'description': 'text placeholder',
               'label': 'Unclassified — requires admin review'}],
     'label': 'Meta / flags'},
)
