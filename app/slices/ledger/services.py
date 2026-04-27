# app/slices/ledger/services.py
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: app/slices/ledger/services.py
# Purpose: Single source of truth for audit/ledger write-path.
# Canon API: ledger-core v2.1.0
# Ethos: skinny routes, fat services, ULID, ISO timestamps, no PII
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.lib.jsonutil import dumps_compact, try_parse_json

from .errors import (
    EventHashConflict,
    LedgerBadArgument,
    LedgerBackupGateBlocked,
    LedgerError,
    LedgerUnavailable,
    ProviderTemporarilyDown,
)
from .models import (
    LedgerEvent,
    LedgerHashchainCheck,
    LedgerHashchainRepair,
)

# -*- coding: utf-8 -*-
# VCDB Canon — DO NOT MODIFY WITHOUT GOVERNANCE APPROVAL
CANON_API = "ledger-core"
CANON_VERSION = "2.1.0"

MAX_APPEND_RETRIES = 5

REASON_ANOMALY_HASHCHAIN = "anomaly_ledger_hashchain"
REASON_FAILURE_HASHCHAIN = "failure_ledger_hashchain"
REASON_ADVISORY_HASHCHAIN = "advisory_ledger_hashchain"
REASON_ADVISORY_CRON_LEDGERCHECK = "advisory_cron_ledgercheck"
REASON_FAILURE_CRON_LEDGERCHECK = "failure_cron_ledgercheck"

STATUS_CLEAN = "clean"
STATUS_ANOMALY = "anomaly"
STATUS_FAILURE = "failure"
STATUS_RECONCILED = "reconciled"

CHECK_KIND_VERIFY = "verify"
CHECK_KIND_DAILY_CLOSE = "daily_close"
CHECK_KIND_CRON_LEDGERCHECK = "cron_ledgercheck"
CHECK_KIND_POST_REPAIR = "post_repair"


def _clean_required_str(
    label: str,
    value: str,
    *,
    max_len: int | None = None,
) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise LedgerBadArgument(f"{label} must be non-empty")
    if max_len is not None and len(clean) > max_len:
        raise LedgerBadArgument(f"{label} exceeds max length {max_len}")
    return clean


def _clean_optional_str(
    label: str,
    value: str | None,
    *,
    max_len: int | None = None,
) -> str | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    if max_len is not None and len(clean) > max_len:
        raise LedgerBadArgument(f"{label} exceeds max length {max_len}")
    return clean


