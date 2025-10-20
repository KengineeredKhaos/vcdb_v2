# app/slices/auth/decorators.py
# Thin compatibility shim — forwards to canon RBAC in app/lib/security.py

from app.lib.security import (
    require_roles_any as rbac,  # legacy name used in some places
    require_roles_any as roles_required,  # <-- add this alias
    require_roles_all,
    require_login,
    require_permission,  # expose for convenience
    require_feature,  # expose for convenience
)

__all__ = [
    "rbac",
    "roles_required",
    "require_roles_all",
    "require_login",
    "require_permission",
    "require_feature",
]
