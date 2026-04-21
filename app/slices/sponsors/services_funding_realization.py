# app/slices/sponsors/services_funding_realization.py

from __future__ import annotations

from dataclasses import dataclass

from app.extensions import db, event_bus
from app.extensions.contracts import calendar_v2, finance_v2, governance_v2
from app.lib.chrono import now_iso8601_ms
from app.lib.request_ctx import ensure_request_id

from .mapper import funding_context_to_realization_defaults
from .services_funding import _get_intent_or_raise

_ALLOWED_INTENT_STATUS = {"committed"}
_ALLOWED_DEMAND_STATUS = {"published", "funding_in_progress"}

_TEMP_KEYS = {
    "temp",
    "temporary",
    "temporarily_restricted",
}
_PERM_KEYS = {
    "perm",
    "permanent",
    "permanently_restricted",
}


@dataclass(frozen=True)
class FundingRealizationResult:
    intent_ulid: str
    sponsor_entity_ulid: str
    funding_demand_ulid: str
    project_ulid: str | None

    amount_cents: int
    fund_code: str

    journal_ulid: str
    reserve_ulid: str | None

    status: str
    decision_fingerprint: str
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class FinanceFulfillmentPackage:
    intent_ulid: str
    sponsor_entity_ulid: str
    funding_demand_ulid: str
    project_ulid: str | None

    amount_cents: int
    fund_code: str
    fund_label: str
    fund_restriction_type: str

    income_kind: str
    receipt_method: str
    reserve_on_receive: bool

    source_profile_key: str
    ops_support_planned: bool
    restriction_keys: tuple[str, ...]
    decision_fingerprint: str

    memo: str
    happened_at_utc: str
    actor_ulid: str | None
    request_id: str | None
    dry_run: bool = False


def _build_finance_fulfillment_package(
    *,
    intent_row,
    defaults,
    fund_meta,
    amount_cents: int,
    fund_code: str,
    income_kind: str,
    receipt_method: str,
    reserve_on_receive: bool,
    restriction_keys: tuple[str, ...],
    decision_fingerprint: str,
    memo: str,
    happened_at_utc: str,
    actor_ulid: str | None,
    request_id: str | None,
    dry_run: bool,
) -> FinanceFulfillmentPackage:
    fund_restriction_type = _derive_restriction_type(
        restriction_keys=restriction_keys,
        archetype=fund_meta.archetype,
    )
    return FinanceFulfillmentPackage(
        intent_ulid=intent_row.ulid,
        sponsor_entity_ulid=intent_row.sponsor_entity_ulid,
        funding_demand_ulid=defaults.funding_demand_ulid,
        project_ulid=defaults.project_ulid,
        amount_cents=amount_cents,
        fund_code=fund_code,
        fund_label=fund_meta.label,
        fund_restriction_type=fund_restriction_type,
        income_kind=income_kind,
        receipt_method=receipt_method,
        reserve_on_receive=reserve_on_receive,
        source_profile_key=defaults.source_profile_key,
        ops_support_planned=defaults.ops_support_planned,
        restriction_keys=tuple(restriction_keys or ()),
        decision_fingerprint=decision_fingerprint,
        memo=memo,
        happened_at_utc=happened_at_utc,
        actor_ulid=actor_ulid,
        request_id=request_id,
        dry_run=dry_run,
    )


def _post_finance_fulfillment(
    package: FinanceFulfillmentPackage,
) -> tuple[finance_v2.PostedDTO, finance_v2.PostedDTO | None]:
    income_post = finance_v2.post_income(
        finance_v2.IncomePostRequestDTO(
            amount_cents=package.amount_cents,
            happened_at_utc=package.happened_at_utc,
            fund_code=package.fund_code,
            fund_label=package.fund_label,
            fund_restriction_type=package.fund_restriction_type,
            income_kind=package.income_kind,
            receipt_method=package.receipt_method,
            source="sponsors",
            source_ref_ulid=package.intent_ulid,
            funding_demand_ulid=package.funding_demand_ulid,
            project_ulid=package.project_ulid,
            payer_entity_ulid=package.sponsor_entity_ulid,
            memo=package.memo,
            created_by_actor=package.actor_ulid,
            request_id=package.request_id,
            dry_run=package.dry_run,
        )
    )

    reserve_post = None
    if package.reserve_on_receive:
        reserve_post = finance_v2.reserve_funds(
            finance_v2.ReserveRequestDTO(
                funding_demand_ulid=package.funding_demand_ulid,
                fund_code=package.fund_code,
                amount_cents=package.amount_cents,
                source="sponsors",
                fund_label=package.fund_label,
                fund_restriction_type=package.fund_restriction_type,
                project_ulid=package.project_ulid,
                source_ref_ulid=package.intent_ulid,
                memo=package.memo,
                actor_ulid=package.actor_ulid,
                request_id=package.request_id,
                dry_run=package.dry_run,
            )
        )

    return income_post, reserve_post


