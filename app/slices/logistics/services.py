# app/slices/logistics/services.py

from __future__ import annotations

import re

from sqlalchemy import and_, func, select

from app.extensions import db
from app.extensions.policies import (
    load_policy_locations,
    load_policy_sku_constraints,
)
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.lib.jsonutil import pretty_dumps
from app.slices.logistics.sku import (
    parse_sku,
    validate_sku,
)

from .models import (
    InventoryBatch,
    InventoryItem,
    InventoryMovement,
    InventoryStock,
    Issue,
    Location,
)
from .sku import b36_to_int, int_to_b36

# Load and cache SKU constraints policy (allowed units/sources, rules).
# If the policy is invalid, this fails fast at startup.
_SKU_POLICY = load_policy_sku_constraints()
_ALLOWED_UNITS = frozenset(_SKU_POLICY.get("allowed_units") or [])
_ALLOWED_SOURCES = frozenset(_SKU_POLICY.get("allowed_sources") or [])
_LOCATION_POLICY = load_policy_locations()
_ALLOWED_LOCATIONS = frozenset(
    loc["code"] for loc in _LOCATION_POLICY.get("locations", [])
)
_RACKBIN_PATTERN = re.compile(
    _LOCATION_POLICY.get("patterns", {}).get("rackbin", r"$^")
)  # default $^ matches nothing


def _require_valid_unit(unit: str) -> None:
    """Raise ValueError if unit is not allowed by Governance policy."""
    if unit not in _ALLOWED_UNITS:
        raise ValueError(
            f"invalid unit {unit!r}; allowed={sorted(_ALLOWED_UNITS)}"
        )


def _require_valid_source(source: str) -> None:
    """Raise ValueError if source is not allowed by Governance policy."""
    if source not in _ALLOWED_SOURCES:
        raise ValueError(
            f"invalid source {source!r}; allowed={sorted(_ALLOWED_SOURCES)}"
        )


def _require_valid_location_code(code: str) -> None:
    policy = load_policy_locations()  # same pattern as SKU policy
    known_codes = {loc["code"] for loc in policy["locations"]}
    rackbin_pattern = re.compile(policy["patterns"]["rackbin"])

    if code in known_codes:
        return
    if rackbin_pattern.match(code):
        return

    raise ValueError(f"invalid location code {code!r}")


# -----------------
# Ensure Location Exists
# upsert by code
# -----------------


def ensure_location(*, code: str, name: str) -> str:
    code = code.strip().upper()
    name = name.strip()

    _require_valid_location_code(code)  # policy-backed check

    row = db.session.execute(
        select(Location).where(Location.code == code)
    ).scalar_one_or_none()
    if row:
        # Optional: ensure name matches policy if this code is policy-controlled
        return row.ulid

    row = Location(ulid=new_ulid(), code=code, name=name)
    db.session.add(row)
    db.session.flush()
    return row.ulid


# -----------------
# Next SKU Sequence
# for Family (base36)
# -----------------


def _next_seq_for_family(parts: dict) -> str:
    """
    Compute the next base-36 sequence for the SKU family defined by parts
    (cat/sub/src/size/col/issuance_class).
    """
    q = select(func.max(InventoryItem.sku_seq)).where(
        and_(
            InventoryItem.sku_cat == parts["cat"],
            InventoryItem.sku_sub == parts["sub"],
            InventoryItem.sku_src == parts["src"],
            InventoryItem.sku_size == parts["size"],
            InventoryItem.sku_color == parts["col"],
            InventoryItem.sku_issuance_class == parts["issuance_class"],
        )
    )
    mx = db.session.execute(q).scalar_one_or_none() or 0
    return int_to_b36(mx + 1, 3)


# -----------------
# Ensure/Upsert
# InventoryItem
# by SKU
# -----------------


