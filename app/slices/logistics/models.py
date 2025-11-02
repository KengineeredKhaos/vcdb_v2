# app/slices/logistics/models.py
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import ULIDFK, ULIDPK


class Location(db.Model, ULIDPK):
    __tablename__ = "logi_location"
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class InventoryItem(db.Model, ULIDPK):
    __tablename__ = "logi_item"
    # Human/category labeling
    category: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # "each" etc.
    condition: Mapped[str] = mapped_column(String(16), nullable=False)
    # SKU + parsed parts (strict per schema)
    sku: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    sku_cat: Mapped[str] = mapped_column(
        String(2), index=True, nullable=False
    )
    sku_sub: Mapped[str] = mapped_column(
        String(3), index=True, nullable=False
    )
    sku_src: Mapped[str] = mapped_column(
        String(2), index=True, nullable=False
    )
    sku_size: Mapped[str] = mapped_column(
        String(3), index=True, nullable=False
    )
    sku_color: Mapped[str] = mapped_column(
        String(3), index=True, nullable=False
    )
    sku_issuance_class: Mapped[str] = mapped_column(
        String(1), index=True, nullable=False
    )
    sku_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )

    __table_args__ = (
        Index(
            "ix_item_sku_family",
            "sku_cat",
            "sku_sub",
            "sku_src",
            "sku_size",
            "sku_color",
            "sku_issuance_class",
        ),
    )


class InventoryBatch(db.Model, ULIDPK):
    __tablename__ = "logi_batch"
    item_ulid: Mapped[str] = ULIDFK("logi_item", nullable=False, index=True)
    location_ulid: Mapped[str] = ULIDFK(
        "logi_location", nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )


class InventoryMovement(db.Model, ULIDPK):
    __tablename__ = "logi_movement"
    item_ulid: Mapped[str] = ULIDFK("logi_item", nullable=False, index=True)
    location_ulid: Mapped[str] = ULIDFK(
        "logi_location", nullable=False, index=True
    )
    batch_ulid: Mapped[str | None] = ULIDFK(
        "logi_batch", nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # "receipt","issue","transfer_out","transfer_in"
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    happened_at_utc: Mapped[str] = mapped_column(String(30), nullable=False)
    source_ref_ulid: Mapped[str | None] = mapped_column(String(26))
    target_ref_ulid: Mapped[str | None] = mapped_column(String(26))
    created_by_actor: Mapped[str | None] = mapped_column(String(26))
    note: Mapped[str | None] = mapped_column(String(160))
    __table_args__ = (CheckConstraint("quantity>0", "ck_move_pos_qty"),)


class InventoryStock(db.Model, ULIDPK):
    __tablename__ = "logi_stock"
    item_ulid: Mapped[str] = ULIDFK("logi_item", nullable=False, index=True)
    location_ulid: Mapped[str] = ULIDFK(
        "logi_location", nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)


class Issue(db.Model, ULIDPK):
    __tablename__ = "logi_issue"
    customer_ulid: Mapped[str] = mapped_column(
        String(26), index=True, nullable=False
    )
    classification_key: Mapped[str | None] = mapped_column(
        String(64), index=True
    )
    sku_code: Mapped[str | None] = mapped_column(String(64), index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    issued_at: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # ISO UTC
    project_ulid: Mapped[str | None] = mapped_column(String(26), index=True)
    movement_ulid: Mapped[str | None] = ULIDFK("logi_movement", nullable=True)
    created_by_actor: Mapped[str | None] = mapped_column(String(26))
    created_at_utc: Mapped[str] = mapped_column(
        String(30), default=now_iso8601_ms, nullable=False
    )
    decision_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint("quantity>0", "ck_issue_pos_qty"),
        Index("ix_issue_customer_issued_at", "customer_ulid", "issued_at"),
        Index(
            "ix_issue_customer_class_time",
            "customer_ulid",
            "classification_key",
            "issued_at",
        ),
        Index(
            "ix_issue_customer_sku_time",
            "customer_ulid",
            "sku_code",
            "issued_at",
        ),
    )
