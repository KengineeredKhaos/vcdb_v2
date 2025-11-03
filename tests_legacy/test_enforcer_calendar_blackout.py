# tests/test_enforcer_calendar_blackout.py
import sys
from types import ModuleType, SimpleNamespace

from app.extensions.enforcers import enforcers

MOD_LEAF = "app.extensions.contracts.calendar_v2"
MOD_PARENT = "app.extensions.contracts"
MODPATH = "app.extensions.contracts.calendar_v2"


def install_stub(monkeypatch, is_blackout_impl):
    # Ensure parent package exists
    parent = sys.modules.get(MOD_PARENT)
    if parent is None:
        parent = ModuleType(MOD_PARENT)
        monkeypatch.setitem(sys.modules, MOD_PARENT, parent)

    # Build leaf stub module
    leaf = ModuleType(MOD_LEAF)
    leaf.is_blackout = is_blackout_impl

    # Install leaf in sys.modules and as attribute on parent
    monkeypatch.setitem(sys.modules, MOD_LEAF, leaf)
    setattr(
        parent, "calendar_v2", leaf
    )  # crucial for "from ... import calendar_v2" styles too
    return leaf


def remove_stub(monkeypatch):
    # 1) ensure the submodule can’t be imported
    monkeypatch.delitem(sys.modules, MOD, raising=False)
    # 2) clear any cached attribute on the parent package
    import app.extensions.contracts as contracts

    monkeypatch.delattr(contracts, "calendar_v2", raising=False)


def test_calendar_blackout_ok_blocked(monkeypatch):
    def _blocked(when_iso, project_ulid):
        assert when_iso and project_ulid
        return (True, "Holiday")

    install_stub(monkeypatch, _blocked)

    ctx = SimpleNamespace(
        when_iso="2025-12-25T00:00:00Z",
        project_ulid="01PROJECTULID____________",
    )
    ok, meta = enforcers.calendar_blackout_ok(ctx)
    assert ok is False
    assert meta["reason"] == "calendar_blackout"
    assert meta["window"] == "Holiday"


def test_calendar_blackout_ok_allowed(monkeypatch):
    def _allowed(when_iso, project_ulid):
        return False

    install_stub(monkeypatch, _allowed)

    ctx = SimpleNamespace(
        when_iso="2025-10-29T00:00:00Z",
        project_ulid="01PROJECTULID____________",
    )
    ok, meta = enforcers.calendar_blackout_ok(ctx)
    assert ok is True
    assert meta["reason"] == "ok"


def test_calendar_blackout_ok_contract_unavailable(monkeypatch):
    remove_stub(monkeypatch)
    ctx = SimpleNamespace(
        when_iso="2025-10-29T00:00:00Z",
        project_ulid="01PROJECTULID____________",
    )
    ok, meta = enforcers.calendar_blackout_ok(ctx)
    assert ok is True
    assert meta["reason"] in {"calendar_unavailable", "skipped", "ok"}