def ensure_item(
    *,
    category: str,
    name: str,
    unit: str,
    condition: str,
    sku: str | None = None,
    sku_parts: dict | None = None,
) -> str:
    """Idempotently create or return an InventoryItem for the given SKU
    (or parts), validating and enforcing SKU constraints."""
    # Governance-backed unit validation (No Garbage In).
    _require_valid_unit(unit)

    # Normalize unit/category/name if you like; optional:
    unit = unit.strip().lower()  # or .upper(), as long as it matches policy
    category = category.strip()
    name = name.strip()

    # Resolve SKU
    if sku:
        if not validate_sku(sku):
            raise ValueError("invalid SKU")
        parts = parse_sku(sku)
        sku = sku.upper()
    elif sku_parts:
        p = {
            k: str(sku_parts[k]).upper()
            for k in ("cat", "sub", "src", "size", "col", "issuance_class")
        }
        seq = str(sku_parts.get("seq") or _next_seq_for_family(p)).upper()
        sku = (
            f"{p['cat']}-{p['sub']}-{p['src']}-{p['size']}-{p['col']}-"
            f"{p['issuance_class']}-{seq}"
        )
        parts = {**p, "seq": seq}
        if not validate_sku(sku):
            raise ValueError("invalid SKU parts")
    else:
        raise ValueError("sku or sku_parts required")

    # Enforce construction constraints (raises ValueError if violated)
    from app.extensions.policy_semantics import assert_sku_constraints_ok

    assert_sku_constraints_ok(parts)

    # Upsert by SKU
    row = db.session.execute(
        select(InventoryItem).where(InventoryItem.sku == sku)
    ).scalar_one_or_none()
    if row:
        return row.ulid
    row = InventoryItem(
        ulid=new_ulid(),
        category=category,
        name=name,
        unit=unit,
        condition=condition,
        sku=sku,
        sku_cat=parts["cat"],
        sku_sub=parts["sub"],
        sku_src=parts["src"],
        sku_size=parts["size"],
        sku_color=parts["col"],
        sku_issuance_class=parts["issuance_class"],
        sku_seq=b36_to_int(parts["seq"]),
    )
    db.session.add(row)
    db.session.flush()
    return row.ulid


# -----------------
# Apply Stock Delta
# (create row if missing)
# (then += delta)
# -----------------


def _apply_stock_delta(
    *, item_ulid: str, location_ulid: str, unit: str, delta: int
) -> None:
    """Ensure an InventoryStock row exists for
    (item, location), then increment quantity
    by delta (may be negative)."""
    rec = db.session.execute(
        select(InventoryStock).where(
            and_(
                InventoryStock.item_ulid == item_ulid,
                InventoryStock.location_ulid == location_ulid,
            )
        )
    ).scalar_one_or_none()
    if not rec:
        rec = InventoryStock(
            ulid=new_ulid(),
            item_ulid=item_ulid,
            location_ulid=location_ulid,
            unit=unit,
            quantity=0,
        )
        db.session.add(rec)
    rec.quantity += delta


# -----------------
# Receive Inventory
# (batch + receipt movement + stock++)
# -----------------


def receive_inventory(
    *,
    item_ulid: str,
    quantity: int,
    unit: str,
    source: str,
    received_at_utc: str,
    location_ulid: str,
    note: str | None = None,
    actor_ulid: str | None = None,
    source_entity_ulid: str | None = None,
) -> dict:
    """Record a receipt: create batch, create 'receipt' movement,
    and increase on-hand stock at the location.
    """
    # Governance-backed validation for unit/source on ingress.
    _require_valid_unit(unit)
    _require_valid_source(source)

    # Normalize if needed to match policy casing:
    unit = unit.strip().lower()
    source = source.strip().lower()

    b = InventoryBatch(
        ulid=new_ulid(),
        item_ulid=item_ulid,
        location_ulid=location_ulid,
        quantity=quantity,
        unit=unit,
    )
    m = InventoryMovement(
        ulid=new_ulid(),
        item_ulid=item_ulid,
        location_ulid=location_ulid,
        batch_ulid=b.ulid,
        kind="receipt",
        quantity=quantity,
        unit=unit,
        happened_at_utc=received_at_utc,
        source_ref_ulid=source_entity_ulid,
        target_ref_ulid=None,
        created_by_actor=actor_ulid,
        note=note,
    )
    db.session.add_all([b, m])
    _apply_stock_delta(
        item_ulid=item_ulid,
        location_ulid=location_ulid,
        unit=unit,
        delta=quantity,
    )
    db.session.flush()
    return {"batch_ulid": b.ulid, "movement_ulid": m.ulid}


