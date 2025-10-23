# app/slices/logistics/services.py
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Optional

from sqlalchemy import and_, func, select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.slices.logistics.models import (
    InventoryBatch,
    InventoryItem,
    InventoryMovement,
    InventoryStock,
    Location,
)

from .sku import b36_to_int, format_sku, int_to_b36, parse_sku, validate_sku

ALLOWED_SOURCES = {"drmo", "donation", "purchase", "transfer"}
ALLOWED_UNITS = {"each", "lbs", "kits", "boxes", "packs"}

# ---------- helpers ----------


def _ensure(arg: str | None, name: str) -> str:
    if not arg or not str(arg).strip():
        raise ValueError(f"{name} required")
    return str(arg).strip()


def ensure_location(*, code: str, name: str) -> str:
    code = _ensure(code, "code")
    name = _ensure(name, "name")
    row = db.session.execute(
        select(Location).where(Location.code == code)
    ).scalar_one_or_none()
    if row:
        if not row.active:
            row.active = True
            row.name = name
        db.session.commit()
        return row.ulid
    row = Location(code=code, name=name, active=True)
    db.session.add(row)
    db.session.commit()
    return row.ulid


# ---------- SKU sequencing ----------


def _next_seq_for_family(
    cat: str, sub: str, src: str, size: str, col: str, grade: str
) -> str:
    row = db.session.execute(
        select(func.max(InventoryItem.sku_seq)).where(
            and_(
                InventoryItem.sku_cat == cat,
                InventoryItem.sku_sub == sub,
                InventoryItem.sku_src == src,
                InventoryItem.sku_size == size,
                InventoryItem.sku_color == col,
                InventoryItem.sku_grade == grade,
            )
        )
    ).scalar_one_or_none()
    nxt_int = 0 if row is None else int(row) + 1
    if nxt_int > 36**3 - 1:
        raise ValueError("SKU sequence exhausted for family")
    return int_to_b36(nxt_int, 3)


# ---------- items ----------


def ensure_item(
    *,
    category: str,
    name: str,
    unit: str,
    condition: str = "mixed",
    sku: str | None = None,
    sku_parts: dict | None = None,
    sku_bin_location: str | None = None,
    sku_nsx: str | None = None,
) -> str:
    unit = unit.strip().lower()
    if unit not in ALLOWED_UNITS:
        raise ValueError("invalid unit")

    # Decide SKU strategy
    parts: dict | None = None
    if sku:
        if not validate_sku(sku):
            raise ValueError("invalid SKU")
        parts = parse_sku(sku)
    elif sku_parts:
        req = ("cat", "sub", "src", "size", "col", "grade")
        if any(k not in sku_parts for k in req):
            raise ValueError("missing sku_parts keys")
        parts = {k: str(sku_parts[k]).upper() for k in req}
        seq = (
            sku_parts.get("seq")
            or _next_seq_for_family(
                parts["cat"],
                parts["sub"],
                parts["src"],
                parts["size"],
                parts["col"],
                parts["grade"],
            )
        ).upper()
        sku = format_sku(
            parts["cat"],
            parts["sub"],
            parts["src"],
            parts["size"],
            parts["col"],
            parts["grade"],
            seq,
        )
        parts["seq"] = seq  # normalized

    row = InventoryItem(
        category=_ensure(category, "category"),
        name=_ensure(name, "name"),
        unit=unit,
        condition=(condition or "mixed"),
        sku=(sku or None),
        sku_bin_location=(sku_bin_location or None),
        sku_nsx=(sku_nsx or None),
        active=True,
    )

    if parts:
        row.sku_cat = parts["cat"]
        row.sku_sub = parts["sub"]
        row.sku_src = parts["src"]
        row.sku_size = parts["size"]
        row.sku_color = parts["col"]
        row.sku_grade = parts["grade"]
        row.sku_seq = b36_to_int(parts["seq"])

    db.session.add(row)
    db.session.commit()
    return row.ulid


def find_item_by_sku(sku: str) -> dict | None:
    if not validate_sku(sku):
        return None
    row = db.session.execute(
        select(InventoryItem).where(InventoryItem.sku == sku.upper())
    ).scalar_one_or_none()
    if not row:
        return None
    return {
        "item_ulid": row.ulid,
        "sku": row.sku,
        "name": row.name,
        "unit": row.unit,
        "condition": row.condition,
        "category": row.category,
        "sku_parts": {
            "cat": row.sku_cat,
            "sub": row.sku_sub,
            "src": row.sku_src,
            "size": row.sku_size,
            "col": row.sku_color,
            "grade": row.sku_grade,
            "seq": int_to_b36(row.sku_seq or 0),
        },
    }


# ---------- stock math (projection) ----------


