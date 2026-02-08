# app/lib/models.py
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

"""
Shared SQLAlchemy mixins for IDs and timestamps.

This module defines the canonical model building blocks:

- ULIDPK: mixin that adds a 26-char ULID primary key column named
  'ulid' with a length check constraint.
- ULIDFK(table): helper for foreign-key columns that reference
  <table>.ulid with sane defaults.
- IsoTimestamps: mixin that adds created_at_utc and updated_at_utc
  ISO-8601 string timestamps (UTC, ms precision).

All slice models should build on these mixins to keep IDs and timestamps
uniform across the codebase. If you need another timestamp style, add
it here so we preserve a single source of truth.
"""

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid


class ULIDPK:
    """Primary key mixin: 26-char ULID in a column named 'ulid'."""

    @declared_attr
    def ulid(cls) -> Mapped[str]:
        return mapped_column(
            String(26), primary_key=True, default=new_ulid, nullable=False
        )

    @declared_attr.directive
    def __table_args__(cls) -> tuple[CheckConstraint]:
        return (CheckConstraint("length(ulid) = 26", name="ck_ulid_len_26"),)


def ULIDFK(
    target_table: str,
    *,
    ondelete: str | None = "RESTRICT",
    nullable: bool = False,
    index: bool = True,
):
    """FK helper to `<target_table>.ulid`."""
    return mapped_column(
        String(26),
        ForeignKey(f"{target_table}.ulid", ondelete=ondelete),
        nullable=nullable,
        index=index,
    )


class IsoTimestamps:
    """
    Adds ISO-8601 (Z, ms) string timestamps to a model:
      - created_at_utc: String(30), default now
      - updated_at_utc: String(30), default now, auto-updates on change
    """

    @declared_attr
    def created_at_utc(cls) -> Mapped[str]:
        return mapped_column(
            String(30), nullable=False, default=now_iso8601_ms
        )

    @declared_attr
    def updated_at_utc(cls) -> Mapped[str]:
        return mapped_column(
            String(30),
            nullable=False,
            default=now_iso8601_ms,
            onupdate=now_iso8601_ms,
        )


__all__ = ["ULIDPK", "ULIDFK", "IsoTimestamps"]
