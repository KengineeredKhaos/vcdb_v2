# tests/test_foundation_roles.py
import pytest

from app.extensions.contracts.auth import v2 as auth_v2
from app.extensions.contracts import governance_v2



def test_rbac_roles_exposed_readonly(app):
    codes = auth_v2.list_all_role_codes()
    assert isinstance(codes, list) and codes, "RBAC role list must not be empty"
    assert all(isinstance(x, str) and x for x in codes)
    # list of all RBAC roles currently in system
    for expected in {"admin", "staff", "user", "auditor", "dev"}:
        assert expected in codes



def test_domain_roles_exposed_readonly(app):
    codes = governance_v2.list_domain_role_codes()
    assert isinstance(codes, list) and codes, "Domain role list must not be empty"
    assert all(isinstance(x, str) and x for x in codes)
    # spot check the canonical domain roles you’ve pinned
    for expected in {"customer", "resource", "sponsor", "governor"}:
        assert expected in codes



def test_rbac_to_domain_mapping_shape(app):
    # If you’ve added this shape (ok to be empty for now),
    # just assert structure
    mapping = getattr(governance_v2, "list_rbac_domain_policy", lambda: {})()
    assert isinstance(mapping, dict)
    # keys optional; if present they must be RBAC role codes and values lists of domain codes
    for k, v in mapping.items():
        assert k in auth_v2.list_all_role_codes()
        assert isinstance(v, list)
        for dom in v:
            assert dom in governance_v2.list_domain_role_codes()