def _json_safe(obj: Any) -> Any:
    """Recursively coerce to JSON-safe primitives."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.hex()
    if isinstance(obj, Mapping):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    return str(obj)


def _canon_envelope(
    *,
    domain: str,
    operation: str,
    request_id: str,
    actor_ulid: str | None,
    target_ulid: str | None,
    refs: dict[str, Any] | None,
    changed: dict[str, Any] | None,
    meta: dict[str, Any] | None,
    happened_at_utc: str | None = None,
    chain_key: str | None = None,
) -> dict[str, Any]:
    """Build a stable, minimal, string-serialized envelope for hashing."""
    clean_domain = _clean_required_str("domain", domain, max_len=40)
    clean_operation = _clean_required_str(
        "operation",
        operation,
        max_len=60,
    )
    clean_request_id = _clean_required_str(
        "request_id",
        request_id,
        max_len=64,
    )
    clean_chain_key = (
        _clean_optional_str(
            "chain_key",
            chain_key,
            max_len=40,
        )
        or clean_domain
    )

    event_type = f"{clean_domain}.{clean_operation}"
    if len(event_type) > 120:
        raise LedgerBadArgument("event_type exceeds max length 120")

    return {
        "chain_key": clean_chain_key,
        "event_type": event_type,
        "domain": clean_domain,
        "operation": clean_operation,
        "request_id": clean_request_id,
        "actor_ulid": _clean_optional_str(
            "actor_ulid",
            actor_ulid,
            max_len=64,
        ),
        "target_ulid": _clean_optional_str(
            "target_ulid",
            target_ulid,
            max_len=64,
        ),
        "happened_at_utc": happened_at_utc or now_iso8601_ms(),
        "refs": _json_safe(refs) if refs is not None else None,
        "changed": _json_safe(changed) if changed is not None else None,
        "meta": _json_safe(meta) if meta is not None else None,
    }


def _hash_env(prev_hash_hex: str | None, env: dict[str, Any]) -> str:
    """SHA-256 over prev-hash + compact JSON of envelope core fields."""
    h = hashlib.sha256()
    if prev_hash_hex:
        h.update(prev_hash_hex.encode("utf-8"))
    h.update(dumps_compact(env).encode("utf-8"))
    return h.hexdigest()


def _event_to_env(ev: LedgerEvent) -> dict[str, Any]:
    """Rebuild the canonical event envelope from a stored row."""
    return {
        "chain_key": ev.chain_key,
        "event_type": ev.event_type,
        "domain": ev.domain,
        "operation": ev.operation,
        "request_id": ev.request_id,
        "actor_ulid": ev.actor_ulid,
        "target_ulid": ev.target_ulid,
        "happened_at_utc": ev.happened_at_utc,
        "refs": try_parse_json(ev.refs_json),
        "changed": try_parse_json(ev.changed_json),
        "meta": try_parse_json(ev.meta_json),
    }


def _extract_idempotency_key(env: dict[str, Any]) -> str | None:
    """
    Pull an explicit replay key from meta/refs.

    Ledger does not guess based only on request_id + event_type because one
    request may legitimately emit more than one event of the same type.
    """
    for bucket_name in ("meta", "refs"):
        bucket = env.get(bucket_name)
        if not isinstance(bucket, Mapping):
            continue
        for key_name in ("idempotency_key", "source_action_ulid"):
            value = bucket.get(key_name)
            clean = str(value or "").strip()
            if clean:
                return clean[:128]
    return None


def _logical_payload_hash(env: dict[str, Any]) -> str:
    """
    Hash the logical event payload for idempotent replay comparison.

    happened_at_utc is intentionally excluded. A replay attempt may happen at
    a different clock time while still representing the same logical write.
    """
    logical = dict(env)
    logical.pop("happened_at_utc", None)
    payload = json.dumps(
        logical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _find_idempotent_event(
    *,
    env: dict[str, Any],
    idempotency_key: str,
) -> LedgerEvent | None:
    """Find a prior event with the same explicit idempotency key."""
    stmt = (
        select(LedgerEvent)
        .where(
            LedgerEvent.chain_key == env["chain_key"],
            LedgerEvent.event_type == env["event_type"],
            LedgerEvent.request_id == env["request_id"],
        )
        .order_by(LedgerEvent.chain_seq, LedgerEvent.ulid)
    )
    if env.get("target_ulid"):
        stmt = stmt.where(LedgerEvent.target_ulid == env["target_ulid"])

    for row in db.session.execute(stmt).scalars():
        old_env = _event_to_env(row)
        if _extract_idempotency_key(old_env) == idempotency_key:
            return row
    return None


def _handle_idempotent_replay(env: dict[str, Any]) -> LedgerEvent | None:
    """
    Accept exact logical replays and reject conflicting replays.

    Return an existing event when the replay is safe. Return None when no
    prior matching idempotency key exists.
    """
    idempotency_key = _extract_idempotency_key(env)
    if not idempotency_key:
        return None

    existing = _find_idempotent_event(
        env=env,
        idempotency_key=idempotency_key,
    )
    if existing is None:
        return None

    attempted_hash = _logical_payload_hash(env)
    existing_hash = _logical_payload_hash(_event_to_env(existing))
    if attempted_hash == existing_hash:
        return existing

    raise EventHashConflict(
        "idempotency key replay conflicts with existing ledger event; "
        f"event_ulid={existing.ulid} chain_key={existing.chain_key}"
    )


def _is_transient_provider_error(exc: SQLAlchemyError) -> bool:
    """Best-effort classification for retryable provider conditions."""
    if isinstance(exc, OperationalError):
        return True
    text = str(exc).lower()
    transient_markers = (
        "database is locked",
        "database table is locked",
        "connection reset",
        "connection refused",
        "connection timed out",
        "server closed the connection",
        "temporarily unavailable",
        "timeout",
    )
    return any(marker in text for marker in transient_markers)


def _raise_provider_error(*, during: str, exc: SQLAlchemyError) -> None:
    message = f"ledger provider unavailable during {during}"
    if _is_transient_provider_error(exc):
        raise ProviderTemporarilyDown(message) from exc
    raise LedgerUnavailable(message) from exc


def _chain_head(chain_key: str) -> LedgerEvent | None:
    stmt = (
        select(LedgerEvent)
        .where(LedgerEvent.chain_key == chain_key)
        .order_by(desc(LedgerEvent.chain_seq), desc(LedgerEvent.ulid))
        .limit(1)
    )
    return db.session.execute(stmt).scalar_one_or_none()


def _make_event_row(
    *,
    env: dict[str, Any],
    prev_hash_hex: str | None,
    chain_seq: int,
) -> LedgerEvent:
    return LedgerEvent(
        ulid=new_ulid(),
        chain_key=env["chain_key"],
        chain_seq=chain_seq,
        domain=env["domain"],
        operation=env["operation"],
        event_type=env["event_type"],
        actor_ulid=env["actor_ulid"],
        target_ulid=env["target_ulid"],
        request_id=env["request_id"],
        happened_at_utc=env["happened_at_utc"],
        refs_json=(
            dumps_compact(env["refs"])
            if env["refs"] is not None
            else None
        ),
        changed_json=(
            dumps_compact(env["changed"])
            if env["changed"] is not None
            else None
        ),
        meta_json=(
            dumps_compact(env["meta"])
            if env["meta"] is not None
            else None
        ),
        prev_hash_hex=prev_hash_hex,
        curr_hash_hex=_hash_env(prev_hash_hex, env),
        created_at_utc=now_iso8601_ms(),
    )


def append_event(
    *,
    domain: str,
    operation: str,
    request_id: str,
    actor_ulid: str | None,
    target_ulid: str | None,
    refs: dict[str, Any] | None = None,
    changed: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    happened_at_utc: str | None = None,
    chain_key: str | None = None,
) -> LedgerEvent:
    """
    Append a ledger event. Callers are slice services or the event bus.

    This unit only flushes; caller commits. Ordinary same-chain append races
    are retried inside Ledger. If retry succeeds, the caller never knows.
    """
    env = _canon_envelope(
        domain=domain,
        operation=operation,
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=target_ulid,
        refs=refs,
        changed=changed,
        meta=meta,
        happened_at_utc=happened_at_utc,
        chain_key=chain_key,
    )

    try:
        replay = _handle_idempotent_replay(env)
        if replay is not None:
            return replay
    except (EventHashConflict, LedgerBadArgument):
        raise
    except SQLAlchemyError as exc:
        _raise_provider_error(during="idempotency lookup", exc=exc)

    last_integrity_error: IntegrityError | None = None
    for attempt in range(1, MAX_APPEND_RETRIES + 1):
        nested = db.session.begin_nested()
        try:
            head = _chain_head(env["chain_key"])
            prev_hash_hex = head.curr_hash_hex if head else None
            chain_seq = int(head.chain_seq or 0) + 1 if head else 1
            row = _make_event_row(
                env=env,
                prev_hash_hex=prev_hash_hex,
                chain_seq=chain_seq,
            )
            db.session.add(row)
            db.session.flush()
            nested.commit()
            return row
        except IntegrityError as exc:
            nested.rollback()
            last_integrity_error = exc
            if attempt >= MAX_APPEND_RETRIES:
                raise EventHashConflict(
                    "ledger append collision could not be resolved after "
                    f"{MAX_APPEND_RETRIES} retries; "
                    f"chain_key={env['chain_key']}"
                ) from exc
        except SQLAlchemyError as exc:
            nested.rollback()
            _raise_provider_error(during="append", exc=exc)

    raise EventHashConflict(
        "ledger append collision could not be resolved; "
        f"chain_key={env['chain_key']}"
    ) from last_integrity_error


def _event_public(ev: LedgerEvent) -> dict[str, Any]:
    return {
        "event_ulid": ev.ulid,
        "chain_key": ev.chain_key,
        "chain_seq": ev.chain_seq,
        "prev_hash_hex": ev.prev_hash_hex,
        "curr_hash_hex": ev.curr_hash_hex,
        "event_type": ev.event_type,
        "request_id": ev.request_id,
    }


def _iter_events(key: str | None) -> Iterable[LedgerEvent]:
    q = select(LedgerEvent).order_by(
        LedgerEvent.chain_key,
        LedgerEvent.chain_seq,
        LedgerEvent.ulid,
    )
    if key:
        q = (
            select(LedgerEvent)
            .where(LedgerEvent.chain_key == key)
            .order_by(LedgerEvent.chain_seq, LedgerEvent.ulid)
        )
    return (x[0] for x in db.session.execute(q).all())


def verify_chain(chain_key: str | None = None) -> dict[str, Any]:
    """
    Recompute hashes for one chain or all chains.

    Anomalies are survivable sequence problems. Failures are conditions that
    make Ledger unable to claim current hash-chain integrity.
    """
    clean_chain_key = _clean_optional_str(
        "chain_key",
        chain_key,
        max_len=40,
    )

    try:
        checked = 0
        chains: set[str] = set()
        anomalies: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        prev_for: dict[str, str | None] = {}
        prev_seq_for: dict[str, int] = {}
        prev_hash_claims: dict[tuple[str, str], list[str]] = {}

        for ev in _iter_events(clean_chain_key):
            chains.add(ev.chain_key)
            expected_prev = prev_for.get(ev.chain_key)
            expected_seq = prev_seq_for.get(ev.chain_key, 0) + 1
            stored_prev_key = ev.prev_hash_hex or "<genesis>"
            prev_hash_claims.setdefault(
                (ev.chain_key, stored_prev_key), []
            ).append(ev.ulid)

            if ev.chain_seq != expected_seq:
                anomalies.append(
                    {
                        "kind": "sequence_gap_or_disorder",
                        "chain_key": ev.chain_key,
                        "event_ulid": ev.ulid,
                        "expected_chain_seq": expected_seq,
                        "observed_chain_seq": ev.chain_seq,
                    }
                )

            if ev.prev_hash_hex != expected_prev:
                anomalies.append(
                    {
                        "kind": "prev_hash_sequence_mismatch",
                        "chain_key": ev.chain_key,
                        "event_ulid": ev.ulid,
                        "chain_seq": ev.chain_seq,
                        "expected_prev_hash": expected_prev,
                        "observed_prev_hash": ev.prev_hash_hex,
                    }
                )

            env = _event_to_env(ev)
            calc_against_stored_prev = _hash_env(ev.prev_hash_hex, env)
            if calc_against_stored_prev != ev.curr_hash_hex:
                failures.append(
                    {
                        "kind": "curr_hash_mismatch",
                        "chain_key": ev.chain_key,
                        "event_ulid": ev.ulid,
                        "chain_seq": ev.chain_seq,
                        "expected_curr_hash": ev.curr_hash_hex,
                        "recomputed_curr_hash": calc_against_stored_prev,
                    }
                )

            prev_for[ev.chain_key] = ev.curr_hash_hex
            prev_seq_for[ev.chain_key] = ev.chain_seq
            checked += 1

        for (claim_chain, claim_prev), event_ulids in prev_hash_claims.items():
            if len(event_ulids) <= 1:
                continue
            anomalies.append(
                {
                    "kind": "hashchain_fork",
                    "chain_key": claim_chain,
                    "claimed_prev_hash": None
                    if claim_prev == "<genesis>"
                    else claim_prev,
                    "event_ulids": event_ulids,
                }
            )

        ok = not anomalies and not failures
        broken = None
        if failures:
            broken = failures[0]
        elif anomalies:
            broken = anomalies[0]

        return {
            "ok": ok,
            "status": _status_for_verify(
                anomaly_count=len(anomalies),
                failure_count=len(failures),
            ),
            "checked": checked,
            "broken": broken,
            "anomalies": anomalies,
            "failures": failures,
            "chains": sorted(chains),
            "as_of_utc": now_iso8601_ms(),
        }
    except LedgerBadArgument:
        raise
    except SQLAlchemyError as exc:
        _raise_provider_error(during="verify", exc=exc)


def _status_for_verify(*, anomaly_count: int, failure_count: int) -> str:
    if failure_count:
        return STATUS_FAILURE
    if anomaly_count:
        return STATUS_ANOMALY
    return STATUS_CLEAN


def _reason_for_verify_result(result: dict[str, Any], check_kind: str) -> str:
    if result.get("failures"):
        if check_kind == CHECK_KIND_CRON_LEDGERCHECK:
            return REASON_FAILURE_CRON_LEDGERCHECK
        return REASON_FAILURE_HASHCHAIN
    if result.get("anomalies"):
        return REASON_ANOMALY_HASHCHAIN
    if check_kind == CHECK_KIND_CRON_LEDGERCHECK:
        return REASON_ADVISORY_CRON_LEDGERCHECK
    return REASON_ADVISORY_HASHCHAIN


def record_hashchain_check(
    *,
    check_kind: str,
    result: dict[str, Any],
    request_id: str,
    actor_ulid: str | None,
    chain_key: str | None,
    started_at_utc: str | None = None,
) -> LedgerHashchainCheck:
    """Persist verify/daily-close evidence for Auditor drill-down."""
    started = started_at_utc or result.get("as_of_utc") or now_iso8601_ms()
    completed = now_iso8601_ms()
    reason_code = _reason_for_verify_result(result, check_kind)
    source_status = str(result.get("status") or STATUS_FAILURE)
    anomaly_count = len(result.get("anomalies") or [])
    failure_count = len(result.get("failures") or [])
    ok = bool(result.get("ok"))

    row = LedgerHashchainCheck(
        check_kind=check_kind,
        reason_code=reason_code,
        source_status=source_status,
        request_id=request_id,
        actor_ulid=actor_ulid,
        chain_key=chain_key,
        started_at_utc=started,
        completed_at_utc=completed,
        ok=ok,
        checked_count=int(result.get("checked") or 0),
        anomaly_count=anomaly_count,
        failure_count=failure_count,
        routine_backup_allowed=ok,
        dirty_forensic_backup_only=not ok,
        details_json=dict(result),
    )
    db.session.add(row)
    db.session.flush()
    return row


def _record_failed_check(
    *,
    check_kind: str,
    request_id: str,
    actor_ulid: str | None,
    chain_key: str | None,
    started_at_utc: str,
    exc: BaseException,
) -> LedgerHashchainCheck:
    """
    Persist a failed daily-close/cron check when verification itself fails.

    This is best effort. If the provider is down hard enough that this row
    cannot be written, the caller still gets the original visible failure.
    """
    now = now_iso8601_ms()
    reason = (
        REASON_FAILURE_CRON_LEDGERCHECK
        if check_kind == CHECK_KIND_CRON_LEDGERCHECK
        else REASON_FAILURE_HASHCHAIN
    )
    row = LedgerHashchainCheck(
        check_kind=check_kind,
        reason_code=reason,
        source_status=STATUS_FAILURE,
        request_id=request_id,
        actor_ulid=actor_ulid,
        chain_key=chain_key,
        started_at_utc=started_at_utc,
        completed_at_utc=now,
        ok=False,
        checked_count=0,
        anomaly_count=0,
        failure_count=1,
        routine_backup_allowed=False,
        dirty_forensic_backup_only=True,
        details_json={
            "ok": False,
            "status": STATUS_FAILURE,
            "checked": 0,
            "broken": {
                "kind": "ledger_check_exception",
                "error_class": exc.__class__.__name__,
            },
            "anomalies": [],
            "failures": [
                {
                    "kind": "ledger_check_exception",
                    "error_class": exc.__class__.__name__,
                }
            ],
            "chains": [chain_key] if chain_key else [],
            "as_of_utc": now,
        },
    )
    db.session.add(row)
    db.session.flush()
    return row


def run_daily_close(
    *,
    request_id: str,
    actor_ulid: str | None,
    chain_key: str | None = None,
    check_kind: str = CHECK_KIND_DAILY_CLOSE,
    alert_on_advisory: bool = False,
) -> dict[str, Any]:
    """
    Verify Ledger before routine backup/archive.

    Clean/reconciled checks allow routine backup. Anomaly/failure checks block
    routine backup and allow dirty forensic backup only. Clean advisory checks
    are recorded as evidence; they do not create Admin Inbox items.

    ``alert_on_advisory`` is retained for call-site compatibility. Ledger no
    longer uses it to create clean-check Admin alerts.
    """
    started = now_iso8601_ms()
    try:
        result = verify_chain(chain_key=chain_key)
        check = record_hashchain_check(
            check_kind=check_kind,
            result=result,
            request_id=request_id,
            actor_ulid=actor_ulid,
            chain_key=chain_key,
            started_at_utc=started,
        )
    except LedgerError as exc:
        check = _record_failed_check(
            check_kind=check_kind,
            request_id=request_id,
            actor_ulid=actor_ulid,
            chain_key=chain_key,
            started_at_utc=started,
            exc=exc,
        )
        result = dict(check.details_json or {})

    # Admin Inbox is for attention/action, not proof that routine work
    # succeeded. Clean/advisory checks are evidence rows only, but they may
    # close an existing Ledger-owned issue if the latest check proves clean.
    # Anomaly/failure checks create or refresh Ledger-owned issue truth and
    # cue Admin through admin_alert.
    from . import admin_issue_services as issues

    issues.sync_hashchain_issue_from_check(
        check=check,
        result=result,
        actor_ulid=actor_ulid,
    )

    return {
        "ok": bool(check.ok),
        "status": check.source_status,
        "reason_code": check.reason_code,
        "check_ulid": check.ulid,
        "routine_backup_allowed": bool(check.routine_backup_allowed),
        "dirty_forensic_backup_only": bool(check.dirty_forensic_backup_only),
        "checked": check.checked_count,
        "anomaly_count": check.anomaly_count,
        "failure_count": check.failure_count,
        "details": result,
    }


def _chain_events(chain_key: str) -> list[LedgerEvent]:
    """Return one chain in canonical sequence order."""
    clean_chain_key = _clean_required_str(
        "chain_key",
        chain_key,
        max_len=40,
    )
    stmt = (
        select(LedgerEvent)
        .where(LedgerEvent.chain_key == clean_chain_key)
        .order_by(LedgerEvent.chain_seq, LedgerEvent.ulid)
    )
    return list(db.session.execute(stmt).scalars())


def _chain_snapshot(events: Iterable[LedgerEvent]) -> list[dict[str, Any]]:
    """Capture PII-free hash-chain evidence for repair records."""
    return [_event_public(ev) for ev in events]


def repair_hashchain(
    *,
    chain_key: str,
    actor_ulid: str | None,
    request_id: str,
    issue_ulid: str | None = None,
    check_ulid: str | None = None,
) -> dict[str, Any]:
    """
    Recompute one chain's prev/curr hashes in chain_seq order.

    This is Ledger-owned repair, not hidden cleanup. Event rows remain in
    place. The repair records before/after evidence in LedgerHashchainRepair
    so Admin and Auditor can see exactly what was touched.
    """
    clean_chain_key = _clean_required_str(
        "chain_key",
        chain_key,
        max_len=40,
    )
    rid = _clean_required_str("request_id", request_id, max_len=64)
    started = now_iso8601_ms()

    try:
        before_verify = verify_chain(chain_key=clean_chain_key)
        events = _chain_events(clean_chain_key)
        if not events:
            raise LedgerBadArgument(
                f"no ledger events found for chain_key={clean_chain_key}"
            )

        before_rows = _chain_snapshot(events)
        affected: list[str] = []
        prev_hash_hex: str | None = None

        for ev in events:
            env = _event_to_env(ev)
            repaired_hash = _hash_env(prev_hash_hex, env)
            if (
                ev.prev_hash_hex != prev_hash_hex
                or ev.curr_hash_hex != repaired_hash
            ):
                affected.append(ev.ulid)

            ev.prev_hash_hex = prev_hash_hex
            ev.curr_hash_hex = repaired_hash
            ev.updated_at_utc = now_iso8601_ms()
            prev_hash_hex = repaired_hash

        db.session.flush()

        after_events = _chain_events(clean_chain_key)
        after_rows = _chain_snapshot(after_events)
        after_verify = verify_chain(chain_key=clean_chain_key)
        completed = now_iso8601_ms()

        post_repair_check = record_hashchain_check(
            check_kind=CHECK_KIND_POST_REPAIR,
            result=after_verify,
            request_id=rid,
            actor_ulid=actor_ulid,
            chain_key=clean_chain_key,
            started_at_utc=completed,
        )

        repair = LedgerHashchainRepair(
            repair_kind="recompute_hashchain",
            reason_code=(
                REASON_ADVISORY_HASHCHAIN
                if after_verify.get("ok")
                else REASON_FAILURE_HASHCHAIN
            ),
            source_status=(
                STATUS_RECONCILED
                if after_verify.get("ok")
                else STATUS_FAILURE
            ),
            request_id=rid,
            actor_ulid=actor_ulid,
            issue_ulid=issue_ulid,
            check_ulid=post_repair_check.ulid,
            chain_key=clean_chain_key,
            started_at_utc=started,
            completed_at_utc=completed,
            before_json={
                "verify": before_verify,
                "events": before_rows,
            },
            after_json={
                "verify": after_verify,
                "events": after_rows,
                "post_repair_check_ulid": post_repair_check.ulid,
            },
            affected_event_ulids_json=affected,
            summary=(
                "Recomputed Ledger hash-chain in chain_seq order for "
                f"chain_key={clean_chain_key}."
            ),
        )
        db.session.add(repair)
        db.session.flush()

        return {
            "ok": bool(after_verify.get("ok")),
            "repair_ulid": repair.ulid,
            "repair_kind": repair.repair_kind,
            "reason_code": repair.reason_code,
            "source_status": repair.source_status,
            "chain_key": clean_chain_key,
            "issue_ulid": issue_ulid,
            "check_ulid": check_ulid,
            "post_repair_check_ulid": post_repair_check.ulid,
            "affected_event_ulids": affected,
            "before": before_verify,
            "after": after_verify,
            "routine_backup_allowed": bool(after_verify.get("ok")),
            "dirty_forensic_backup_only": not bool(after_verify.get("ok")),
        }
    except LedgerBadArgument:
        raise
    except SQLAlchemyError as exc:
        _raise_provider_error(during="hashchain repair", exc=exc)


def latest_daily_close_status(
    *,
    chain_key: str | None = None,
) -> dict[str, Any]:
    """Return the most recent backup-gating check status.

    Daily close and cron checks can open or block the gate. A successful
    post-repair verification can reopen the gate immediately because repair
    means Ledger is ready for action, not merely waiting for the next close.
    """
    clean_chain_key = _clean_optional_str(
        "chain_key",
        chain_key,
        max_len=40,
    )
    stmt = (
        select(LedgerHashchainCheck)
        .where(
            LedgerHashchainCheck.check_kind.in_(
                [
                    CHECK_KIND_DAILY_CLOSE,
                    CHECK_KIND_CRON_LEDGERCHECK,
                    CHECK_KIND_POST_REPAIR,
                ]
            )
        )
        .order_by(desc(LedgerHashchainCheck.created_at_utc))
        .limit(1)
    )
    if clean_chain_key is not None:
        stmt = stmt.where(LedgerHashchainCheck.chain_key == clean_chain_key)

    row = db.session.execute(stmt).scalar_one_or_none()
    if row is None:
        return {
            "has_daily_close": False,
            "routine_backup_allowed": False,
            "dirty_forensic_backup_only": True,
            "reason": "no_daily_close_recorded",
            "chain_key": clean_chain_key,
        }
    return {
        "has_daily_close": True,
        "check_ulid": row.ulid,
        "reason_code": row.reason_code,
        "source_status": row.source_status,
        "ok": bool(row.ok),
        "routine_backup_allowed": bool(row.routine_backup_allowed),
        "dirty_forensic_backup_only": bool(row.dirty_forensic_backup_only),
        "completed_at_utc": row.completed_at_utc,
        "chain_key": row.chain_key,
    }


def backup_gate_status(*, chain_key: str | None = None) -> dict[str, Any]:
    """
    Public Ledger-owned backup gate status.

    Routine backup/archive callers should consult this before making an
    archive-of-record. Dirty forensic backup remains a separate explicit path.
    """
    status = latest_daily_close_status(chain_key=chain_key)
    status["gate"] = (
        "routine_backup_allowed"
        if status.get("routine_backup_allowed")
        else "routine_backup_blocked"
    )
    return status


def require_routine_backup_allowed(
    *,
    chain_key: str | None = None,
) -> dict[str, Any]:
    """
    Fail closed for routine backup/archive when daily close is not clean.

    Backup/archive code should call this before routine archive-of-record. If
    it raises, the caller may still take an explicitly named dirty forensic
    snapshot, but it must not certify the backup as routine/verified.
    """
    status = backup_gate_status(chain_key=chain_key)
    if status.get("routine_backup_allowed"):
        return status
    raise LedgerBackupGateBlocked(
        "routine backup/archive blocked by Ledger daily-close status: "
        f"{status.get('reason_code') or status.get('reason')}"
    )
