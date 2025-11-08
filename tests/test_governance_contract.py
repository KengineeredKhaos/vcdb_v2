# tests/test_governance_contract.py
import json

from app.extensions import db
from app.extensions.contracts import customers_v2 as cust
from app.extensions.contracts import governance_v2 as gov
from app.lib.ids import new_ulid
from app.slices.customers import services as cust_svc
from app.slices.entity import services as ent_svc
from app.slices.ledger.models import LedgerEvent


def _mk_customer():
    ent_ulid = ent_svc.ensure_person(
        first_name="Gov",
        last_name="Loop",
        email=None,
        phone=None,
        request_id=new_ulid(),
        actor_ulid=None,
    )
    cust_ulid = cust_svc.ensure_customer(
        entity_ulid=ent_ulid,
        request_id=new_ulid(),
        actor_ulid=None,
    )
    return cust_ulid


def _get_attr(obj, names):
    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            if v is not None:
                return v
    return None


def _to_dict(val):
    if val is None:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, (bytes, bytearray)):
        try:
            return json.loads(val.decode("utf-8"))
        except Exception:
            return {}
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            s = val.strip()
            if s.startswith("{") and s.endswith("}"):
                s = s.replace("'", '"')
                try:
                    return json.loads(s)
                except Exception:
                    return {}
            return {}
    return {}


def _latest(domain, op, target_ulid):
    return (
        db.session.query(LedgerEvent)
        .filter(
            LedgerEvent.domain == domain,
            LedgerEvent.operation == op,
            LedgerEvent.target_ulid == target_ulid,
        )
        .order_by(LedgerEvent.happened_at_utc.desc())
        .first()
    )


def test_governance_decision_flow_and_ledger(app):
    cust_ulid = _mk_customer()

    # Set veteran verified + Tier1 housing crisis → homeless
    cust.verify_veteran(
        customer_ulid=cust_ulid,
        method="va_id",
        verified=True,
        actor_ulid=None,
        actor_has_governor=True,
        request_id=new_ulid(),
    )
    cust.update_tier1(
        customer_ulid=cust_ulid,
        payload={
            "food": 2,
            "hygiene": 2,
            "health": 2,
            "housing": 1,
            "clothing": 3,
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )
    # Also make tier2_min = 1 (watchlist)
    cust.update_tier2(
        customer_ulid=cust_ulid,
        payload={
            "income": 1,
            "employment": 2,
            "transportation": 3,
            "education": 3,
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )

    # Evaluate governance
    req_id = new_ulid()
    dec = gov.evaluate_customer(cust_ulid, request_id=req_id, actor_ulid=None)

    assert dec.customer_ulid == cust_ulid
    assert dec.is_veteran_verified is True
    assert dec.is_homeless_verified is True
    assert dec.attention_required is True  # tier1_min == 1
    assert dec.watchlist is True  # tier2_min == 1
    assert dec.eligible_veteran_only is True
    assert dec.eligible_homeless_only is True

    # Ledger event written
    e = _latest("governance", "decision_made", cust_ulid)
    assert e is not None, "expected governance.decision_made"

    changed_raw = _get_attr(
        e,
        (
            "changed",
            "changed_json",
            "payload",
            "payload_json",
            "details",
            "details_json",
        ),
    )
    changed = _to_dict(changed_raw)
    decisions = changed.get("decisions") or {}
    # We don't require all keys (tolerant), but core ones should be true
    assert decisions.get("attention_required") is True
    assert decisions.get("eligible_veteran_only") is True
