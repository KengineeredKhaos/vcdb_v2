# app/lib/security.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Single source of truth for RBAC (read-only via Auth contract)
# Canon API: rbac-core v1.0.0  (frozen)

"""
Here’s a compact “cheat sheet” for route gates you now have,
with when to use each and copy-paste snippets for your Dev Runbook.

# Core concepts (quick)

* **RBAC roles** = application roles (e.g., `admin`, `auditor`, `dev`).
  Use: `@rbac("admin")`
    or `@require_roles_any(...)`
    or `@require_roles_all(...)`

* **Domain roles** = business/operational roles
  (e.g., `governor`, `staff`, `customer`).
  Use: `@require_domain_roles_any(...)`
    or `@require_domain_roles_all(...)`
  In non-prod, **devs can temporarily assume domain roles** via `/dev/assume`.

* **Env guard** = disable certain routes in production (e.g., dev tools).
  Use: `APP_MODE != "production"` checks.

---

# 1) Single gate: RBAC only

**When:** Global admin console, audit screens, user management—things that
 aren’t domain-specific.

```python
from app.slices.auth.decorators import rbac

@rbac("admin")
def admin_dashboard():
    ...
```

**Variant (any of multiple RBAC roles):**

```python
from app.lib.security import require_roles_any

@require_roles_any("admin", "auditor")
def system_logs():
    ...
```

**Variant (must have all listed RBAC roles):**

```python
from app.lib.security import require_roles_all

@require_roles_all("admin", "security_officer")
def sensitive_settings():
    ...
```

---

# 2) Single gate: Domain role only

**When:** Operational screens where *any* authenticated user may exist,
 but only certain **domain** personas should act (e.g., “staff” tools).

```python
from app.lib.security import require_domain_roles_any

@require_domain_roles_any("staff")
def intake_form():
    ...
```

**Notes:**

* In non-prod, a user with RBAC `dev` can `/dev/assume` `["staff"]`
  to exercise this route.
* In prod, assumption is disabled; users must truly have the domain role.

**All-of domain roles (rare):**
(this gives Staff special Governor access)

```python
from app.lib.security import require_domain_roles_all

@require_domain_roles_all("staff", "governor")
def special_joint_action():
    ...
```
We don't realisticly need/want/use this.
It is a byproduct of the Dev flexible roles configuration.
---

# 3) Two-gate pattern: RBAC & Domain

**When:** You need **both** app-level permission and business persona
—e.g., Governance Policy editor.
This is your go-to for anything writing Governance policy.

```python
from app.slices.auth.decorators import rbac
from app.lib.security import require_domain_roles_any

@rbac("admin")                           # RBAC gate
@require_domain_roles_any("governor")    # Domain gate
def governance_policy_edit():
    ...
```

**Why 2 gates?**

* RBAC `admin` controls *who can change settings at all*.
* Domain `governor` ensures it’s a **governance** actor, not just any admin.

---

# 4) Read-only vs write split

**When:** Anyone can view policy, but only Admin+Governor can edit.

```python
# Read-only view: RBAC auditor or admin (no domain gate)
@require_roles_any("auditor", "admin")
def governance_policy_view():
    ...

# Edit: strict two-gate
@rbac("admin")
@require_domain_roles_any("governor")
def governance_policy_edit():
    ...
```

---

# 5) Dev-only utilities (non-prod)

**When:** Local/test tools, seeders, “assume roles,” mock screens.

```python
from flask import current_app, jsonify
from app.slices.auth.decorators import rbac

def _nonprod_guard():
    if current_app.config.get("APP_MODE") == "production":
        return jsonify(ok=False, error="disabled in production"), 403

@rbac("dev")
def dev_only_tool():
    guard = _nonprod_guard()
    if guard: return guard
    ...
```

---

# 6) Combining “any-of RBAC” with “any-of Domain”

**When:** Flexible access—e.g., let either admins or auditors in,
but they must also be a relevant domain persona.

```python
from app.lib.security import require_roles_any, require_domain_roles_any

@require_roles_any("admin", "auditor")
@require_domain_roles_any("governor", "staff")
def policy_audit_report():
    ...
```

---

# 7) Capability check (if/when you add it)

**When:** You model fine-grained abilities (e.g., `can_assume_roles`).

```python
from app.lib.security import require_capabilities_any

@rbac("dev")
@require_capabilities_any("can_assume_roles")
def dev_assume_endpoint():
    ...
```

*(If `require_capabilities_any` isn’t in your `security.py` yet,
it’s a ~10-line mirror of `require_roles_any`.)*

---

# 8) Advanced: project/record-scoped domain checks

**When:** Domain role is necessary but you also need object-level guard
(e.g., staff can only touch their own project).
Pair a domain gate with your own predicate.

```python
@require_domain_roles_any("staff")
def update_project(pid):
    project = Project.get(pid)
    if project.org_ulid not in current_user.orgs:
        abort(403)
    ...
```

---

# 9) Practical examples in your app

**Governance policy JSON editor (Admin slice):**

```python
@rbac("admin")
@require_domain_roles_any("governor")
def policy_put():
    # load JSON from request, validate, write to slices/governance/data/
    ...
```

**Logistics: issue screen (only staff can issue):**

```python
@require_domain_roles_any("staff")
def issue_item():
    ...
```

**Catalog maintenance (admins or governors can view; only admins modify):**

```python
@require_roles_any("admin", "governor")
def catalog_view():
    ...

@rbac("admin")
def catalog_patch():
    ...
```

**Dev tools (local only):**

```python
@rbac("dev")
def dev_assume():
    guard = _nonprod_guard()
    if guard: return guard
    # set session['assumed_domain_roles'] = [...]
```

---

# 10) Quick reference (copy into Runbook)

* **RBAC (any):** `@require_roles_any("admin", "auditor")`
* **RBAC (all):** `@require_roles_all("admin", "security_officer")`
* **Domain (any):** `@require_domain_roles_any("staff", "governor")`
* **Domain (all):** `@require_domain_roles_all("staff", "governor")`
* **Two-gate (strict):** `@rbac("admin")` + `@require_domain_roles_any("governor")`
* **Dev-only:** `@rbac("dev")` + `APP_MODE != "production"` guard
* **Assumed roles:** Only affect **domain** gates, and only when `APP_MODE != "production"` and user has `dev`. RBAC gates are unaffected.


"""
from __future__ import annotations

