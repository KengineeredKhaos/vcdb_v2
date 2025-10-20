# app/slices/logistics/models.py
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.chrono import now_iso8601_ms, utcnow_naive
from app.lib.models import ULIDFK, ULIDPK


class Location(db.Model, ULIDPK):
    __tablename__ = "logi_location"

    code: Mapped[str] = mapped_column(
        String(48), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=now_iso8601_ms,
        onupdate=now_iso8601_ms,
        nullable=False,
    )


class InventoryItem(db.Model, ULIDPK):
    """
    A catalog record for a tangible thing we track by quantity (no dollars).
    SKU is a human/business code; ULID remains the immutable PK.
    """

    __tablename__ = "logi_item"

    # --- SKU & normalized parts ---
    sku: Mapped[str | None] = mapped_column(
        String(32), unique=True, index=True, nullable=True
    )  # e.g., "UG-TP-DR-M-OD-B-0F7"
    sku_cat: Mapped[str | None] = mapped_column(
        String(2), nullable=True, index=True
    )  # CAT
    sku_sub: Mapped[str | None] = mapped_column(
        String(3), nullable=True, index=True
    )  # SUB
    sku_src: Mapped[str | None] = mapped_column(
        String(2), nullable=True, index=True
    )  # SRC
    sku_size: Mapped[str | None] = mapped_column(
        String(3), nullable=True, index=True
    )  # SZ
    sku_color: Mapped[str | None] = mapped_column(
        String(3), nullable=True, index=True
    )  # COL
    sku_grade: Mapped[str | None] = mapped_column(
        String(1), nullable=True, index=True
    )  # CND
    sku_seq: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )  # base-36 sequence as int

    # optional bin / external codes
    sku_bin_location: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    sku_nsx: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # NSN/UPC/etc.

    # --- descriptive fields ---
    category: Mapped[str] = mapped_column(
        String(32), index=True, nullable=False
    )  # e.g., 'food','hygiene','tools'
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    unit: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # 'each','lbs','kits','boxes','packs'
    condition: Mapped[str] = mapped_column(
        String(16), nullable=False, default="mixed"
    )  # 'new','used','mixed'
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, index=True, nullable=False
    )

    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=now_iso8601_ms,
        onupdate=now_iso8601_ms,
        nullable=False,
    )

    __table_args__ = (
        # speedy “family” scans for next sequence:
        Index(
            "ix_logi_item_sku_family",
            "sku_cat",
            "sku_sub",
            "sku_src",
            "sku_size",
            "sku_color",
            "sku_grade",
        ),
    )


class InventoryBatch(db.Model, ULIDPK):
    __tablename__ = "logi_batch"

    item_ulid: Mapped[str] = ULIDFK("logi_item", index=True)
    source: Mapped[str] = mapped_column(
        String(24), nullable=False, index=True
    )  # 'drmo','donation','purchase','transfer'
    source_entity_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )  # optional provider EntityOrg
    received_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)

    note: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )


class InventoryMovement(db.Model, ULIDPK):
    __tablename__ = "logi_movement"

    batch_ulid: Mapped[str] = ULIDFK("logi_batch", index=True)
    item_ulid: Mapped[str] = ULIDFK("logi_item", index=True)

    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # 'receipt','issue','transfer_out','transfer_in','adjustment'
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # always positive; sign implied by kind
    unit: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # duplicate for queries
    happened_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    location_from_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )
    location_to_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )

    target_ref_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )  # e.g., customer/event/program ULID (no PII)
    note: Mapped[str | None] = mapped_column(String(160), nullable=True)

    created_by_actor: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_movement_pos_qty"),
    )


class InventoryStock(db.Model, ULIDPK):
    __tablename__ = "logi_stock"

    item_ulid: Mapped[str] = ULIDFK("logi_item", index=True)
    location_ulid: Mapped[str] = ULIDFK("logi_location", index=True)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)

    qty_on_hand: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    updated_at_utc: Mapped[str] = mapped_column(
        String(30),
        default=now_iso8601_ms,
        onupdate=now_iso8601_ms,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "item_ulid", "location_ulid", name="uq_stock_item_location"
        ),
    )
