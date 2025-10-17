# app/extensions/contracts/governance/v1.py
from __future__ import annotations

from types import SimpleNamespace
from typing import List, Optional

from app.slices.governance import services as gsvc


def get_states() -> List[SimpleNamespace]:
    """Public read API: returns simple objects with .code and .name."""
    rows = gsvc.svc_list_states_rows()
    return [SimpleNamespace(code=r.code, name=r.name) for r in rows]


def get_domain_roles() -> List[SimpleNamespace]:
    """Domain roles (customer, resource, sponsor, governor). Not RBAC."""
    rows = gsvc.svc_list_domain_roles_rows()
    return [SimpleNamespace(code=r.code, name=r.name) for r in rows]


def get_policy_value(namespace: str, key: str) -> Optional[dict]:
    """Return the active policy value (dict) or None."""
    return gsvc.svc_get_policy_value(namespace, key)
