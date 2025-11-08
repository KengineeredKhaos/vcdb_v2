# tests/test_lib_core_time_ctx.py

from app.lib.chrono import (
    as_naive_utc,
    ensure_aware_utc,
    now_iso8601_ms,
    parse_iso8601,
    to_iso8601,
    utcnow_aware,
    utcnow_naive,
)
from app.lib.ids import is_ulid, new_ulid
from app.lib.request_ctx import (
    ensure_request_id,
    get_actor_ulid,
    get_request_id,
    reset_request_ctx,
    set_actor_ulid,
    set_request_id,
)


def test_chrono_roundtrip_and_awareness():
    # string roundtrip stays parseable & aware
    s = now_iso8601_ms()
    dt = parse_iso8601(s)
    assert dt.tzinfo is not None

    # to_iso8601 produces a string parseable back to aware UTC
    s2 = to_iso8601(dt)
    dt2 = parse_iso8601(s2)
    assert dt2.tzinfo is not None

    # naive/aware helpers behave as advertised
    aware = utcnow_aware()
    naive = as_naive_utc(aware)
    assert naive.tzinfo is None

    reaware = ensure_aware_utc(naive)
    assert reaware.tzinfo is not None

    # utcnow_naive explicitly returns naive
    n2 = utcnow_naive()
    assert n2.tzinfo is None

    # explicit set works
    rid2 = new_ulid()
    set_request_id(rid2)
    assert get_request_id() == rid2

    actor = new_ulid()
    set_actor_ulid(actor)
    assert get_actor_ulid() == actor
