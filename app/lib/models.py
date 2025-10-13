# app/lib/models.py
from sqlalchemy import CheckConstraint, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from app.lib.ids import new_ulid


class ULIDPK:
    ulid: Mapped[str] = mapped_column(
        String(26),
        primary_key=True,
        nullable=False,
        default=new_ulid,  # <-- this is the key line
    )
    __table_args__ = (
        CheckConstraint("length(ulid) = 26", name="ck_ulid_len_26"),
    )


def ULIDFK(
    target_table: str,
    *,
    ondelete: Optional[str] = "RESTRICT",
    nullable: bool = False,
    index: bool = True,
):
    """
    Return a String(26) mapped_column that FKs to `<target_table>.ulid`.

    Example:
        entity_ulid = ULIDFK("entity_entity")
    """
    return mapped_column(
        String(26),
        ForeignKey(f"{target_table}.ulid", ondelete=ondelete),
        nullable=nullable,
        index=index,
    )


__all__ = ["ULIDPK", "ULIDFK"]
