# app/extensions/contracts/finance/v1.py
from __future__ import annotations

from typing import Optional

from app.extensions.contracts.types import ContractRequest, ContractResponse
from app.extensions.contracts.validate import load_schema, validate_payload
from app.lib.chrono import now_iso8601_ms
from app.slices.finance import services as fin

SCHEMA_POST = load_schema(
    __file__, "schemas/finance.journal_post.request.json"
)
SCHEMA_REVERSE = load_schema(
    __file__, "schemas/finance.journal_reverse.request.json"
)
SCHEMA_INKIND = load_schema(
    __file__, "schemas/finance.inkind_record.request.json"
)
SCHEMA_RELEASE = load_schema(
    __file__, "schemas/finance.restrict_release.request.json"
)
SCHEMA_PERIOD_SET = load_schema(
    __file__, "schemas/finance.period_set_status.request.json"
)
SCHEMA_BAL_REBLD = load_schema(
    __file__, "schemas/finance.balance_rebuild.request.json"
)
SCHEMA_STAT_REC = load_schema(
    __file__, "schemas/finance.stat_record.request.json"
)
SCHEMA_FUND_GET = {
    "type": "object",
    "properties": {
        "fund_ulid": {"type": "string", "minLength": 26, "maxLength": 26},
        "fund_code": {"type": "string", "minLength": 1, "maxLength": 64},
    },
    "oneOf": [
        {"required": ["fund_ulid"]},
        {"required": ["fund_code"]},
    ],
    "additionalProperties": False,
}

SCHEMA_FUND_LIST = {
    "type": "object",
    "properties": {
        "active_only": {"type": "boolean"},
    },
    "additionalProperties": False,
}


def journal_post(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_POST, req["data"])
    j = fin.post_journal(
        source=d["source"],
        external_ref_ulid=d.get("external_ref_ulid"),
        happened_at_utc=d["happened_at_utc"],
        currency=d.get("currency", "USD"),
        memo=d.get("memo"),
        lines=d["lines"],
        created_by_actor=req.get("actor_ulid"),
    )
    return {
        "contract": "finance.journal.post.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {"journal_ulid": j},
    }


def journal_reverse(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_REVERSE, req["data"])
    rid = fin.reverse_journal(
        journal_ulid=d["journal_ulid"], created_by_actor=req.get("actor_ulid")
    )
    return {
        "contract": "finance.journal.reverse.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {"reversal_journal_ulid": rid},
    }


def inkind_record(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_INKIND, req["data"])
    # DRMO policy: only call this when a reliable valuation exists (enforced by caller’s Governance policy).
    j = fin.record_inkind(
        happened_at_utc=d["happened_at_utc"],
        fund_code=d["fund_code"],
        amount_cents=d["amount_cents"],
        expense_acct=d.get("expense_acct", "5200"),
        revenue_acct=d.get("revenue_acct", "4200"),
        memo=d.get("memo"),
        external_ref_ulid=d.get("external_ref_ulid"),
        created_by_actor=req.get("actor_ulid"),
        valuation_basis=d["valuation_basis"],
    )
    return {
        "contract": "finance.inkind.record.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {"journal_ulid": j},
    }


def restrict_release(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_RELEASE, req["data"])
    j = fin.release_restriction(
        happened_at_utc=d["happened_at_utc"],
        amount_cents=d["amount_cents"],
        restricted_fund=d["restricted_fund"],
        unrestricted_fund=d.get("unrestricted_fund", "unrestricted"),
        memo=d.get("memo"),
        created_by_actor=req.get("actor_ulid"),
    )
    return {
        "contract": "finance.restrict.release.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {"journal_ulid": j},
    }


def period_set_status(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_PERIOD_SET, req["data"])
    fin.set_period_status(period_key=d["period_key"], status=d["status"])
    return {
        "contract": "finance.period.set_status.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {},
    }


def balance_rebuild(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_BAL_REBLD, req["data"])
    out = fin.rebuild_balances(
        period_from=d["period_from"], period_to=d["period_to"]
    )
    return {
        "contract": "finance.balance.rebuild.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": out,
    }


def stat_record(req: ContractRequest) -> ContractResponse:
    d = validate_payload(SCHEMA_STAT_REC, req["data"])
    ulid = fin.record_stat_metric(
        period_key=d["period_key"],
        metric_code=d["metric_code"],
        quantity=d["quantity"],
        unit=d["unit"],
        source=d["source"],
        source_ref_ulid=d.get("source_ref_ulid"),
    )
    return {
        "contract": "finance.stat.record.v2",
        "request_id": req["request_id"],
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": {"stat_ulid": ulid},
    }


def fund_get(req: ContractRequest) -> ContractResponse:
    """Return a single fund summary by ULID or code, or ok=True,data=None if not found."""
    d = validate_payload(SCHEMA_FUND_GET, req.get("data", {}))

    summary: Optional[dict] = None
    if d.get("fund_ulid"):
        summary = fin.get_fund_summary(fund_ulid=d["fund_ulid"])
    else:
        summary = fin.get_fund_summary(fund_code=d["fund_code"])

    return {
        "contract": "finance.fund.get.v1",
        "request_id": req.get("request_id"),
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": summary,  # None if not found
    }


def fund_list(req: ContractRequest) -> ContractResponse:
    """List funds (optionally only active)."""
    d = validate_payload(SCHEMA_FUND_LIST, req.get("data", {}))
    active_only = bool(d.get("active_only", True))
    rows = fin.list_funds(active_only=active_only)
    return {
        "contract": "finance.fund.list.v1",
        "request_id": req.get("request_id"),
        "ts": now_iso8601_ms(),
        "ok": True,
        "data": rows,  # list of fund summaries
    }