def _apply_stock_delta(
    *, item_ulid: str, location_ulid: str, unit: str, delta: int
):
    rec = db.session.execute(
        select(InventoryStock).where(
            InventoryStock.item_ulid == item_ulid,
            InventoryStock.location_ulid == location_ulid,
        )
    ).scalar_one_or_none()
    if not rec:
        rec = InventoryStock(
            item_ulid=item_ulid,
            location_ulid=location_ulid,
            unit=unit,
            qty_on_hand=0,
        )
        db.session.add(rec)
    rec.qty_on_hand = int(rec.qty_on_hand) + int(delta)
    rec.updated_at_utc = now_iso8601_ms()
    if rec.qty_on_hand < 0:
        raise ValueError("stock underflow")


def rebuild_stock(
    *, item_ulid: Optional[str] = None, location_ulid: Optional[str] = None
) -> dict:
    q_del = db.session.query(InventoryStock)
    if item_ulid:
        q_del = q_del.filter(InventoryStock.item_ulid == item_ulid)
    if location_ulid:
        q_del = q_del.filter(InventoryStock.location_ulid == location_ulid)
    deleted = q_del.delete()

    deltas: dict[tuple[str, str, str], int] = defaultdict(int)
    q = db.session.query(InventoryMovement)
    if item_ulid:
        q = q.filter(InventoryMovement.item_ulid == item_ulid)
    if location_ulid:
        q = q.filter(
            (InventoryMovement.location_from_ulid == location_ulid)
            | (InventoryMovement.location_to_ulid == location_ulid)
        )
    for m in q.all():
        if m.kind == "receipt":
            deltas[(m.item_ulid, m.location_to_ulid, m.unit)] += m.quantity
        elif m.kind == "issue":
            deltas[(m.item_ulid, m.location_from_ulid, m.unit)] -= m.quantity
        elif m.kind == "transfer_out":
            deltas[(m.item_ulid, m.location_from_ulid, m.unit)] -= m.quantity
        elif m.kind == "transfer_in":
            deltas[(m.item_ulid, m.location_to_ulid, m.unit)] += m.quantity
        elif m.kind == "adjustment":
            sign = 1 if m.location_to_ulid else -1
            loc = m.location_to_ulid or m.location_from_ulid
            deltas[(m.item_ulid, loc, m.unit)] += sign * m.quantity

    for (item, loc, unit), delta in deltas.items():
        _apply_stock_delta(
            item_ulid=item, location_ulid=loc, unit=unit, delta=delta
        )

    db.session.commit()
    event_bus.emit(
        type="logistics.stock.rebuilt",
        slice="logistics",
        operation="rebuild",
        actor_ulid=None,
        target_ulid="-",
        request_id="-",
        happened_at_utc=now_iso8601_ms(),
        refs={"deleted": deleted, "entries": len(deltas)},
    )
    return {"deleted": deleted, "entries": len(deltas)}


# ---------- core flows ----------


def receive_inventory(
    *,
    item_ulid: str,
    quantity: int,
    unit: str,
    source: str,
    received_at_utc: str,
    location_ulid: str,
    source_entity_ulid: Optional[str],
    note: Optional[str],
    actor_id: Optional[str],
) -> dict:
    if int(quantity) <= 0:
        raise ValueError("quantity must be > 0")
    unit = unit.strip().lower()
    if unit not in ALLOWED_UNITS:
        raise ValueError("invalid unit")
    source = source.strip().lower()
    if source not in ALLOWED_SOURCES:
        raise ValueError("invalid source")

    b = InventoryBatch(
        item_ulid=item_ulid,
        source=source,
        source_entity_ulid=source_entity_ulid or None,
        received_at_utc=received_at_utc,
        note=note or None,
        created_by_actor=actor_id,
    )
    db.session.add(b)
    db.session.flush()

    m = InventoryMovement(
        batch_ulid=b.ulid,
        item_ulid=item_ulid,
        kind="receipt",
        quantity=int(quantity),
        unit=unit,
        happened_at_utc=received_at_utc,
        location_from_ulid=None,
        location_to_ulid=location_ulid,
        target_ref_ulid=None,
        note=note or None,
        created_by_actor=actor_id,
    )
    db.session.add(m)

    _apply_stock_delta(
        item_ulid=item_ulid,
        location_ulid=location_ulid,
        unit=unit,
        delta=int(quantity),
    )
    db.session.commit()

    event_bus.emit(
        type="inventory.received",
        slice="logistics",
        operation="insert",
        actor_ulid=actor_id,
        target_ulid=b.ulid,
        request_id=b.ulid,
        happened_at_utc=received_at_utc,
        refs={
            "item_ulid": item_ulid,
            "qty": int(quantity),
            "unit": unit,
            "location_ulid": location_ulid,
            "source": source,
        },
    )
    return {"batch_ulid": b.ulid, "movement_ulid": m.ulid}


