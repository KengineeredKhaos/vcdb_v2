# app/slices/ledger/services.py
from __future__ import annotations

from typing import Any, Mapping

from flask import current_app
from sqlalchemy import text


def append_event(event: Mapping[str, Any]) -> dict[str, str]:
    """
    Append one ledger event. `event` must already contain:
      id, type, domain, operation, happened_at_utc, request_id,
      actor_id?, target_id?, changed_fields_json, refs_json,
      correlation_id?, prev_event_id?, prev_hash?, event_hash
    Returns {"id": ..., "event_hash": ...}.
    """
    # Map python dict -> table columns (rename if your schema differs)
    sql = text(
        """
        INSERT INTO ledger_event (
            id, type, domain, operation, happened_at_utc, request_id,
            actor_id, target_id, changed_fields_json, refs_json,
            correlation_id, prev_event_id, prev_hash, event_hash
        ) VALUES (
            :id, :type, :domain, :operation, :happened_at_utc, :request_id,
            :actor_id, :target_id, json(:changed_fields_json), json(:refs_json),
            :correlation_id, :prev_event_id, :prev_hash, :event_hash
        )
    """
    )
    # If your DB driver wants plain strings for JSON columns, `json(:x)` works for SQLite with JSON1.
    # Otherwise, use `:changed_fields_json` and pass json.dumps(...) in params.

    # Ensure JSON strings if not using json(:param) above:
    params = dict(event)
    if isinstance(params.get("changed_fields_json"), (dict, list)):
        import json

        params["changed_fields_json"] = json.dumps(
            params["changed_fields_json"]
        )
    if isinstance(params.get("refs_json"), (dict, list)):
        import json

        params["refs_json"] = json.dumps(params["refs_json"])

    with current_app.app_context():
        db.session.execute(sql, params)
        db.session.commit()

    return {"id": str(event["id"]), "event_hash": str(event["event_hash"])}
