# app/lib/security.py — simple role gate (placeholder)
from functools import wraps
import logging


audit_logger = logging.getLogger("vcdb.audit")


def roles_required(*role_names):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
        # TODO: integrate Flask-Login & real roles
        audit_logger.info({
            "event": "rbac.check",
            "roles_required": list(role_names),
            "note": "DEV scaffold — allow all",
        })
        return fn(*args, **kwargs)
    return wrapper
return decorator

def hash_password():
    pass
