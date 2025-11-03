# tests/test_extensions_policies_smoke.py
import pytest

from app.extensions.policies import load_policy_issuance


def test_load_policy_issuance_smoke():
    pol = load_policy_issuance()
    # minimal shape assertions so this stays low-friction
    assert isinstance(pol, dict)
    assert "rules" in pol
