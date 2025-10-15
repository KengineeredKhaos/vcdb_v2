from app.slices.auth.services import ensure_role

for c, d in [
    ("user", "Standard user"),
    ("auditor", "Read-only"),
    ("admin", "Administrator"),
]:
    ensure_role(c, d)
