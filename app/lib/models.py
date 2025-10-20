# app/lib/models.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

from typing import Optional, Tuple

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
    def __table_args__(cls) -> Tuple[CheckConstraint]:
        return (CheckConstraint("length(ulid) = 26", name="ck_ulid_len_26"),)


def ULIDFK(
    target_table: str,
    *,
    ondelete: Optional[str] = "RESTRICT",
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
