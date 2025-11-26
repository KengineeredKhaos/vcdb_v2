# app/slices/logistics/models.py

"""
Logistics slice — inventory catalog, stock/movements, and issuance facts.

This module defines the core data model for physical inventory in VCDB v2.
Logistics owns the *facts* about items, stock levels, and movements; policy,
financial valuation, and customer profile live in other slices. The tables here
are deliberately narrow and operational:

* Location
    Logical or physical locations where stock can live (e.g., main warehouse,
    outreach van, storage locker). These are referenced by batches, movements,
    and stock summary rows.
* InventoryItem
    The canonical item catalog, one row per SKU. Each item carries a human
    category/name/unit/condition plus a parsed, indexed SKU family
    (cat/sub/src/size/color/issuance_class/seq) to support fast lookups by
    classification and issuance rules.
* InventoryBatch
    Represents a discrete batch of an item at a specific location (e.g., a
    receipt or donation lot). Used when you need to trace stock back to a
    source or DRMO vs commercial acquisition. Quantities are in whole units.
* InventoryMovement
    Append-only record of item movements: receipts, issues, transfers, etc.
    Each movement ties an item and location (and optionally a batch) to a
    quantity, timestamp, and optional external references (source/target ULIDs,
    actor, note). This is the ground truth for how stock has changed over time.
* InventoryStock
    A denormalized stock summary per (item_ulid, location_ulid). This table is
    a performance helper derived from movements; it can be recomputed if needed
    and should never be treated as an audit log.
* Issue
    Customer-facing issuance facts keyed by `customer_ulid`. Each row captures
    what SKU was issued, in what quantity, when, and under which project. It
    also links back to the underlying movement row (if any) and can store a
    JSON-encoded decision payload explaining why the issuance was allowed under
    policy. This is the Logistics-owned history that downstream slices (e.g.,
    Governance, Customers) use to enforce cadence and eligibility; no PII lives
    here beyond the customer ULID.

Ownership and boundaries:

* The Logistics slice is the only writer for these tables. Other slices must
  interact with inventory and issuance via services and contracts, not by
  importing these models directly or joining on them.
* Governance supplies issuance policy and cadence rules; Logistics applies that
  policy to customer/stock context and records the resulting Issue and
  movements.
* Finance is responsible for valuing items and recording monetary impact in the
  journal; Logistics records only quantities, SKUs, locations, and references.
* Ledger events for inventory/issuance are emitted from Logistics services via
  the shared event bus and refer to ULIDs, not raw row contents.

In short, this module is the operational backbone for "what do we have, where
is it, and what did we hand to whom and when?" All higher-level reporting,
policy, and financial views are layered on top of these facts.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.lib.models import ULIDFK, ULIDPK, IsoTimestamps


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


class InventoryBatch(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "logi_batch"
    item_ulid: Mapped[str] = ULIDFK("logi_item", nullable=False, index=True)
    location_ulid: Mapped[str] = ULIDFK(
        "logi_location", nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)


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