def issue_inventory(
    *,
    batch_ulid: str,
    item_ulid: str,
    quantity: int,
    unit: str,
    location_ulid: str,
    happened_at_utc: str,
    target_ref_ulid: Optional[str],
    note: Optional[str],
    actor_id: Optional[str],
) -> str:
    if int(quantity) <= 0:
        raise ValueError("quantity must be > 0")
    unit = unit.strip().lower()
    if unit not in ALLOWED_UNITS:
        raise ValueError("invalid unit")

    m = InventoryMovement(
        batch_ulid=batch_ulid,
        item_ulid=item_ulid,
        kind="issue",
        quantity=int(quantity),
        unit=unit,
        happened_at_utc=happened_at_utc,
        location_from_ulid=location_ulid,
        location_to_ulid=None,
        target_ref_ulid=target_ref_ulid or None,
        note=note or None,
        created_by_actor=actor_id,
    )
    db.session.add(m)
    _apply_stock_delta(
        item_ulid=item_ulid,
        location_ulid=location_ulid,
        unit=unit,
        delta=-int(quantity),
    )
    db.session.commit()

    event_bus.emit(
        type="inventory.issued",
        slice="logistics",
        operation="issue",
        actor_ulid=actor_id,
        target_ulid=m.ulid,
        request_id=m.ulid,
        happened_at_utc=happened_at_utc,
        refs={
            "item_ulid": item_ulid,
            "qty": int(quantity),
            "unit": unit,
            "location_ulid": location_ulid,
            "target_ref_ulid": target_ref_ulid,
        },
    )
    return m.ulid


def transfer_inventory(
    *,
    item_ulid: str,
    quantity: int,
    unit: str,
    happened_at_utc: str,
    location_from_ulid: str,
    location_to_ulid: str,
    note: Optional[str],
    actor_id: Optional[str],
    batch_ulid: Optional[str] = None,
) -> dict:
    if int(quantity) <= 0:
        raise ValueError("quantity must be > 0")
    unit = unit.strip().lower()
    if unit not in ALLOWED_UNITS:
        raise ValueError("invalid unit")

    if not batch_ulid:
        b = InventoryBatch(
            item_ulid=item_ulid,
            source="transfer",
            source_entity_ulid=None,
            received_at_utc=happened_at_utc,
            note=note or None,
            created_by_actor=actor_id,
        )
        db.session.add(b)
        db.session.flush()
        batch_ulid = b.ulid

    m_out = InventoryMovement(
        batch_ulid=batch_ulid,
        item_ulid=item_ulid,
        kind="transfer_out",
        quantity=int(quantity),
        unit=unit,
        happened_at_utc=happened_at_utc,
        location_from_ulid=location_from_ulid,
        location_to_ulid=None,
        target_ref_ulid=None,
        note=note or None,
        created_by_actor=actor_id,
    )
    m_in = InventoryMovement(
        batch_ulid=batch_ulid,
        item_ulid=item_ulid,
        kind="transfer_in",
        quantity=int(quantity),
        unit=unit,
        happened_at_utc=happened_at_utc,
        location_from_ulid=None,
        location_to_ulid=location_to_ulid,
        target_ref_ulid=None,
        note=note or None,
        created_by_actor=actor_id,
    )
    db.session.add_all([m_out, m_in])

    _apply_stock_delta(
        item_ulid=item_ulid,
        location_ulid=location_from_ulid,
        unit=unit,
        delta=-int(quantity),
    )
    _apply_stock_delta(
        item_ulid=item_ulid,
        location_ulid=location_to_ulid,
        unit=unit,
        delta=int(quantity),
    )
    db.session.commit()

    event_bus.emit(
        type="inventory.transferred",
        slice="logistics",
        operation="transfer",
        actor_ulid=actor_id,
        target_ulid=batch_ulid,
        request_id=batch_ulid,
        happened_at_utc=happened_at_utc,
        refs={
            "item_ulid": item_ulid,
            "qty": int(quantity),
            "unit": unit,
            "from": location_from_ulid,
            "to": location_to_ulid,
        },
    )
    return {"movement_out_ulid": m_out.ulid, "movement_in_ulid": m_in.ulid}


# ---------- views/search ----------


def stock_view(
    *, item_ulid: str | None = None, location_ulid: str | None = None
) -> list[dict]:
    q = db.session.query(InventoryStock)
    if item_ulid:
        q = q.filter(InventoryStock.item_ulid == item_ulid)
    if location_ulid:
        q = q.filter(InventoryStock.location_ulid == location_ulid)
    rows = q.order_by(InventoryStock.updated_at_utc.desc()).all()
    return [
        {
            "stock_ulid": r.ulid,
            "item_ulid": r.item_ulid,
            "location_ulid": r.location_ulid,
            "unit": r.unit,
            "qty_on_hand": r.qty_on_hand,
            "updated_at_utc": r.updated_at_utc,
        }
        for r in rows
    ]


def item_view(item_ulid: str) -> dict | None:
    it = db.session.get(InventoryItem, item_ulid)
    if not it:
        return None
    stock = stock_view(item_ulid=item_ulid)
    return {
        "item_ulid": it.ulid,
        "category": it.category,
        "sku": it.sku,
        "name": it.name,
        "unit": it.unit,
        "condition": it.condition,
        "active": it.active,
        "stock": stock,
        "created_at_utc": it.created_at_utc,
        "updated_at_utc": it.updated_at_utc,
    }