def _derive_restriction_type(
    *,
    restriction_keys: tuple[str, ...],
    archetype: str,
) -> str:
    archetype_norm = (archetype or "").strip().lower()
    keys = {str(k).strip().lower() for k in restriction_keys}

    if keys.intersection(_PERM_KEYS) or archetype_norm in _PERM_KEYS:
        return "permanently_restricted"
    if keys.intersection(_TEMP_KEYS) or archetype_norm in _TEMP_KEYS:
        return "temporarily_restricted"
    return "unrestricted"


def _require_realizable_intent(intent_row) -> None:
    if intent_row.status not in _ALLOWED_INTENT_STATUS:
        raise ValueError(
            "funding intent must be committed before realization"
        )


def _require_realizable_context(
    context: calendar_v2.PublishedFundingDemandPackageDTO,
) -> None:
    if context.demand.status not in _ALLOWED_DEMAND_STATUS:
        raise ValueError(
            "funding demand must be published or funding_in_progress"
        )


def _merge_restriction_keys(*groups: tuple[str, ...]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group or ():
            key = str(raw).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
    return tuple(out)


def _resolve_income_kind(
    requested_income_kind: str | None,
    *,
    defaults,
) -> str:
    value = (requested_income_kind or "").strip()
    if value:
        return value
    value = (defaults.recommended_income_kind or "").strip()
    if value:
        return value
    raise ValueError("income_kind required")


def _resolve_reserve_on_receive(
    requested: bool | None,
    *,
    defaults,
) -> bool:
    if requested is not None:
        return bool(requested)
    if defaults.reserve_on_receive_expected is None:
        return False
    return bool(defaults.reserve_on_receive_expected)


def realize_funding_intent(
    *,
    intent_ulid: str,
    amount_cents: int,
    happened_at_utc: str,
    fund_code: str,
    income_kind: str | None,
    receipt_method: str,
    reserve_on_receive: bool | None = None,
    memo: str | None = None,
    actor_ulid: str | None,
    actor_rbac_roles: tuple[str, ...] = (),
    actor_domain_roles: tuple[str, ...] = (),
    request_id: str | None,
    dry_run: bool = False,
) -> FundingRealizationResult:
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")
    if not happened_at_utc:
        raise ValueError("happened_at_utc required")
    if not fund_code:
        raise ValueError("fund_code required")
    if not receipt_method:
        raise ValueError("receipt_method required")

    intent_row = _get_intent_or_raise(intent_ulid)
    _require_realizable_intent(intent_row)

    intent_amount = int(intent_row.amount_cents or 0)
    if amount_cents != intent_amount:
        raise ValueError(
            "partial realization is not supported in this baseline"
        )

    demand_pkg = calendar_v2.get_published_funding_demand_package(
        intent_row.funding_demand_ulid
    )
    _require_realizable_context(demand_pkg)

    defaults = funding_context_to_realization_defaults(
        demand_pkg,
        intent_ulid=intent_row.ulid,
        amount_cents=amount_cents,
    )
    income_kind = _resolve_income_kind(income_kind, defaults=defaults)
    reserve_on_receive = _resolve_reserve_on_receive(
        reserve_on_receive,
        defaults=defaults,
    )

    fund_meta = governance_v2.get_fund_code(fund_code)
    restriction_keys = governance_v2.apply_fund_defaults(
        fund_code=fund_code,
        restriction_keys=defaults.default_restriction_keys,
    )
    restriction_keys = _merge_restriction_keys(
        defaults.default_restriction_keys,
        restriction_keys,
    )

    sem = governance_v2.validate_semantic_keys(
        fund_code=fund_code,
        restriction_keys=restriction_keys,
        income_kind=income_kind,
        demand_eligible_fund_codes=defaults.eligible_fund_codes,
    )
    if not sem.ok:
        raise ValueError("; ".join(sem.errors) or "invalid semantics")

    gov_preview = governance_v2.preview_funding_policy(
        governance_v2.FundingDecisionRequestDTO(
            op="receive",
            amount_cents=amount_cents,
            funding_demand_ulid=defaults.funding_demand_ulid,
            project_ulid=defaults.project_ulid,
            income_kind=income_kind,
            source_profile_key=defaults.source_profile_key,
            spending_class=defaults.spending_class,
            tag_any=defaults.tag_any,
            restriction_keys=restriction_keys,
            ops_support_planned=defaults.ops_support_planned,
            demand_eligible_fund_codes=defaults.eligible_fund_codes,
            selected_fund_code=fund_code,
            actor_rbac_roles=actor_rbac_roles,
            actor_domain_roles=actor_domain_roles,
        )
    )

    if not gov_preview.allowed:
        raise PermissionError(
            "; ".join(gov_preview.reason_codes) or "funding receive denied"
        )
    if gov_preview.required_approvals:
        raise PermissionError(
            "receive requires approvals: "
            + ", ".join(gov_preview.required_approvals)
        )

    memo_txt = memo or intent_row.note or f"realized:{income_kind}"

    request_id = str(request_id or ensure_request_id())

    package = _build_finance_fulfillment_package(
        intent_row=intent_row,
        defaults=defaults,
        fund_meta=fund_meta,
        amount_cents=amount_cents,
        fund_code=fund_code,
        income_kind=income_kind,
        receipt_method=receipt_method,
        reserve_on_receive=reserve_on_receive,
        restriction_keys=restriction_keys,
        decision_fingerprint=gov_preview.decision_fingerprint,
        memo=memo_txt,
        happened_at_utc=happened_at_utc,
        actor_ulid=actor_ulid,
        request_id=request_id,
        dry_run=dry_run,
    )

    income_post, reserve_post = _post_finance_fulfillment(package)

    flags: list[str] = list(income_post.flags or ())
    if reserve_post is not None:
        flags.extend(reserve_post.flags or ())

    if dry_run:
        return FundingRealizationResult(
            intent_ulid=intent_row.ulid,
            sponsor_entity_ulid=intent_row.sponsor_entity_ulid,
            funding_demand_ulid=defaults.funding_demand_ulid,
            project_ulid=defaults.project_ulid,
            amount_cents=amount_cents,
            fund_code=fund_code,
            journal_ulid=income_post.id,
            reserve_ulid=None if reserve_post is None else reserve_post.id,
            status=intent_row.status,
            decision_fingerprint=gov_preview.decision_fingerprint,
            flags=tuple(flags),
        )

    intent_row.status = "fulfilled"
    db.session.flush()

    event_bus.emit(
        domain="sponsors",
        operation="sponsor_funding_realized",
        actor_ulid=actor_ulid,
        target_ulid=intent_row.ulid,
        happened_at_utc=now_iso8601_ms(),
        request_id=request_id,
        refs={
            "sponsor_entity_ulid": intent_row.sponsor_entity_ulid,
            "funding_demand_ulid": defaults.funding_demand_ulid,
            "project_ulid": defaults.project_ulid,
            "journal_ulid": income_post.id,
            "reserve_ulid": (
                None if reserve_post is None else reserve_post.id
            ),
            "fund_code": fund_code,
            "decision_fingerprint": gov_preview.decision_fingerprint,
        },
        changed={"fields": ["status"]},
        meta={
            "amount_cents": amount_cents,
            "income_kind": income_kind,
            "receipt_method": receipt_method,
            "reserve_on_receive": reserve_on_receive,
            "source_profile_key": defaults.source_profile_key,
            "ops_support_planned": defaults.ops_support_planned,
            "restriction_keys": list(package.restriction_keys),
        },
    )

    return FundingRealizationResult(
        intent_ulid=intent_row.ulid,
        sponsor_entity_ulid=intent_row.sponsor_entity_ulid,
        funding_demand_ulid=defaults.funding_demand_ulid,
        project_ulid=defaults.project_ulid,
        amount_cents=amount_cents,
        fund_code=fund_code,
        journal_ulid=income_post.id,
        reserve_ulid=None if reserve_post is None else reserve_post.id,
        status=intent_row.status,
        decision_fingerprint=gov_preview.decision_fingerprint,
        flags=tuple(flags),
    )
