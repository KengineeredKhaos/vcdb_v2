# app/slices/sponsors/services_funding_realization.py

from __future__ import annotations

from dataclasses import dataclass

from app.extensions import db, event_bus
from app.extensions.contracts import calendar_v2, finance_v2, governance_v2
from app.lib.chrono import now_iso8601_ms

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
    context: calendar_v2.FundingDemandContextDTO,
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

    context = calendar_v2.get_funding_demand_context(
        intent_row.funding_demand_ulid
    )
    _require_realizable_context(context)

    defaults = funding_context_to_realization_defaults(
        context,
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

    preview = governance_v2.preview_funding_decision(
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

    if not preview.allowed:
        raise PermissionError(
            "; ".join(preview.reason_codes) or "funding receive denied"
        )
    if preview.required_approvals:
        raise PermissionError(
            "receive requires approvals: "
            + ", ".join(preview.required_approvals)
        )

    fund_restriction_type = _derive_restriction_type(
        restriction_keys=restriction_keys,
        archetype=fund_meta.archetype,
    )
    memo_txt = memo or intent_row.note or f"realized:{income_kind}"

    income_post = finance_v2.post_income(
        finance_v2.IncomePostRequestDTO(
            amount_cents=amount_cents,
            happened_at_utc=happened_at_utc,
            fund_code=fund_code,
            fund_label=fund_meta.label,
            fund_restriction_type=fund_restriction_type,
            income_kind=income_kind,
            receipt_method=receipt_method,
            source="sponsors",
            source_ref_ulid=intent_row.ulid,
            funding_demand_ulid=defaults.funding_demand_ulid,
            project_ulid=defaults.project_ulid,
            payer_entity_ulid=intent_row.sponsor_entity_ulid,
            memo=memo_txt,
            created_by_actor=actor_ulid,
            request_id=request_id,
            dry_run=dry_run,
        )
    )

    reserve_post = None
    if reserve_on_receive:
        reserve_post = finance_v2.reserve_funds(
            finance_v2.ReserveRequestDTO(
                funding_demand_ulid=defaults.funding_demand_ulid,
                fund_code=fund_code,
                amount_cents=amount_cents,
                source="sponsors",
                fund_label=fund_meta.label,
                fund_restriction_type=fund_restriction_type,
                project_ulid=defaults.project_ulid,
                source_ref_ulid=intent_row.ulid,
                memo=memo_txt,
                actor_ulid=actor_ulid,
                request_id=request_id,
                dry_run=dry_run,
            )
        )

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
            decision_fingerprint=preview.decision_fingerprint,
            flags=tuple(flags),
        )

    intent_row.status = "fulfilled"
    db.session.flush()

    event_bus.emit(
        domain="sponsors",
        operation="sponsor_funding_realized",
        actor_ulid=actor_ulid,
        target_ulid=intent_row.ulid,
        request_id=request_id or income_post.id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "sponsor_entity_ulid": intent_row.sponsor_entity_ulid,
            "funding_demand_ulid": defaults.funding_demand_ulid,
            "project_ulid": defaults.project_ulid,
            "journal_ulid": income_post.id,
            "reserve_ulid": (
                None if reserve_post is None else reserve_post.id
            ),
            "fund_code": fund_code,
            "decision_fingerprint": preview.decision_fingerprint,
        },
        changed={"fields": ["status"]},
        meta={
            "amount_cents": amount_cents,
            "income_kind": income_kind,
            "receipt_method": receipt_method,
            "reserve_on_receive": reserve_on_receive,
            "source_profile_key": defaults.source_profile_key,
            "ops_support_planned": defaults.ops_support_planned,
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
        decision_fingerprint=preview.decision_fingerprint,
        flags=tuple(flags),
    )
