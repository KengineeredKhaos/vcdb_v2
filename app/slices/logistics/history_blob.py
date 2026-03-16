# app/slices/logistics/history_blob.py

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.lib.chrono import now_iso8601_ms

"""
Deployment Notes:

blob = build_customer_history_blob(
    schema_name="logistics.issuance_summary",
    schema_version=1,
    title="Issued hygiene kit",
    summary="Issued hygiene kit; cadence ok.",
    source_slice="logistics",
    public_tags=["issuance", "hygiene"],
    admin_tags=["high_frequency_requests"],  # silent
    source_ref_ulid=issue_ulid,
    created_by_actor_ulid=actor_ulid,
    payload={
        "sku": sku,
        "qty": 1,
        "cadence_window_days": 30,
    },
)

customers_v1.append_history_entry(
    target_entity_ulid=entity_ulid,
    kind="issuance_summary",
    blob_json=blob,
    actor_ulid=actor_ulid,
    request_id=request_id,
)
"""

_ULID_RE = "^[0-9A-HJKMNP-TV-Z]{26}$"


def _uniq_tags(tags: Iterable[str] | None) -> list[str]:
    if not tags:
        return []
    uniq = sorted({t.strip() for t in tags if t and t.strip()})
    return uniq


def build_customer_history_blob(
    *,
    schema_name: str,
    schema_version: int,
    title: str,
    summary: str,
    source_slice: str,
    happened_at_iso: str | None = None,
    severity: str = "info",  # "info" | "warn"
    public_tags: Sequence[str] | None = None,
    admin_tags: Sequence[str] | None = None,
    dedupe_key: str | None = None,
    source_ref_ulid: str | None = None,
    created_by_actor_ulid: str | None = None,
    refs: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Producer-side envelope constructor for CustomerHistory.data_json.

    - Builds the canonical envelope+payload shape.
    - Does NOT validate against schema (Customers will validate on write).
    - Keep in sync with:
        app/slices/customers/data/schemas/customer_history_blob.schema.json
    """
    if payload is None:
        payload = {}

    blob: dict[str, Any] = {
        "envelope": {
            "schema_name": schema_name,
            "schema_version": int(schema_version),
            "title": title,
            "summary": summary,
            "severity": severity,
            "happened_at": happened_at_iso or now_iso8601_ms(),
            "source_slice": source_slice,
            "public_tags": _uniq_tags(public_tags),
            "admin_tags": _uniq_tags(admin_tags),
        },
        "payload": dict(payload),
    }

    env = blob["envelope"]

    if dedupe_key:
        env["dedupe_key"] = dedupe_key
    if source_ref_ulid:
        env["source_ref_ulid"] = source_ref_ulid
    if created_by_actor_ulid:
        env["created_by_actor_ulid"] = created_by_actor_ulid
    if refs:
        env["refs"] = dict(refs)

    return blob
