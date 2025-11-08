# tests/_ulid.py
from app.lib.ids import new_ulid

def make_ulid() -> str:
    u = new_ulid()
    assert isinstance(u, str) and len(u) == 26, f"bad ULID: {u!r}"
    return u

def assert_ulid(u: str) -> None:
    assert isinstance(u, str) and len(u) == 26, f"bad ULID: {u!r}"
