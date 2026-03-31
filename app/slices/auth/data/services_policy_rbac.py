from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from flask import current_app


@dataclass(frozen=True, slots=True)
class RbacRoleView:
    code: str
    label: str
    summary: str
    sort_order: int


class RbacPolicyError(ValueError):
    pass


def _policy_path() -> Path:
    return (
        Path(current_app.root_path)
        / "slices"
        / "auth"
        / "data"
        / "policy_rbac.json"
    )


def load_policy_rbac() -> dict[str, object]:
    path = _policy_path()
    return json.loads(path.read_text(encoding="utf-8"))


def _row_to_view(row: object) -> RbacRoleView:
    if not isinstance(row, dict):
        raise RbacPolicyError("RBAC role rows must be objects.")

    code = str(row.get("code") or "").strip().lower()
    label = str(row.get("label") or "").strip()
    summary = str(row.get("summary") or "").strip()

    try:
        sort_order = int(row.get("sort_order") or 0)
    except (TypeError, ValueError) as exc:
        raise RbacPolicyError(
            f"Invalid sort_order for RBAC role: {code or '?'}"
        ) from exc

    if not code:
        raise RbacPolicyError("RBAC role code is required.")
    if not label:
        raise RbacPolicyError(f"RBAC role label is required: {code}")
    if not summary:
        raise RbacPolicyError(
            f"RBAC role summary is required: {code}"
        )
    if sort_order < 1:
        raise RbacPolicyError(
            f"RBAC role sort_order must be >= 1: {code}"
        )

    return RbacRoleView(
        code=code,
        label=label,
        summary=summary,
        sort_order=sort_order,
    )


def list_rbac_role_views() -> list[RbacRoleView]:
    policy = load_policy_rbac()
    rows = list(policy.get("rbac_roles") or ())
    views = [_row_to_view(row) for row in rows]

    seen: set[str] = set()
    for view in views:
        if view.code in seen:
            raise RbacPolicyError(
                f"Duplicate RBAC role code in policy: {view.code}"
            )
        seen.add(view.code)

    views.sort(key=lambda item: (item.sort_order, item.code))
    return views


def list_rbac_role_choices() -> list[tuple[str, str]]:
    return [
        (view.code, f"{view.label} ({view.summary})")
        for view in list_rbac_role_views()
    ]


def get_rbac_role_view(role_code: str) -> RbacRoleView:
    wanted = str(role_code or "").strip().lower()
    for view in list_rbac_role_views():
        if view.code == wanted:
            return view
    raise LookupError(f"Unknown RBAC role: {role_code}")


def validate_rbac_role_code(role_code: str) -> str:
    return get_rbac_role_view(role_code).code
