# app/extensions/contracts/auth/v2.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Single source of truth for RBAC (read-only via Auth contract)
# Canon API: rbac-core v1.0.0  (frozen)
from __future__ import annotations

from typing import List

from flask import current_app  # Not Canonical: DEV OPS Only
from flask_login import current_user  # Not Canonical: DEV OPS Only

from app.extensions import db
from app.slices.auth.models import (
    Role,
    User,
)  # read-only import is fine for a contract


def get_user_roles(user_ulid: str) -> list[str]:
    # In dev/stub mode, prefer the session roles for speed and zero-DB
    if current_app.config.get("AUTH_MODE") == "stub":
        if (
            getattr(current_user, "is_authenticated", False)
            and getattr(current_user, "ulid", None) == user_ulid
        ):
            return [
                str(r).strip().lower()
                for r in (getattr(current_user, "roles", []) or [])
            ]
    # else: fall through to real DB lookup...
    # u = db.session.get(User, user_ulid); return [r.code for r in u.roles if r.is_active]
    return []


# -----------------
# DEVELOPMENT NOTES
# Commented Canonical Code for empty/unseeded database ops
# Dev purposes ONLY !!! Must remove above and uncomment below
# to return to canonical state
# -----------------

# def get_user_roles(user_ulid: str) -> List[str]:
#     """
#     Return active role codes for the user (lowercased, de-duped).
#     No PII beyond role codes.
#     """
#     u = db.session.get(User, user_ulid)
#     if not u:
#         return []
#     # only active roles
#     return sorted(
#         {
#             (r.code or "").strip().lower()
#             for r in (u.roles or [])
#             if r.is_active
#         }
#     )


def list_all_role_codes() -> List[str]:
    """Return all active role codes (lowercased), for UI / choices."""
    rows = db.session.query(Role).filter_by(is_active=True).all()
    return sorted({(r.code or "").strip().lower() for r in rows})
