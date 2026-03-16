# app/slices/sponsors/services_funding_realization.py

from __future__ import annotations

from dataclasses import dataclass

from app.extensions import db, event_bus
from app.extensions.contracts import calendar_v2, finance_v2, governance_v2
from app.lib.chrono import now_iso8601_ms

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
    fund_key: str

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


def _require_realizable_demand(demand: calendar_v2.FundingDemandDTO) -> None:
    if demand.status not in _ALLOWED_DEMAND_STATUS:
        raise ValueError(
            "funding demand must be published or funding_in_progress"
        )


def realize_funding_intent(
    *,
    intent_ulid: str,
    amount_cents: int,
    happened_at_utc: str,
    fund_key: str,
    income_kind: str,
    receipt_method: str,
    reserve_on_receive: bool = True,
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
    if not fund_key:
        raise ValueError("fund_key required")
    if not income_kind:
        raise ValueError("income_kind required")
    if not receipt_method:
        raise ValueError("receipt_method required")

    intent_row = _get_intent_or_raise(intent_ulid)
    _require_realizable_intent(intent_row)

    intent_amount = int(intent_row.amount_cents or 0)
    if amount_cents != intent_amount:
        raise ValueError(
            "partial realization is not supported in this baseline"
        )

    demand = calendar_v2.get_funding_demand(intent_row.funding_demand_ulid)
    _require_realizable_demand(demand)

    fund_meta = governance_v2.get_fund_key(fund_key)
    restriction_keys = governance_v2.apply_fund_defaults(
        fund_key=fund_key,
        restriction_keys=(),
    )

    sem = governance_v2.validate_semantic_keys(
        fund_key=fund_key,
        restriction_keys=restriction_keys,
        income_kind=income_kind,
        demand_eligible_fund_keys=tuple(demand.eligible_fund_keys),
    )
    if not sem.ok:
        raise ValueError("; ".join(sem.errors) or "invalid semantics")

    preview = governance_v2.preview_funding_decision(
        governance_v2.FundingDecisionRequestDTO(
            op="receive",
            amount_cents=amount_cents,
            funding_demand_ulid=demand.funding_demand_ulid,
            project_ulid=demand.project_ulid,
            income_kind=income_kind,
            restriction_keys=restriction_keys,
            demand_eligible_fund_keys=tuple(demand.eligible_fund_keys),
            selected_fund_key=fund_key,
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
            fund_key=fund_key,
            fund_label=fund_meta.label,
            fund_restriction_type=fund_restriction_type,
            income_kind=income_kind,
            receipt_method=receipt_method,
            source="sponsors",
            source_ref_ulid=intent_row.ulid,
            funding_demand_ulid=demand.funding_demand_ulid,
            project_ulid=demand.project_ulid,
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
                funding_demand_ulid=demand.funding_demand_ulid,
                fund_key=fund_key,
                amount_cents=amount_cents,
                source="sponsors",
                fund_label=fund_meta.label,
                fund_restriction_type=fund_restriction_type,
                project_ulid=demand.project_ulid,
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
            funding_demand_ulid=demand.funding_demand_ulid,
            project_ulid=demand.project_ulid,
            amount_cents=amount_cents,
            fund_key=fund_key,
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
            "funding_demand_ulid": demand.funding_demand_ulid,
            "project_ulid": demand.project_ulid,
            "journal_ulid": income_post.id,
            "reserve_ulid": (
                None if reserve_post is None else reserve_post.id
            ),
            "fund_key": fund_key,
            "decision_fingerprint": preview.decision_fingerprint,
        },
        changed={"fields": ["status"]},
        meta={
            "amount_cents": amount_cents,
            "income_kind": income_kind,
            "receipt_method": receipt_method,
            "reserve_on_receive": reserve_on_receive,
        },
    )

    return FundingRealizationResult(
        intent_ulid=intent_row.ulid,
        sponsor_entity_ulid=intent_row.sponsor_entity_ulid,
        funding_demand_ulid=demand.funding_demand_ulid,
        project_ulid=demand.project_ulid,
        amount_cents=amount_cents,
        fund_key=fund_key,
        journal_ulid=income_post.id,
        reserve_ulid=None if reserve_post is None else reserve_post.id,
        status=intent_row.status,
        decision_fingerprint=preview.decision_fingerprint,
        flags=tuple(flags),
    )
