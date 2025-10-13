# app/extensions/event_bus.py
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, DefaultDict, List, Tuple
from collections import defaultdict
import threading

# -----------------------------------------------------------------------------
# Public contract
# -----------------------------------------------------------------------------
# - register_sink(fn): set a persistence sink (Transactions / Ledger) that accepts
#   an envelope dict and returns an event id (e.g., ULID). Optional; if unset, emit
#   still notifies in-process subscribers.
# - emit(**envelope): validate required keys, forward to sink (if any), then fan out
#   to in-process subscribers (exact type and prefix subscribers). Returns sink result.
# - subscribe(event_type, handler): exact match subscription.
# - subscribe_prefix(prefix, handler): prefix subscription (e.g., "governance.").
# - unsubscribe(handler): remove handler from all subscriptions (helpful for tests).
#
# Envelope requirements (minimal):
#   {'type', 'slice', 'request_id', 'happened_at'}
# You may include anything else (actor_id, target_id, refs, etc.).
#
# IMPORTANT: This bus does not do any I/O; the sink you register does. Keep handlers
# lightweight and non-blocking where possible.
# -----------------------------------------------------------------------------

SinkFn = Callable[[Dict[str, Any]], Optional[str]]
HandlerFn = Callable[[Dict[str, Any]], None]

_REQUIRED_KEYS = {"type", "slice", "request_id", "happened_at"}

_sink: Optional[SinkFn] = None

_lock = threading.RLock()
_exact: DefaultDict[str, List[HandlerFn]] = defaultdict(list)
_prefix: List[
    Tuple[str, HandlerFn]
] = []  # (prefix, handler), checked in order


def register_sink(fn: SinkFn) -> None:
    """Register the Transactions/Ledger slice function that persists events."""
    global _sink
    with _lock:
        _sink = fn


def subscribe(event_type: str, handler: HandlerFn) -> None:
    """Subscribe to a specific event type, e.g., 'governance.policy.updated'."""
    if not callable(handler):
        raise TypeError("handler must be callable")
    with _lock:
        _exact[event_type].append(handler)


def subscribe_prefix(prefix: str, handler: HandlerFn) -> None:
    """Subscribe to all events whose type starts with prefix, e.g., 'finance.'."""
    if not callable(handler):
        raise TypeError("handler must be callable")
    with _lock:
        _prefix.append((prefix, handler))


def unsubscribe(handler: HandlerFn) -> int:
    """Remove a handler from all subscriptions. Returns number of removals."""
    removed = 0
    with _lock:
        for k, lst in list(_exact.items()):
            before = len(lst)
            _exact[k] = [h for h in lst if h is not handler]
            removed += before - len(_exact[k])
            if not _exact[k]:
                _exact.pop(k, None)
        global _prefix
        before = len(_prefix)
        _prefix = [(p, h) for (p, h) in _prefix if h is not handler]
        removed += before - len(_prefix)
    return removed


def emit(**envelope) -> Optional[str]:
    """Emit an event:
    1) Validate minimal shape,
    2) Forward to sink (if registered),
    3) Fan-out to in-process subscribers (best effort).

    Returns the sink's result (e.g., event id) or None if no sink registered.
    """
    missing = _REQUIRED_KEYS - set(envelope.keys())
    if missing:
        raise ValueError(
            f"event_bus.emit missing required fields: {sorted(missing)}"
        )

    # Persist first (if any), then notify in-process subscribers
    result: Optional[str] = None
    if _sink is not None:
        result = _sink(envelope)

    # Copy refs for handlers so they can’t mutate original
    evt = dict(envelope)

    # Fan-out (best effort; handler exceptions are logged and suppressed)
    # Keep a snapshot of subscribers to avoid holding the lock while calling.
    with _lock:
        exact_handlers = list(_exact.get(evt["type"], ()))
        prefix_handlers = [
            h for (p, h) in _prefix if evt["type"].startswith(p)
        ]

    for handler in exact_handlers + prefix_handlers:
        try:
            handler(evt)
        except Exception as e:
            # Minimal inline logging; replace with your logger if present
            print(f"[event_bus] handler error for '{evt['type']}': {e}")

    return result