# ----------------------------
# Issue (low-level):
# create issue movement,
# decrement stock,
# insert Issue
# ----------------------------
def issue_inventory_lowlevel(
    *,
    batch_ulid: str,
    item_ulid: str,
    quantity: int,
    unit: str,
    location_ulid: str,
    happened_at_utc: str,
    target_ref_ulid: str | None,
    note: str | None,
    actor_ulid: str | None,
) -> str:
    """Low-level issuance path that writes a movement, reduces stock,
    and inserts the Issue row; returns movement_ulid.
    """

    # Movement record
    m = InventoryMovement(
        ulid=new_ulid(),
        item_ulid=item_ulid,
        location_ulid=location_ulid,
        batch_ulid=batch_ulid,
        kind="issue",
        quantity=quantity,
        unit=unit,
        happened_at_utc=happened_at_utc,
        source_ref_ulid=None,
        target_ref_ulid=target_ref_ulid,
        created_by_actor=actor_ulid,
        note=note,
    )
    db.session.add(m)

    # Stock delta
    _apply_stock_delta(
        item_ulid=item_ulid,
        location_ulid=location_ulid,
        unit=unit,
        delta=-quantity,
    )

    # Issue row (no decision_json here; attach later)
    it = db.session.execute(
        select(InventoryItem.sku, InventoryItem.category).where(
            InventoryItem.ulid == item_ulid
        )
    ).one()
    sku_code, category = it

    issue = Issue(
        ulid=new_ulid(),
        customer_ulid=target_ref_ulid,
        classification_key=category,
        sku_code=sku_code,
        quantity=quantity,
        issued_at=happened_at_utc,
        project_ulid=None,
        movement_ulid=m.ulid,
        created_by_actor=actor_ulid,
    )
    db.session.add(issue)

    db.session.flush()
    return m.ulid


# -----------------
# Attach Decision Trace
# Issue.decision_json
# (issue decision text)
# -----------------


def attach_issue_decision(movement_ulid: str, decision: dict) -> None:
    """
    Find the Issue linked to the movement and persist
    the serialized policy/enforcer decision trace to decision_json.
    """
    issue = db.session.execute(
        select(Issue).where(Issue.movement_ulid == movement_ulid)
    ).scalar_one_or_none()
    if issue:
        issue.decision_json = pretty_dumps(decision)
        db.session.flush()


# -----------------
# Count Issues in Window
# (filter by sku or classification)
# -----------------


def count_issues_in_window(
    customer_ulid: str,
    classification_key: str | None = None,
    sku_code: str | None = None,
    window_start_iso: str | None = None,
    as_of_iso: str | None = None,
) -> int:
    """
    Count Issue rows for a customer within [window_start_iso, as_of_iso],
    filtered by either classification_key OR sku_code.
    If both given, sku_code wins.

    Return the number of Issue rows for the customer within
    [window_start, as_of], preferring sku_code filter over classification.
    """
    if not as_of_iso:
        as_of_iso = now_iso8601_ms()

    preds = [Issue.customer_ulid == customer_ulid]
    if window_start_iso:
        preds.append(Issue.issued_at >= window_start_iso)
    if as_of_iso:
        preds.append(Issue.issued_at <= as_of_iso)
    if sku_code:
        preds.append(Issue.sku_code == sku_code)
    elif classification_key:
        preds.append(Issue.classification_key == classification_key)

    q = select(func.count()).select_from(Issue).where(and_(*preds))
    return int(db.session.execute(q).scalar_one() or 0)


def nth_oldest_issue_at_in_window(
    customer_ulid: str,
    n: int,
    classification_key: str | None = None,
    sku_code: str | None = None,
    window_start_iso: str | None = None,
    as_of_iso: str | None = None,
) -> str | None:
    """
    Return the Nth-oldest Issue.issued_at (1-based) within [window_start_iso, as_of_iso],
    filtered by sku_code (preferred) or classification_key.

    Used to compute next-eligible time when cadence is maxed.
    """
    if n <= 0:
        return None
    if not as_of_iso:
        as_of_iso = now_iso8601_ms()

    preds = [Issue.customer_ulid == customer_ulid]
    if window_start_iso:
        preds.append(Issue.issued_at >= window_start_iso)
    if as_of_iso:
        preds.append(Issue.issued_at <= as_of_iso)
    if sku_code:
        preds.append(Issue.sku_code == sku_code)
    elif classification_key:
        preds.append(Issue.classification_key == classification_key)

    q = (
        select(Issue.issued_at)
        .where(and_(*preds))
        .order_by(Issue.issued_at.asc())
        .offset(n - 1)
        .limit(1)
    )
    return db.session.execute(q).scalar_one_or_none()
