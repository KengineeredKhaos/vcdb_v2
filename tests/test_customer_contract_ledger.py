# tests/test_customer_contract_ledger.py
import json
from app.extensions import db
from app.lib.ids import new_ulid
from app.extensions.contracts import customers_v2 as contract
from app.slices.entity import services as ent_svc
from app.slices.customers import services as cust_svc
from app.slices.ledger.models import LedgerEvent


def _mk_customer_ulid() -> str:
    ent_ulid = ent_svc.ensure_person(
        first_name="Ledger",
        last_name="Probe",
        email=None,
        phone=None,
        request_id=new_ulid(),
        actor_ulid=None,
    )
    return cust_svc.ensure_customer(
        entity_ulid=ent_ulid,
        request_id=new_ulid(),
        actor_ulid=None,
    )


def _get_attr(obj, names):
    for n in names:
        if hasattr(obj, n):
            val = getattr(obj, n)
            if val is not None:
                return val
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


def _latest(domain: str, operation: str, target_ulid: str):
    return (
        db.session.query(LedgerEvent)
        .filter(
            LedgerEvent.domain == domain,
            LedgerEvent.operation == operation,
            LedgerEvent.target_ulid == target_ulid,
        )
        .order_by(LedgerEvent.happened_at_utc.desc())
        .first()
    )


def test_ledger_emits_created_and_profile_and_verification(app):
    cust_ulid = _mk_customer_ulid()

    # created_insert exists
    e_create = _latest("customers", "created_insert", cust_ulid)
    assert e_create is not None, "expected customers.created_insert"
    assert e_create.target_ulid == cust_ulid

    # Tier-1 → profile_update with refs.section mentioning tier1 OR changed.fields includes 'tier1'
    _ = contract.update_tier1(
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

    e_tier1 = _latest("customers", "profile_update", cust_ulid)
    assert (
        e_tier1 is not None
    ), "expected customers.profile_update after tier1 update"

    refs_raw = _get_attr(
        e_tier1,
        (
            "refs",
            "refs_json",
            "reference",
            "reference_json",
            "meta",
            "meta_json",
        ),
    )
    refs = _to_dict(refs_raw)
    changed_raw = _get_attr(
        e_tier1,
        (
            "changed",
            "changed_json",
            "delta",
            "delta_json",
            "payload",
            "payload_json",
            "details",
            "details_json",
        ),
    )
    changed = _to_dict(changed_raw)

    fields = set(changed.get("fields") or [])
    if fields:
        assert (
            "tier1" in fields
        ), f"expected changed.fields to include 'tier1', got: {fields}"
    else:
        section = str(refs.get("section", "")).lower()
        assert (
            "tier1" in section
        ), f"expected refs.section to include 'tier1', got: {section!r}"

    # Veteran verification → verification_updated; changed.fields ideally includes both keys
    _ = contract.verify_veteran(
        customer_ulid=cust_ulid,
        method="va_id",
        verified=True,
        actor_ulid=None,
        actor_has_governor=True,
        request_id=new_ulid(),
    )

    e_vet = _latest("customers", "verification_updated", cust_ulid)
    assert e_vet is not None, "expected customers.verification_updated"

    changed_raw2 = _get_attr(
        e_vet,
        (
            "changed",
            "changed_json",
            "delta",
            "delta_json",
            "payload",
            "payload_json",
            "details",
            "details_json",
        ),
    )
    changed2 = _to_dict(changed_raw2)
    fields2 = set(changed2.get("fields") or [])
    if fields2:
        assert {"is_veteran_verified", "veteran_method"}.issubset(fields2)
