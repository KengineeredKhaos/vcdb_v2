# app/lib/__init__.py
"""
CANON: Do not re-export from lib.

Import concrete modules directly, e.g.:
  from app.lib.ids import new_ulid
  from app.lib.chrono import now_iso8601_ms
  from app.lib.schema import validate_json
"""

__all__: list[str] = []  # explicit: nothing is exported here
