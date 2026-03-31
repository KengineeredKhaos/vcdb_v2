from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RbacRoleView:
    code: str
    label: str
    summary: str
    sort_order: int


def _policy_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "policy_rbac.json"


def load_policy_rbac() -> dict[str, Any]:
    path = _policy_path()
    return json.loads(path.read_text(encoding="utf-8"))


def list_rbac_role_views() -> list[RbacRoleView]:
    policy = load_policy_rbac()
    rows = list(policy.get("rbac_roles") or ())
    views: list[RbacRoleView] = []

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("policy_rbac.json must use object-based role definitions.")
        code = str(row.get("code") or "").strip().lower()
        label = str(row.get("label") or "").strip()
        summary = str(row.get("summary") or "").strip()
        sort_order = int(row.get("sort_order") or 0)
        if not code:
            raise ValueError("RBAC role code is required.")
        if not label:
            raise ValueError(f"RBAC role {code} is missing label.")
        if not summary:
            raise ValueError(f"RBAC role {code} is missing summary.")
        views.append(
            RbacRoleView(
                code=code,
                label=label,
                summary=summary,
                sort_order=sort_order,
            )
        )

    views.sort(key=lambda item: (item.sort_order, item.code))
    return views


def list_rbac_role_choices() -> list[tuple[str, str]]:
    return [
        (row.code, f"{row.label} ({row.summary})")
        for row in list_rbac_role_views()
    ]


def get_rbac_role_view(role_code: str) -> RbacRoleView:
    wanted = str(role_code or "").strip().lower()
    for row in list_rbac_role_views():
        if row.code == wanted:
            return row
    raise ValueError(f"Unknown RBAC role: {role_code}")


def validate_rbac_role_code(role_code: str) -> str:
    return get_rbac_role_view(role_code).code
