# app/extensions/contracts/auth_v2.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: app/extensions/contracts/auth_v2.py
# Purpose: Single source of truth for RBAC role lookups (read-only via Auth contract)
# Canon API: rbac-core v1.0.0  (frozen)

from __future__ import annotations

from app.extensions import db
from app.slices.auth.models import Role, User

# read-only import is fine for a contract


def get_user_roles(user_ulid: str) -> list[str]:
    """
    Return active RBAC role codes for the given user ULID.

    - Lowercased and de-duplicated.
    - Returns an empty list if the user does not exist or has no active roles.
    - Exposes no PII beyond role codes.

    This is a pure read-only contract function: it does not inspect Flask
    request/session state and does not mutate the database.
    """
    u = db.session.get(User, user_ulid)
    if not u:
        return []

    return sorted(
        {
            (r.code or "").strip().lower()
            for r in (u.roles or [])
            if r.is_active
        }
    )


def list_all_role_codes() -> list[str]:
    """
    Return all active RBAC role codes (lowercased, de-duplicated).

    Intended for UI choices and admin tooling that needs to present
    the current RBAC role catalog. Actual role *definitions* and
    semantics are governed by the Governance slice; Auth owns the
    Role table and assignments only.
    """
    rows = db.session.query(Role).filter_by(is_active=True).all()
    return sorted({(r.code or "").strip().lower() for r in rows})
