# app/slices/auth/decorators.py
# Thin compatibility shim — forwards to canon RBAC in app/lib/security.py

from app.lib.security import (
    require_feature,  # expose for convenience
    require_login,
    require_permission,  # expose for convenience
    require_roles_all,
)
from app.lib.security import (
    require_roles_any as rbac,  # legacy name used in some places
)
from app.lib.security import (
    require_roles_any as roles_required,  # <-- add this alias
)

__all__ = [
    "rbac",
    "roles_required",
    "require_roles_all",
    "require_login",
    "require_permission",
    "require_feature",
]