from functools import wraps
from typing import Iterable, Set

from flask import abort, current_app, session
from flask_login import current_user

from app.extensions.contracts import auth_v2 as auth_ro

ASSUME_KEY = "assumed_domain_roles"


def _dev_assumption_enabled(user) -> bool:
    if current_app.config.get("APP_MODE") == "production":
        return False
    has_dev = "dev" in getattr(user, "rbac_roles", [])
    # TODO: flip to real capability when Auth contract exposes it.
    # For now, use config toggle to allow/deny assumption in non-prod.
    allow = bool(current_app.config.get("ALLOW_DEV_ASSUME_ROLES", True))
    return has_dev and allow


def current_domain_roles(user) -> list[str]:
    base = set(getattr(user, "domain_roles", []))
    if _dev_assumption_enabled(user):
        assumed = set(session.get(ASSUME_KEY, []))
        return sorted(base | assumed)
    return sorted(base)


# -----------------
# Internal helpers
# -----------------


def _norm(codes: Iterable[str]) -> Set[str]:
    return {str(c).strip().lower() for c in (codes or []) if c}


def _current_user_ulid() -> str | None:
    # SessionUser sets .ulid; real User model also has .ulid
    return getattr(current_user, "ulid", None)


def _current_user_roles() -> list[str]:
    """
    Prefer roles carried in the session object (fast).
    If not present or you want the ground truth,
    fall back to the Auth contract.
    """
    if getattr(current_user, "roles", None):
        return sorted(_norm(current_user.roles))
    uid = _current_user_ulid()
    if not uid:
        return []
    return sorted(_norm(auth_ro.get_user_roles(uid)))


def _is_authenticated() -> bool:
    return bool(getattr(current_user, "is_authenticated", False))


# -----------------
# Predicates
# (usable in services/CLI)
# -----------------


def user_has_any_roles(user_ulid: str, *need_codes: str) -> bool:
    have = set(auth_ro.get_user_roles(user_ulid))
    need = _norm(need_codes)
    return not have.isdisjoint(need) if need else True


def user_has_all_roles(user_ulid: str, *need_codes: str) -> bool:
    have = set(auth_ro.get_user_roles(user_ulid))
    need = _norm(need_codes)
    return need.issubset(have) if need else True


# -----------------
# Route Decorators
# (explicit where needed)
# -----------------
"""
How To Deploy RBAC & Domain role gates:

****   include in top level imports   ****
from app.lib.security import rbac, require_domain_roles_any

****   route predicate   ****
@rbac("admin")                           # RBAC gate
@require_domain_roles_any("governor")    # Domain-role gate (if required)
def <replace_with_route_nomenclature>():
    ...
Example above structured to respect Dev assertion of flexible Domain Roles
"""


