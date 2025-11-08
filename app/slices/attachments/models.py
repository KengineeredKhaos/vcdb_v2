# app/slices/attachments/models.py
from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.models import ULIDPK, ULIDFK, IsoTimestamps



class Attachment(db.Model, ULIDPK, IsoTimestamps):
    """
    Immutable blob metadata. Content-addressed by sha256.
    Storage is external (S3/minio/local); storage_key points to it.
    """

    __tablename__ = "attachment_attachment"

    sha256: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # e.g., application/pdf
    original_filename: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    storage_key: Mapped[str] = mapped_column(
        String(300), nullable=False
    )  # e.g., sha256/ab/cd/<hash>.pdf

    # governance hooks
    privacy_level: Mapped[str] = mapped_column(
        String(1), nullable=False, default="A"
    )  # A/B/C
    retention_policy_code: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )  # active|quarantined|archived

    created_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    # ORM relationship (inferred via FK on AttachmentLink.attachment_ulid)
    links: Mapped[list["AttachmentLink"]] = relationship(
        "AttachmentLink",
        back_populates="attachment",
        cascade="all, delete-orphan",
    )


class AttachmentLink(db.Model, ULIDPK, IsoTimestamps):
    """
    Links an attachment to any domain object (by ULID) in any slice.
    Multiple links per attachment are allowed; links can be archived (soft-delete).
    """

    __tablename__ = "attachment_link"

    # Add a real FK to make the join condition obvious
    attachment_ulid: Mapped[str] = ULIDFK("attachment_attachment", index=True)

    slice: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # e.g., "resources"
    domain: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # e.g., "mou"|"sla"
    target_ulid: Mapped[str] = mapped_column(
        String(26), nullable=False, index=True
    )  # e.g., resource_ulid

    note: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    archived_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    archived_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    attachment: Mapped["Attachment"] = relationship(
        "Attachment",
        back_populates="links",
        foreign_keys="[AttachmentLink.attachment_ulid]",
    )

    __table_args__ = (
        UniqueConstraint(
            "attachment_ulid",
            "slice",
            "domain",
            "target_ulid",
            "archived_at_utc",
            name="uq_active_link",
        ),
        Index("ix_links_target_domain", "slice", "domain", "target_ulid"),
    )
