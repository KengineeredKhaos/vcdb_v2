# app/extensions/event_bus.py
from __future__ import annotations

from threading import RLock
from typing import Callable, Iterable, Optional

from app.lib.chrono import now_iso8601_ms

Envelope = dict
Sink = Callable[[Envelope], Optional[str]]


class EventBus:
    """Schema-aligned bus for ledger events (single responsibility: normalize + fan-out)."""

    def __init__(self) -> None:
        self._sinks: list[Sink] = []
        self._lock = RLock()

    def register_sink(self, sink: Sink) -> None:
        with self._lock:
            self._sinks.append(sink)

    def sinks(self) -> Iterable[Sink]:
        with self._lock:
            return tuple(self._sinks)

    def emit(
        self,
        *,
        # --- required by contract ---
        domain: str,
        operation: str,
        request_id: str,
        actor_ulid: str,
        # --- optional by contract ---
        happened_at: Optional[str] = None,
        target_ulid: Optional[str] = None,
        changed: Optional[dict] = None,
        refs: Optional[dict] = None,
        correlation_id: Optional[str] = None,
        # --- legacy compatibility (will be mapped if provided) ---
        **legacy,
    ) -> Optional[str]:
        # Backfill timestamp
        if not happened_at:
            happened_at = now_iso8601_ms()

        # Map legacy fields → contract fields (so old callers don’t explode)
        # - slice -> domain
        # - type "domain.operation" -> domain/operation (if provided)
        # - actor_id -> actor_ulid
        # - target_id -> target_ulid
        # - changed_fields -> changed
        # - request_id required: keep if already passed; else accept legacy
        if not domain and (sl := legacy.get("slice")):
            domain = sl
        if legacy.get("type") and not operation:
            t = legacy["type"]
            if "." in t:
                d, op = t.split(".", 1)
                domain = domain or d
                operation = op
        actor_ulid = actor_ulid or legacy.get("actor_id")
        target_ulid = target_ulid or legacy.get("target_id")
        changed = changed or legacy.get("changed_fields")
        refs = refs or legacy.get("refs")
        if not correlation_id:
            correlation_id = legacy.get("correlation_id")

        env: Envelope = {
            "domain": domain,
            "operation": operation,
            "happened_at": happened_at,
            "request_id": request_id,
            "actor_ulid": actor_ulid,
            "target_ulid": target_ulid,
            "changed": changed,
            "refs": refs,
            "correlation_id": correlation_id,
        }

        # Validate minimal requireds
        missing = [
            k
            for k in (
                "domain",
                "operation",
                "request_id",
                "actor_ulid",
                "happened_at",
            )
            if not env.get(k)
        ]
        if missing:
            raise ValueError(
                f"event_bus.emit missing required fields: {missing}"
            )

        result: Optional[str] = None
        for sink in self.sinks():
            try:
                r = sink(env)
                result = result or r
            except Exception:
                # Swallow; logging is fine here if you want.
                pass
        return result


event_bus = EventBus()
register_sink = event_bus.register_sink
emit = event_bus.emit
