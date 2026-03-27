# tests/slices/auth/conftest.py

from __future__ import annotations

import pytest

from app.slices.auth import routes as auth_routes


@pytest.fixture(autouse=True)
def _stub_auth_event_bus(monkeypatch):
    monkeypatch.setattr(
        auth_routes.event_bus,
        "emit",
        lambda **kwargs: None,
    )
