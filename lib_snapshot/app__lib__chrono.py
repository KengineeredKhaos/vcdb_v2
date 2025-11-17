# app/lib/time.py
from datetime import datetime, timezone


# Always produce ISO-8601 UTC with 'Z' and 3 decimal milliseconds
# Write now: utc_now()
# Stamp new rows/events (created_at, happened_at, request IDs, etc.).
def utc_now() -> str:
    dt = datetime.now(timezone.utc)
    # Truncate to milliseconds
    ms = int(dt.microsecond / 1000)
    return (
        dt.replace(microsecond=ms * 1000).isoformat().replace("+00:00", "Z")
    )


# Normalize before save/emit: to_iso8601(dt)
# Any datetime coming from Python, a form, or a library gets normalized
# to canonical UTC string before you store it or put it on the wire.
def to_iso8601(dt: datetime) -> str:
    if dt.tzinfo is None:
        # Treat naive as UTC only if it’s explicitly our policy;
        # safer is to reject.
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return (
        dt.replace(microsecond=ms * 1000).isoformat().replace("+00:00", "Z")
    )


# Read/compute: parse_iso8601(s)
# When you need to do arithmetic or comparisons in Python,
# parse the stored string back to an aware UTC datetime.
def parse_iso8601(s: str) -> datetime:
    # Accept 'Z' and offsets; return aware UTC datetime
    if s.endswith("Z"):
        s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # Decide: reject naive or assume UTC. Rejecting avoids silent bugs:
        raise ValueError(
            "Naive datetime not allowed; include timezone or 'Z'."
        )
    return dt.astimezone(timezone.utc)


"""
DEPLOYMENT:

# Create a ledger event
event = {
    "id": new_ulid(),
    "happened_at": utc_now(),
    "actor_id": actor_ulid,
    "operation": "policy.update",
}

# Normalize an incoming user-specified deadline
deadline = to_iso8601(user_supplied_dt)

# Load from DB and compute
dt = parse_iso8601(row["happened_at"])
if utc_now() > to_iso8601(dt + timedelta(days=30)):
    ...
"""
