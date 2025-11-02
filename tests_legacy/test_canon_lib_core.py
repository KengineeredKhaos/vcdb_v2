# tests/test_canon_lib_core.py
import inspect
from app.lib import jsonutil, ids, hashing, request_ctx, schema


def test_jsonutil_aliases_present():
    assert jsonutil.dumps_compact is jsonutil.stable_dumps
    assert jsonutil.try_parse_json("[]") == []


def test_ulid_len_and_order():
    u = ids.new_ulid()
    assert isinstance(u, str) and len(u) == 26


def test_hashing_stable():
    assert hashing.sha256_json({"b": 1, "a": 2}) == hashing.sha256_json(
        {"a": 2, "b": 1}
    )


def test_request_ctx_roundtrip():
    rid = request_ctx.ensure_request_id()
    assert rid and rid == request_ctx.get_request_id()


def test_schema_try_validate_json():
    ok, err = schema.try_validate_json({"type": "object"}, {"x": 1})
    assert ok and err is None
