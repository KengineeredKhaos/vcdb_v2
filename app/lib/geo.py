# app/lib/geo.py
from __future__ import annotations

from functools import cache

# Strict state two letter codes plus DC & PR
# in json format
# ---- Private, canonical data (immutable tuples) ---------------------------
# Keep these module-private; only expose getters so callers can’t mutate.

_US_STATES: tuple[tuple[str, str], ...] = (
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
    ("DC", "District of Columbia"),
    ("AS", "American Samoa"),
    ("GU", "Guam"),
    ("MP", "Northern Mariana Islands"),
    ("PR", "Puerto Rico"),
    ("UM", "United States Minor Outlying Islands"),
    ("VI", "Virgin Islands, U.S."),
)


_COUNTRIES: tuple[tuple[str, str], ...] = (
    ("US", "United States"),
    ("CA", "Canada"),
    ("MX", "Mexico"),
    # add what you need now; you can always expand later
)


# ---- Public getters (immutable views) -------------------------------------
@cache
def us_states() -> tuple[tuple[str, str], ...]:
    """Choice-friendly (code, name) pairs for US states (immutable)."""
    return _US_STATES


@cache
def state_map() -> dict[str, str]:
    """Fast validation/lookup → code -> name (immutable copy)."""
    return dict(_US_STATES)


@cache
def countries() -> tuple[tuple[str, str], ...]:
    """Choice-friendly (code, name) pairs for countries (immutable)."""
    return _COUNTRIES


@cache
def country_map() -> dict[str, str]:
    """Fast validation/lookup → code -> name (immutable copy)."""
    return dict(_COUNTRIES)


# ---- Normalizers / validators --------------------------------------------
def normalize_state(code_or_name: str) -> str | None:
    """Return the 2-letter state code for a code OR display name; else None."""
    if not code_or_name:
        return None
    s = code_or_name.strip().upper()
    # If already a code
    if s in state_map():
        return s
    # Try by name (case-insensitive)
    name_to_code = {name.upper(): code for code, name in us_states()}
    return name_to_code.get(s)


def is_state_code(code: str) -> bool:
    return bool(code) and code.strip().upper() in state_map()


def normalize_country(code_or_name: str) -> str | None:
    if not code_or_name:
        return None
    s = code_or_name.strip().upper()
    if s in country_map():
        return s
    name_to_code = {name.upper(): code for code, name in countries()}
    return name_to_code.get(s)
