# app/slices/ledger/services.py
from __future__ import annotations
import hashlib, json
from typing import Iterable
from sqlalchemy import asc
from app.extensions import db
from app.lib.ids import new_ulid
from app.lib.chrono import utcnow_naive, to_iso8601
from .models import LedgerEvent


def _digest(payload: dict) -> bytes:
    s = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(s).digest()


def log_event(
    ev_type: str,
    *,
    actor_ulid: str | None = None,
    subject_ulid: str | None = None,
    entity_ulid: str | None = None,
    changed_fields: Iterable[str] | None = None,
    meta: dict | None = None,
    chain_key: str | None = None,
    request_id: str | None = None,
) -> str:
    # find previous hash in this chain (or global if chain_key is None)
    q = db.session.query(LedgerEvent)
    q = (
        q.filter_by(chain_key=chain_key)
        if chain_key
        else q.filter(LedgerEvent.chain_key.is_(None))
    )
    prev = q.order_by(
        asc(LedgerEvent.happened_at_utc), asc(LedgerEvent.ulid)
    ).all()[-1:] or [None]
    prev_hash = prev[0].hash if prev[0] is not None else None

    happened = utcnow_naive()
    envelope = {
        "type": ev_type,
        "happened_at_utc": to_iso8601(happened),
        "actor_ulid": actor_ulid,
        "subject_ulid": subject_ulid,
        "entity_ulid": entity_ulid,
        "changed_fields": list(changed_fields) if changed_fields else None,
        "meta": meta or None,
        "request_id": request_id,
        "chain_key": chain_key,
        "prev_hash": prev_hash.hex() if prev_hash else None,
    }
    digest = _digest(envelope)

    row = LedgerEvent(
        ulid=new_ulid(),
        type=ev_type,
        happened_at_utc=happened,
        actor_ulid=actor_ulid,
        subject_ulid=subject_ulid,
        entity_ulid=entity_ulid,
        changed_fields=envelope["changed_fields"],
        meta=envelope["meta"],
        request_id=request_id,
        chain_key=chain_key,
        prev_hash=prev_hash,
        hash=digest,
    )
    db.session.add(row)
    db.session.commit()
    return row.ulid


def verify_chain(chain_key: str | None = None) -> dict:
    q = db.session.query(LedgerEvent)
    q = (
        q.filter_by(chain_key=chain_key)
        if chain_key
        else q.filter(LedgerEvent.chain_key.is_(None))
    )
    rows = q.order_by(
        asc(LedgerEvent.happened_at_utc), asc(LedgerEvent.ulid)
    ).all()
    prev_hash = None
    for r in rows:
        envelope = {
            "type": r.type,
            "happened_at_utc": to_iso8601(r.happened_at_utc),
            "actor_ulid": r.actor_ulid,
            "subject_ulid": r.subject_ulid,
            "entity_ulid": r.entity_ulid,
            "changed_fields": r.changed_fields,
            "meta": r.meta,
            "request_id": r.request_id,
            "chain_key": r.chain_key,
            "prev_hash": prev_hash.hex() if prev_hash else None,
        }
        if _digest(envelope) != r.hash:
            return {"ok": False, "bad_ulid": r.ulid}
        prev_hash = r.hash
    return {"ok": True, "count": len(rows)}