def require_login():
    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            return view(*args, **kwargs)

        return wrap

    return deco


def require_roles_any(*need_codes: str):
    need = _norm(need_codes)

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            have = set(_current_user_roles())
            if need and have.isdisjoint(need):
                abort(403)
            return view(*args, **kwargs)

        return wrap

    return deco


def require_roles_all(*need_codes: str):
    need = _norm(need_codes)

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            have = set(_current_user_roles())
            if need and not need.issubset(have):
                abort(403)
            return view(*args, **kwargs)

        return wrap

    return deco


def require_domain_roles_any(*need_codes: str):
    need = _norm(need_codes)

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            # Domain roles = DB roles (+ assumed roles if APP_MODE != production and user has 'dev')
            have = set(current_domain_roles(current_user))
            if need and have.isdisjoint(need):
                abort(403)
            return view(*args, **kwargs)

        return wrap

    return deco


def require_domain_roles_all(*need_codes: str):
    need = _norm(need_codes)

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            have = set(current_domain_roles(current_user))
            if need and not need.issubset(have):
                abort(403)
            return view(*args, **kwargs)

        return wrap

    return deco


# convenience alias (to mirror rbac alias at bottom)
domain_roles_required = require_domain_roles_any


# -----------------
# Public helpers:
# role reading & convenience
# -----------------


def current_user_ulid() -> str | None:
    """Stable way for callers to get the current user's ULID (or None)."""
    return getattr(current_user, "ulid", None)


def current_user_roles() -> set[str]:
    """Ground-truth role set for the current user (lowercased)."""
    # Prefer session-carried roles if present; otherwise hit the Auth contract
    sess_roles = getattr(current_user, "roles", None)
    if sess_roles:
        return _norm(sess_roles)
    uid = current_user_ulid()
    if not uid:
        return set()
    return set(auth_ro.get_user_roles(uid))


def user_is_admin(user_ulid: str | None = None) -> bool:
    """Convenience for the common case."""
    if user_ulid is None:
        uid = current_user_ulid()
    else:
        uid = user_ulid
    if not uid:
        return False
    return "admin" in set(auth_ro.get_user_roles(uid))


# -----------------
# Feature flag gate
# -----------------


def require_feature(flag_name: str):
    """
    Gate a route behind a simple app.config feature flag (truthy).
    Keeps unfinished admin pages tucked away without RBAC churn.
    """

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not bool(current_app.config.get(flag_name, False)):
                abort(404)
            return view(*args, **kwargs)

        return wrap

    return deco


# -----------------
# Optional: permission shim
# (role->permission mapping today, contract later)
# -----------------


def _permission_roles_map() -> dict[str, set[str]]:
    """
    Returns a mapping of permission -> roles that grant it.
    Today sourced from config PERMISSIONS_MAP; later can come from an Auth contract
    without changing call sites.
    Example config:
      PERMISSIONS_MAP = {
          "governance:policy:edit": {"admin"},
          "ledger:read": {"admin","auditor"},
      }
    """

    raw = current_app.config.get("PERMISSIONS_MAP", {}) or {}
    return {str(p).lower(): _norm(roles) for p, roles in raw.items()}


def user_has_permission(user_ulid: str, permission: str) -> bool:
    """Does this user have the given permission (via any mapped role)?"""
    need = str(permission).lower().strip()
    perm_map = _permission_roles_map()
    roles_for_perm = perm_map.get(need, set())
    if not roles_for_perm:
        return False
    have = set(auth_ro.get_user_roles(user_ulid))
    return not have.isdisjoint(roles_for_perm)


def require_permission(permission: str):
    """
    Route decorator that enforces a high-level permission.
    Internally maps permission -> roles (from config today).
    """
    need = str(permission).lower().strip()

    def deco(view):
        @wraps(view)
        def wrap(*args, **kwargs):
            if not _is_authenticated():
                abort(401)
            uid = current_user_ulid()
            if not uid or not user_has_permission(uid, need):
                abort(403)
            return view(*args, **kwargs)

        return wrap

    return deco


# -----------------
# compatibility aliases
# (so legacy imports keep working)
# -----------------

# If older code does: from app.slices.auth.decorators import rbac
rbac = require_roles_any
roles_required = require_roles_any


__all__ = [
    # decorators
    "require_roles_any",
    "require_domain_roles_any",
    # alias preserved for legacy imports
    "rbac",
]
