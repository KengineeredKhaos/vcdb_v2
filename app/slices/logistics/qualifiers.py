# app/slices/logistics/qualifiers.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from app.extensions.contracts.customers_v2 import CustomerCuesDTO

# ---------------------------------------------------------------------------
# Qualifiers: pure, side-effect free gates.
#
# This module MUST remain:
#   - no DB reads
#   - no policy loads
#   - no contract calls
#
# Input:
#   qualifiers: merged toggles (from policy) for a given SKU/customer context
#   customer_cues: PII-free decision-ready cues from Customers contract
#
# Output:
#   QualifierOutcome(ok, reason, checks)
# ---------------------------------------------------------------------------


# Stable, grep-able reason strings (also used as “failed gate” ids)
REASON_VETERAN_REQUIRED: Final[str] = "veteran_required"
REASON_HOMELESS_REQUIRED: Final[str] = "homeless_required"
REASON_WATCHLIST_BLOCK: Final[str] = "watchlist_block"
REASON_TIER1_IMMEDIATE_REQUIRED: Final[str] = "tier1_immediate_required"

REASON_TIER1_MIN_AT_LEAST: Final[str] = "tier1_min_at_least"
REASON_TIER2_MIN_AT_LEAST: Final[str] = "tier2_min_at_least"
REASON_TIER3_MIN_AT_LEAST: Final[str] = "tier3_min_at_least"

REASON_UNKNOWN_QUALIFIER_PREFIX: Final[str] = "unknown_qualifier:"
REASON_BAD_QUALIFIER_VALUE_PREFIX: Final[str] = "bad_qualifier_value:"


BOOL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "veteran_required",
        "homeless_required",
        "watchlist_block",
        "tier1_immediate_required",
    }
)

INT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "tier1_min_at_least",
        "tier2_min_at_least",
        "tier3_min_at_least",
    }
)

SUPPORTED_QUALIFIER_KEYS: Final[frozenset[str]] = frozenset(
    set(BOOL_KEYS) | set(INT_KEYS)
)


@dataclass(frozen=True)
class QualifierOutcome:
    ok: bool
    reason: str | None = None
    # Immutable “debug trace” of evaluated checks (name -> pass/fail)
    checks: tuple[tuple[str, bool], ...] = ()


def evaluate(
    *,
    qualifiers: dict[str, Any] | None,
    customer_cues: CustomerCuesDTO | None,
) -> QualifierOutcome:
    """Evaluate merged qualifier toggles against customer cues.

    Pure qualifier gate.

    Fail-closed posture:
      - If a qualifier key is unknown AND its value is truthy, deny.
      - If a known qualifier has a wrong type (non-null), deny.
      - If a qualifier requires cues but cues are missing, deny that qualifier.
    """

    q = qualifiers or {}
    if not q:
        return QualifierOutcome(ok=True)

    checks: list[tuple[str, bool]] = []

    def _check(name: str, passed: bool) -> bool:
        checks.append((name, bool(passed)))
        return bool(passed)

    # 1) Unknown truthy qualifier keys => deny (fail closed)
    for k, v in q.items():
        if k in SUPPORTED_QUALIFIER_KEYS:
            continue
        if v:  # truthy means it intends to have effect
            return QualifierOutcome(
                ok=False,
                reason=f"{REASON_UNKNOWN_QUALIFIER_PREFIX}{k}",
                checks=tuple(checks),
            )

    # 2) Bad types for known keys => deny (fail closed)
    #    Prevents silent "constraint ignored" behavior.
    for k, v in q.items():
        if v is None:
            continue

        if k in BOOL_KEYS and not isinstance(v, bool):
            return QualifierOutcome(
                ok=False,
                reason=f"{REASON_BAD_QUALIFIER_VALUE_PREFIX}{k}",
                checks=tuple(checks),
            )

        if k in INT_KEYS:
            # bool is a subclass of int in Python; exclude it explicitly.
            if not isinstance(v, int) or isinstance(v, bool):
                return QualifierOutcome(
                    ok=False,
                    reason=f"{REASON_BAD_QUALIFIER_VALUE_PREFIX}{k}",
                    checks=tuple(checks),
                )

    cues = customer_cues

    # --- Boolean gates ---
    if q.get("veteran_required") is True:
        if not _check(
            "is_veteran_verified", bool(cues and cues.is_veteran_verified)
        ):
            return QualifierOutcome(
                False, REASON_VETERAN_REQUIRED, tuple(checks)
            )

    if q.get("homeless_required") is True:
        if not _check(
            "is_homeless_verified", bool(cues and cues.is_homeless_verified)
        ):
            return QualifierOutcome(
                False, REASON_HOMELESS_REQUIRED, tuple(checks)
            )

    if q.get("watchlist_block") is True:
        # Block if watchlist is true; missing cues => treat as not watchlisted (non-blocking)
        if not _check("not_watchlisted", not bool(cues and cues.watchlist)):
            return QualifierOutcome(
                False, REASON_WATCHLIST_BLOCK, tuple(checks)
            )

    if q.get("tier1_immediate_required") is True:
        if not _check(
            "flag_tier1_immediate", bool(cues and cues.flag_tier1_immediate)
        ):
            return QualifierOutcome(
                False, REASON_TIER1_IMMEDIATE_REQUIRED, tuple(checks)
            )

    # --- Numeric minimum gates (ints) ---
    def _int_or_none(v: Any) -> int | None:
        # bool is an int; do not accept it as a numeric constraint.
        if isinstance(v, bool):
            return None
        return v if isinstance(v, int) else None

    t1_req = _int_or_none(q.get("tier1_min_at_least"))
    if t1_req is not None:
        t1_have = cues.tier1_min if cues else None
        if not _check(
            "tier1_min_at_least", (t1_have is not None and t1_have >= t1_req)
        ):
            return QualifierOutcome(
                False, REASON_TIER1_MIN_AT_LEAST, tuple(checks)
            )

    t2_req = _int_or_none(q.get("tier2_min_at_least"))
    if t2_req is not None:
        t2_have = cues.tier2_min if cues else None
        if not _check(
            "tier2_min_at_least", (t2_have is not None and t2_have >= t2_req)
        ):
            return QualifierOutcome(
                False, REASON_TIER2_MIN_AT_LEAST, tuple(checks)
            )

    t3_req = _int_or_none(q.get("tier3_min_at_least"))
    if t3_req is not None:
        t3_have = cues.tier3_min if cues else None
        if not _check(
            "tier3_min_at_least", (t3_have is not None and t3_have >= t3_req)
        ):
            return QualifierOutcome(
                False, REASON_TIER3_MIN_AT_LEAST, tuple(checks)
            )

    return QualifierOutcome(ok=True, checks=tuple(checks))
