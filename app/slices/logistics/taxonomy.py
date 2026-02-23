from __future__ import annotations

from typing import Final

# Logistics taxonomy (slice-local; not Governance).
# Keep SKU parsing/validation constants here to avoid JSON churn.

SKU_CODE_REGEX: Final[str] = r"^[A-Z]{2}-[A-Z]{2}-[A-Z]{2}-[A-Z*]-[A-Z*]-[A-Z]-\d{3}$"

# SKU part vocabulary used by parse_sku()/validate_sku().
# Pattern: CC-SS-RR-X-Y-Z-NNN
#   CC = category (2)
#   SS = subcategory (2)
#   RR = source (2)
#   X  = size (1) or '*'
#   Y  = color (1) or '*'
#   Z  = issuance_class (1)
#   NNN= sequence (3 digits)
SKU_PART_KEYS: Final[tuple[str, ...]] = (
    "category",
    "subcategory",
    "source",
    "size",
    "color",
    "issuance_class",
    "seq",
)

ALLOWED_SOURCES: Final[tuple[str, ...]] = (
    "DR",
    "LC",
)

ALLOWED_UNITS: Final[tuple[str, ...]] = (
    "each",
    "lbs",
    "kit",
    "box",
    "pack",
)

# Locations: the list of concrete locations is slice data
# (see data/locations.json).
LOCATION_KINDS: Final[tuple[str, ...]] = (
    "warehouse",
    "rackbin",
    "satellite",
    "vehicle",
)

RACKBIN_PATTERN: Final[str] = r"^MAIN-[A-F][1-3]-[1-3]$"

# Inventory item lifecycle (workflow taxonomy).
ITEM_LIFECYCLE_STATES: Final[tuple[str, ...]] = (
    "received",
    "inspected",
    "available",
    "issued",
    "returned",
)

ITEM_LIFECYCLE_TRANSITIONS: Final[dict[str, tuple[str, ...]]] = {'available': ('issued',),
 'inspected': ('available',),
 'issued': ('returned',),
 'received': ('inspected',),
 'returned': ('inspected',)}
