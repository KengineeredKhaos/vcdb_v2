
from app.extensions import event_bus


event_bus.emit
    domain: str,                               # owning slice / domain
    operation: str,                            # what happened
    request_id: str,                           # request ULID
    actor_ulid: Optional[str],                 # who acted (ULID | None)
    target_ulid: Optional[str],                # primary subject | N/A
    refs: Optional[Dict[str, Any]] = None,     # small reference dictionary
    changed: Optional[Dict[str, Any]] = None,  # small “before/after” hints
    meta: Optional[Dict[str, Any]] = None,     # tiny extra context (PII-free)
    happened_at_utc: Optional[str] = None,     # ISO-8601 Z
    chain_key: Optional[str] = None,           # alternate chain (rare)
