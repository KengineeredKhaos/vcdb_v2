# app/slices/resources/services_matching.py

from __future__ import annotations

from dataclasses import dataclass

from app.extensions.contracts import customers_v2
from app.lib.chrono import now_iso8601_ms

from . import services as resource_svc
from .mapper import ResourceView
from .matching_matrix import flat_codes_to_pairs, get_need_row


@dataclass(frozen=True)
class ResourceNeedMatchItemView:
    entity_ulid: str
    readiness_status: str
    mou_status: str
    matched_capability_keys: tuple[str, ...]
    bucket: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ResourceNeedMatchResultView:
    customer_ulid: str
    need_key: str
    tier: int
    tier_priority: int | None
    customer_gate: str
    blocked_reason: str | None
    operator_cautions: tuple[str, ...]
    exact_matches: tuple[ResourceNeedMatchItemView, ...]
    adjacent_matches: tuple[ResourceNeedMatchItemView, ...]
    review_matches: tuple[ResourceNeedMatchItemView, ...]
    as_of_iso: str


def _tier_unlocked(cues: customers_v2.CustomerCuesDTO, tier: int) -> bool:
    if tier == 1:
        return bool(cues.tier1_unlocked)
    if tier == 2:
        return bool(cues.tier2_unlocked)
    if tier == 3:
        return bool(cues.tier3_unlocked)
    raise ValueError(f"invalid tier: {tier!r}")


def _tier_priority(
    cues: customers_v2.CustomerCuesDTO, tier: int
) -> int | None:
    if tier == 1:
        return cues.tier1_min
    if tier == 2:
        return cues.tier2_min
    if tier == 3:
        return cues.tier3_min
    raise ValueError(f"invalid tier: {tier!r}")


def _operator_cautions(
    cues: customers_v2.CustomerCuesDTO,
    *,
    tier: int,
) -> tuple[str, ...]:
    out: list[str] = []
    if bool(getattr(cues, "flag_tier1_immediate", False)) and tier == 1:
        out.append("tier_immediate")
    if bool(getattr(cues, "entity_package_incomplete", False)):
        out.append("entity_package_incomplete")
    if bool(getattr(cues, "watchlist", False)):
        out.append("customer_watchlist")
    return tuple(out)


def _matched_keys(
    view: ResourceView, codes: tuple[str, ...]
) -> tuple[str, ...]:
    wanted = set(codes)
    matched = sorted(
        f"{cap.domain}.{cap.key}"
        for cap in view.active_capabilities
        if f"{cap.domain}.{cap.key}" in wanted
    )
    return tuple(matched)


def _bucket_item(
    view: ResourceView,
    *,
    bucket: str,
    matched_capability_keys: tuple[str, ...],
) -> ResourceNeedMatchItemView:
    reason = {
        "exact": ("capability_exact",),
        "adjacent": ("capability_adjacent",),
        "review": ("capability_review_only",),
    }[bucket]
    return ResourceNeedMatchItemView(
        entity_ulid=view.entity_ulid,
        readiness_status=view.readiness_status,
        mou_status=view.mou_status,
        matched_capability_keys=matched_capability_keys,
        bucket=bucket,
        reason_codes=reason,
    )


def _find_bucket(
    *,
    bucket: str,
    codes: tuple[str, ...],
    seen: set[str],
) -> list[ResourceNeedMatchItemView]:
    if not codes:
        return []
    rows, _total = resource_svc.find_resources(
        any_of=flat_codes_to_pairs(codes),
        admin_review_required=False,
        readiness_in=["active"],
        page=1,
        per=200,
    )
    out: list[ResourceNeedMatchItemView] = []
    for view in rows:
        if view.entity_ulid in seen:
            continue
        matched = _matched_keys(view, codes)
        if not matched:
            continue
        out.append(
            _bucket_item(
                view,
                bucket=bucket,
                matched_capability_keys=matched,
            )
        )
        seen.add(view.entity_ulid)
    return out


def match_customer_need(
    *,
    customer_ulid: str,
    need_key: str,
    include_adjacent: bool = True,
) -> ResourceNeedMatchResultView:
    key = str(need_key or "").strip().lower()
    row = get_need_row(key)
    cues = customers_v2.get_customer_cues(customer_ulid)
    tier = int(row["tier"])
    priority = _tier_priority(cues, tier)
    cautions = _operator_cautions(cues, tier=tier)

    if not bool(cues.eligibility_complete):
        return ResourceNeedMatchResultView(
            customer_ulid=cues.entity_ulid,
            need_key=key,
            tier=tier,
            tier_priority=priority,
            customer_gate="blocked",
            blocked_reason="customer_not_eligible",
            operator_cautions=cautions,
            exact_matches=(),
            adjacent_matches=(),
            review_matches=(),
            as_of_iso=now_iso8601_ms(),
        )

    if not _tier_unlocked(cues, tier):
        return ResourceNeedMatchResultView(
            customer_ulid=cues.entity_ulid,
            need_key=key,
            tier=tier,
            tier_priority=priority,
            customer_gate="blocked",
            blocked_reason="tier_not_unlocked",
            operator_cautions=cautions,
            exact_matches=(),
            adjacent_matches=(),
            review_matches=(),
            as_of_iso=now_iso8601_ms(),
        )

    seen: set[str] = set()
    exact = _find_bucket(
        bucket="exact",
        codes=tuple(row["exact"]),
        seen=seen,
    )
    adjacent = []
    if include_adjacent:
        adjacent = _find_bucket(
            bucket="adjacent",
            codes=tuple(row["adjacent"]),
            seen=seen,
        )
    review = _find_bucket(
        bucket="review",
        codes=tuple(row["review"]),
        seen=seen,
    )

    return ResourceNeedMatchResultView(
        customer_ulid=cues.entity_ulid,
        need_key=key,
        tier=tier,
        tier_priority=priority,
        customer_gate="allowed",
        blocked_reason=None,
        operator_cautions=cautions,
        exact_matches=tuple(exact),
        adjacent_matches=tuple(adjacent),
        review_matches=tuple(review),
        as_of_iso=now_iso8601_ms(),
    )


__all__ = [
    "ResourceNeedMatchItemView",
    "ResourceNeedMatchResultView",
    "match_customer_need",
]
