# app/slices/attachments/services.py
from __future__ import annotations

import hashlib
import os
from typing import Optional, BinaryIO, Tuple

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from .models import Attachment, AttachmentLink

# ---- Storage abstraction ----------------------------------------------------


class StorageBackend:
    """Very small interface you can swap with S3/MinIO later."""

    def __init__(self, root: str):
        self.root = root

    def put(self, storage_key: str, src: BinaryIO) -> None:
        path = os.path.join(self.root, storage_key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                f.write(chunk)

    def exists(self, storage_key: str) -> bool:
        return os.path.exists(os.path.join(self.root, storage_key))

    def sign_url(self, storage_key: str, *, ttl_seconds: int = 300) -> str:
        # Dev stub: file:// path. Replace with real signed URL for S3/MinIO.
        return f"file://{os.path.join(self.root, storage_key)}"


def get_backend() -> StorageBackend:
    # Use app.config if available; default to var/data/attachments
    root = os.getenv("ATTACHMENTS_ROOT", "var/data/attachments")
    return StorageBackend(root=root)


# ---- Helpers ----------------------------------------------------------------


def _ensure_reqid(rid: Optional[str]) -> str:
    if not rid or not str(rid).strip():
        raise ValueError("request_id must be non-empty")
    return str(rid)


def _sha256_and_len(stream: BinaryIO) -> Tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        total += len(chunk)
        h.update(chunk)
    return h.hexdigest(), total


def _ext_from_filename(name: Optional[str]) -> str:
    if not name:
        return ""
    _, ext = os.path.splitext(name)
    return ext.lower().lstrip(".")


def _storage_key_for(sha256: str, ext: str) -> str:
    a, b = sha256[:2], sha256[2:4]
    suffix = f".{ext}" if ext else ""
    return f"sha256/{a}/{b}/{sha256}{suffix}"


# ---- Core API ----------------------------------------------------------------


def upload_register(
    *,
    file_stream: BinaryIO,
    mime: str,
    original_filename: Optional[str],
    privacy_level: str = "A",
    retention_policy_code: Optional[str] = None,
    request_id: str,
    actor_ulid: Optional[str],
) -> str:
    """
    Register (and store) a blob. Content-addressed, deduped by sha256.
    Returns attachment_ulid.
    """
    _ensure_reqid(request_id)

    # 1) hash and size (we must re-open or buffer for storage)
    # For simplicity, read once into memory in MVP; for large files, use tee temp file.
    data = file_stream.read()
    sha256 = hashlib.sha256(data).hexdigest()
    size = len(data)

    # 2) build storage key
    ext = _ext_from_filename(original_filename)
    storage_key = _storage_key_for(sha256, ext)

    # 3) upsert metadata (dedupe on sha256)
    att = db.session.query(Attachment).filter_by(sha256=sha256).first()
    if not att:
        att = Attachment(
            sha256=sha256,
            size_bytes=size,
            mime=mime,
            original_filename=original_filename or None,
            storage_key=storage_key,
            privacy_level=(privacy_level or "A"),
            retention_policy_code=retention_policy_code or None,
            status="active",
            created_by_actor=actor_ulid,
        )
        db.session.add(att)
        db.session.commit()

        # 4) store blob if not present
        backend = get_backend()
        if not backend.exists(storage_key):
            backend.put(storage_key, src=BinaryIOAdapter(data))
        event_bus.emit(
            type="attachment.uploaded",
            slice="attachments",
            operation="insert",
            actor_ulid=actor_ulid,
            target_ulid=att.ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"sha256": sha256, "mime": mime, "size_bytes": size},
        )
    return att.ulid


class BinaryIOAdapter:
    """Tiny adapter to provide .read() over bytes for backend.put() usage."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = len(self._data) - self._pos
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk


def link_attachment(
    *,
    attachment_ulid: str,
    slice_name: str,
    domain: str,
    target_ulid: str,
    note: Optional[str],
    request_id: str,
    actor_ulid: Optional[str],
) -> str:
    """
    Link an existing attachment to a domain object.
    """
    _ensure_reqid(request_id)
    att = db.session.get(Attachment, attachment_ulid)
    if not att:
        raise ValueError("attachment not found")

    # ensure no active duplicate
    exists = (
        db.session.query(AttachmentLink)
        .filter_by(
            attachment_ulid=attachment_ulid,
            slice=slice_name,
            domain=domain,
            target_ulid=target_ulid,
            archived_at_utc=None,
        )
        .first()
    )
    if exists:
        return exists.ulid

    link = AttachmentLink(
        attachment_ulid=attachment_ulid,
        slice=slice_name,
        domain=domain,
        target_ulid=target_ulid,
        note=(note or None)[:120] if note else None,
        created_by_actor=actor_ulid,
    )
    db.session.add(link)
    db.session.commit()

    event_bus.emit(
        type="attachment.linked",
        slice="attachments",
        operation="link",
        actor_ulid=actor_ulid,
        target_ulid=link.ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={
            "attachment_ulid": attachment_ulid,
            "slice": slice_name,
            "domain": domain,
            "target_ulid": target_ulid,
        },
    )
    return link.ulid


def unlink_attachment(
    *,
    link_ulid: str,
    request_id: str,
    actor_ulid: Optional[str],
) -> None:
    """Archive the link (do not delete blob)."""
    _ensure_reqid(request_id)
    link = db.session.get(AttachmentLink, link_ulid)
    if not link or link.archived_at_utc:
        return
    link.archived_at_utc = now_iso8601_ms()
    link.archived_by_actor = actor_ulid
    db.session.commit()

    event_bus.emit(
        type="attachment.unlinked",
        slice="attachments",
        operation="unlink",
        actor_ulid=actor_ulid,
        target_ulid=link.ulid,
        request_id=request_id,
        happened_at_utc=link.archived_at_utc,
        refs={
            "attachment_ulid": link.attachment_ulid,
            "slice": link.slice,
            "domain": link.domain,
            "target_ulid": link.target_ulid,
        },
    )


def sign_url(
    *,
    attachment_ulid: str,
    ttl_seconds: int = 300,
    request_id: str,
    actor_ulid: Optional[str],
) -> str:
    """
    Produce a short-lived URL to access the blob. In dev, returns file:// path.
    """
    _ensure_reqid(request_id)
    att = db.session.get(Attachment, attachment_ulid)
    if not att:
        raise ValueError("attachment not found")
    url = get_backend().sign_url(att.storage_key, ttl_seconds=ttl_seconds)
    event_bus.emit(
        type="attachment.url.signed",
        slice="attachments",
        operation="sign",
        actor_ulid=actor_ulid,
        target_ulid=attachment_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"ttl_seconds": ttl_seconds},
    )
    return url
