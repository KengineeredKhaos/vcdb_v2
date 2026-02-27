# app/slices/sponsors/taxonomy.py

from __future__ import annotations

from typing import Final

__all__ = [
    "is_valid_readiness_status",
    "is_valid_mou_status",
    "all_capability_codes",
    "SPONSOR_CAPABILITY_NOTE_MAX",
    "SPONSOR_READINESS_STATUSES",
    "SPONSOR_READINESS_CODES",
    "SPONSOR_READINESS_DEFAULT",
    "SPONSOR_MOU_STATUSES",
    "SPONSOR_MOU_CODES",
    "SPONSOR_READINESS_DEFAULT",
    "SPONSOR_PLEDGE_STATUSES",
    "SPONSOR_PLEDGE_STATUS_CODES",
    "SPONSOR_TRANSITIONS",
    "SPONSOR_PLEDGE_TYPES",
    "SPONSOR_PLEDGE_TYPE_CODES",
    "SPONSOR_CAPABILITY_META",
    "SPONSOR_CAPABILITY_DOMAINS",
    # POC constraints
    "POC_SCOPES",
    "DEFAULT_POC_SCOPE",
    "POC_MAX_RANK",
]


# -----------------
# Notes Length Knob
# -----------------

# how long a capability note can be (operator hint)
SPONSOR_CAPABILITY_NOTE_MAX: int = 240  # pick your number


# -----------------
# Helper/Prep
# Functions
# -----------------


def all_capability_codes() -> list[str]:
    out: list[str] = []
    for dom in SPONSOR_CAPABILITY_DOMAINS:
        dcode = str(dom.get("code") or "").strip()
        for k in dom.get("keys") or []:
            kcode = str(k.get("code") or "").strip()
            if dcode and kcode:
                out.append(f"{dcode}.{kcode}")
    return sorted(out)


def is_valid_readiness_status(v: str) -> bool:
    vv = (v or "").strip().lower()
    return vv in SPONSOR_READINESS_CODES


def is_valid_mou_status(v: str) -> bool:
    vv = (v or "").strip().lower()
    return vv in SPONSOR_MOU_CODES


# Sponsors taxonomy (slice-local; not Governance).

SPONSOR_READINESS_DEFAULT: Final[str] = "draft"
SPONSOR_READINESS_STATUSES: Final[tuple[dict, ...]] = (
    {"can_issue": False, "code": "draft", "label": "Draft"},
    {"can_issue": False, "code": "review", "label": "Under review"},
    {"can_issue": True, "code": "active", "label": "Active"},
    {"can_issue": False, "code": "suspended", "label": "Suspended"},
)
SPONSOR_READINESS_CODES: Final[tuple[str, ...]] = tuple(
    str(x["code"]).strip().lower() for x in SPONSOR_READINESS_STATUSES
)

SPONSOR_MOU_DEFAULT: Final[str] = "none"
SPONSOR_MOU_STATUSES: Final[tuple[dict, ...]] = (
    {"can_issue": False, "code": "none", "label": "No MOU"},
    {"can_issue": False, "code": "pending", "label": "MOU pending"},
    {"can_issue": True, "code": "active", "label": "Active MOU"},
    {"can_issue": False, "code": "expired", "label": "Expired MOU"},
    {"can_issue": False, "code": "terminated", "label": "Terminated"},
)
SPONSOR_MOU_CODES: Final[tuple[str, ...]] = tuple(
    str(x["code"]).strip().lower() for x in SPONSOR_MOU_STATUSES
)

SPONSOR_PLEDGE_STATUSES: Final[tuple[dict, ...]] = (
    {"code": "proposed", "label": "Proposed"},
    {"code": "active", "label": "Active"},
    {"code": "fulfilled", "label": "Fulfilled"},
    {"code": "cancelled", "label": "Cancelled"},
)
SPONSOR_PLEDGE_STATUS_CODES: Final[tuple[str, ...]] = tuple(
    str(x["code"]).strip().lower() for x in SPONSOR_PLEDGE_STATUSES
)
SPONSOR_TRANSITIONS: Final[dict[str, dict[str, list[str]]]] = {
    "mou": {
        "active": ["expired", "terminated"],
        "expired": ["active", "terminated"],
        "none": ["pending"],
        "pending": ["active", "none"],
    },
    "pledge": {
        "active": ["fulfilled", "cancelled"],
        "proposed": ["active", "cancelled"],
    },
    "readiness": {
        "active": ["suspended"],
        "draft": ["review", "suspended"],
        "review": ["active", "suspended"],
        "suspended": ["review", "active"],
    },
}

# UI pledge type enum (slice taxonomy).
SPONSOR_PLEDGE_TYPES: Final[tuple[dict, ...]] = (
    {"code": "cash", "label": "Cash"},
    {"code": "in_kind", "label": "In-kind"},
)
SPONSOR_PLEDGE_TYPE_CODES: Final[tuple[str, ...]] = tuple(
    str(x["code"]).strip().lower() for x in SPONSOR_PLEDGE_TYPES
)
# Sponsor capabilities taxonomy (slice-local).
SPONSOR_CAPABILITY_META: Final[dict[str, str]] = {
    "flat_key_prefix": "sponsor.capability",
    "unclassified_key": "meta.unclassified",
}
SPONSOR_CAPABILITY_DOMAINS: Final[tuple[dict, ...]] = (
    {
        "code": "funding",
        "keys": [
            {
                "code": "cash",
                "description": "Private Party Cash or Check",
                "label": "Dead Presidents",
            },
            {
                "code": "cash_grant",
                "description": "Unrestricted or lightly restricted cash awards",
                "label": "Cash grant",
            },
            {
                "code": "restricted_grant",
                "description": "Tied to a specific program or use",
                "label": "Restricted grant",
            },
        ],
        "label": "Monetary funding",
    },
    {
        "code": "in_kind",
        "keys": [
            {
                "code": "in_kind_goods",
                "description": "text placeholder",
                "label": "Goods",
            },
            {
                "code": "in_kind_services",
                "description": "text placeholder",
                "label": "Services",
            },
        ],
        "label": "In-kind support",
    },
    {
        "code": "meta",
        "keys": [
            {
                "code": "unclassified",
                "description": "text placeholder",
                "label": "Unclassified — requires admin review",
            }
        ],
        "label": "Meta / flags",
    },
)


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
