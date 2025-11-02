import inspect
import app.slices.ledger.services as svc
import app.extensions.contracts.ledger.v2 as contract
import app.extensions.event_bus as bus


def _params(fn):
    return list(inspect.signature(fn).parameters.keys())


def test_services_append_event_signature():
    expected = [
        "domain",
        "operation",
        "request_id",
        "actor_ulid",
        "target_ulid",
        "refs",
        "changed",
        "meta",
        "happened_at_utc",
        "chain_key",
    ]
    assert _params(svc.append_event) == expected


def test_services_verify_chain_signature():
    assert _params(svc.verify_chain) == ["chain_key"]


def test_contract_emit_signature():
    expected = [
        "domain",
        "operation",
        "request_id",
        "actor_ulid",
        "target_ulid",
        "refs",
        "changed",
        "meta",
        "happened_at_utc",
        "chain_key",
    ]
    assert _params(contract.emit) == expected


def test_bus_emit_signature():
    expected = [
        "domain",
        "operation",
        "request_id",
        "actor_ulid",
        "target_ulid",
        "refs",
        "changed",
        "meta",
        "happened_at_utc",
        "chain_key",
    ]
    assert _params(bus.emit) == expected
