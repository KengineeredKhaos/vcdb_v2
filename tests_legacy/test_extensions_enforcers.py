# tests/test_extensions_enforcers.py
from types import SimpleNamespace

import pytest

from app.extensions.enforcers import _Enforcers, enforcers


def test_local_registry_basic():
    """Use a fresh local registry to avoid touching the global singleton."""
    reg = _Enforcers()

    # register by function argument
    def alpha(ctx):  # pragma: no cover - trivial handler
        return "A"

    reg.register("alpha", alpha)

    # register by decorator
    @reg.register("bravo")
    def _bravo(ctx):  # pragma: no cover
        return "B"

    # names, get, attr access, contains
    assert set(reg.names()) == {"alpha", "bravo"}
    assert "alpha" in reg and "bravo" in reg and "charlie" not in reg
    assert reg.get("alpha") is alpha
    assert reg.get("missing") is None

    # __getattr__ returns callables, unknown raises AttributeError
    assert callable(reg.alpha) and callable(reg.bravo)
    with pytest.raises(AttributeError):
        _ = reg.charlie  # noqa: F841


def test_local_registry_overwrite():
    """Later register() calls for the same name should overwrite."""
    reg = _Enforcers()

    def f1(ctx):
        return 1

    def f2(ctx):
        return 2

    reg.register("dup", f1)
    assert reg.dup(SimpleNamespace()) == 1

    reg.register("dup", f2)
    assert reg.dup(SimpleNamespace()) == 2


def test_global_registry_isolated(monkeypatch):
    """
    Snapshot/restore the global singleton's map so this test never leaks
    handlers into the application.
    """
    snapshot = dict(enforcers._map)  # type: ignore[attr-defined]
    try:
        enforcers._map.clear()  # type: ignore[attr-defined]

        @enforcers.register("ping")
        def _ping(ctx):
            return "pong"

        assert "ping" in enforcers
        assert enforcers.ping(SimpleNamespace()) == "pong"
        assert set(enforcers.names()) == {"ping"}

        # missing attribute → AttributeError (good for tooling/Pyright)
        with pytest.raises(AttributeError):
            _ = enforcers.nope  # noqa: F841
    finally:
        enforcers._map.clear()  # type: ignore[attr-defined]
        enforcers._map.update(snapshot)  # type: ignore[attr-defined]
