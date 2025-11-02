# app/slices/logistics/services.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from sqlalchemy import and_, func, select

from app.extensions import db
from app.extensions.enforcers import enforcers  # calendar_blackout_ok
from app.extensions.event_bus import emit as emit_event
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.lib.jsonutil import pretty_dumps
from app.slices.governance import services as gov  # decide_issue
from app.slices.logistics.sku import parse_sku, validate_sku

from .models import (
    InventoryBatch,
    InventoryItem,
    InventoryMovement,
    InventoryStock,
    Issue,
    Location,
)
from .sku import b36_to_int, int_to_b36

ALLOWED_UNITS = {"each", "lbs", "kits", "boxes", "packs"}
ALLOWED_SOURCES = {"donation", "purchase", "transfer", "drmo"}

# -----------------
# Ensure Location Exists
# upsert by code
# -----------------


def ensure_location(*, code: str, name: str) -> str:
    """
    Idempotently create or return a Location by code (upper-cased),
    committing if a new row is inserted.
    """
    row = db.session.execute(
        select(Location).where(Location.code == code)
    ).scalar_one_or_none()
    if row:
        return row.ulid
    row = Location(
        ulid=new_ulid(), code=code.strip().upper(), name=name.strip()
    )
    db.session.add(row)
    db.session.commit()
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
    if unit not in ALLOWED_UNITS:
        raise ValueError("invalid unit")

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
    db.session.commit()
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
    actor_id: str | None = None,
    source_entity_ulid: str | None = None,
) -> dict:
    """Record a receipt: create batch, create 'receipt' movement,
    and increase on-hand stock at the location."""
    if unit not in ALLOWED_UNITS:
        raise ValueError("invalid unit")
    if source not in ALLOWED_SOURCES:
        raise ValueError("invalid source")

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
        created_by_actor=actor_id,
        note=note,
    )
    db.session.add_all([b, m])
    _apply_stock_delta(
        item_ulid=item_ulid,
        location_ulid=location_ulid,
        unit=unit,
        delta=quantity,
    )
    db.session.commit()
    return {"batch_ulid": b.ulid, "movement_ulid": m.ulid}


# ----------------------------
# Issue (low-level):
# create issue movement,
# decrement stock,
# insert Issue
# ----------------------------
def issue_inventory(
    *,
    batch_ulid: str,
    item_ulid: str,
    quantity: int,
    unit: str,
    location_ulid: str,
    happened_at_utc: str,
    target_ref_ulid: str | None,
    note: str | None,
    actor_id: str | None,
) -> str:
    """Low-level issuance path that writes a movement, reduces stock,
    and inserts the Issue row; returns movement_ulid."""
    if unit not in ALLOWED_UNITS:
        raise ValueError("invalid unit")

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
        created_by_actor=actor_id,
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
        created_by_actor=actor_id,
    )
    db.session.add(issue)

    db.session.commit()
    return m.ulid


# ----------------------------
# Context/DTO utilities
# (used by enforcer/policy orchestration)
# ----------------------------


@dataclass(frozen=True)
class IssueResult:
    """
    Lightweight result DTO for policy-only issuances and
    CLI/reporting surfaces.
    """

    ok: bool
    reason: str
    issue_ulid: Optional[str] = None
    decision: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None


# -----------------
# Context/DTO utilities
# (used by enforcer/policy orchestration)
# -----------------


class _Ctx:
    """
    Minimal attribute carrier for enforcers/governance so callers don’t need
    to import slice internals.
    """

    def __init__(
        self,
        *,
        customer_ulid: str,
        sku_code: Optional[str],
        classification_key: Optional[str],
        when_iso: str,
        project_ulid: Optional[str],
    ):
        self.customer_ulid = customer_ulid
        self.sku_code = sku_code
        self.classification_key = classification_key
        self.when_iso = when_iso
        self.project_ulid = project_ulid


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
        db.session.commit()


# -----------------
# Issue (high-level):
# enforcer → policy → resolve batch → low-level issue → attach decision
# -----------------


def decide_and_issue_one(
    *,
    customer_ulid: str,
    sku_code: str,
    quantity: int = 1,
    when_iso: str | None = None,
    project_ulid: str | None = None,
    actor_id: str | None = None,
    location_ulid: str,  # where stock will be pulled from
    batch_ulid: str | None = None,  # optional: choose a specific batch
) -> dict:
    """
    End-to-end issuance that gates on blackout + policy,
    locates stock, performs the low-level issue,
    and stores the decision trace.

    High-level "one-shot" issuance:
      - Calendar blackout (fast gate)
      - Policy decision (Governance)
      - Resolve item/batch
      - Call low-level issue_inventory(...)
      - Persist decision_json on Issue
    Returns {movement_ulid, decision, ok, reason}
    """
    as_of = when_iso or now_iso8601_ms()

    # derive classification key from SKU once
    parts = parse_sku(sku_code)
    classification_key = f"{parts['cat']}-{parts['sub']}"

    # 1) Enforcer: calendar blackout quick gate
    # (ckey not used here, but harmless to include)
    ok, meta = enforcers.calendar_blackout_ok(
        type(
            "Ctx",
            (),
            {
                "customer_ulid": customer_ulid,
                "sku_code": sku_code,
                "classification_key": classification_key,  # can be None
                "sku_parts": parse_sku(sku_code),  # <-- add this
                "when_iso": as_of,
                "project_ulid": project_ulid,
            },
        )
    )
    if not ok:
        return {
            "ok": False,
            "reason": meta.get("reason", "calendar_blackout"),
            "decision": {"enforcer": meta},
        }

    # 2) Governance decision (policy_issuance.json)
    dec = gov.decide_issue(
        type(
            "Ctx",
            (),
            {
                "customer_ulid": customer_ulid,
                "sku_code": sku_code,
                "classification_key": classification_key,  # can be None
                "sku_parts": parse_sku(sku_code),  # <-- add this
                "when_iso": as_of,
                "project_ulid": project_ulid,
            },
        )
    )

    decision = {
        # Governance returns IssueDecision(allowed=...), not ".ok"
        "ok": bool(getattr(dec, "allowed", getattr(dec, "ok", False))),
        "reason": getattr(dec, "reason", None),
        "approver_required": getattr(dec, "approver_required", None),
        "limit_window_label": getattr(dec, "limit_window_label", None),
        "next_eligible_at_iso": getattr(dec, "next_eligible_at_iso", None),
    }
    if not decision["ok"]:
        return {
            "ok": False,
            "reason": decision["reason"] or "denied",
            "decision": decision,
        }

    # 3) Resolve item + batch if batch_ulid not supplied
    it_ulid = db.session.execute(
        select(InventoryItem.ulid).where(InventoryItem.sku == sku_code)
    ).scalar_one_or_none()
    if not it_ulid:
        return {"ok": False, "reason": "item_not_found", "decision": decision}

    b_ulid = batch_ulid
    if not b_ulid:
        b_ulid = db.session.execute(
            select(InventoryBatch.ulid)
            .where(
                InventoryBatch.item_ulid == it_ulid,
                InventoryBatch.location_ulid == location_ulid,
            )
            .order_by(InventoryBatch.ulid.desc())
        ).scalar_one_or_none()
        if not b_ulid:
            return {
                "ok": False,
                "reason": "no_batch_at_location",
                "decision": decision,
            }

    # 4) Low-level issuance
    mv_ulid = issue_inventory(
        batch_ulid=b_ulid,
        item_ulid=it_ulid,
        quantity=quantity,
        unit="each",
        location_ulid=location_ulid,
        happened_at_utc=as_of,
        target_ref_ulid=customer_ulid,
        note=None,
        actor_id=actor_id,
    )

    # 5) Attach decision trace to Issue
    attach_issue_decision(mv_ulid, decision)

    # 6) # Emit audit spine event (immutable)
    emit_event(
        domain="logistics",
        operation="issue.created",
        request_id=new_ulid(),  # correlation id
        actor_ulid=actor_id,
        target_ulid=customer_ulid,  # subject: the customer
        refs={
            "movement_ulid": mv_ulid,
            "sku_code": sku_code,
            "location_ulid": location_ulid,
            "project_ulid": project_ulid,
        },
        changed={"quantity": quantity},
        meta={"decision": decision},  # full decision trace mirrored here
        happened_at_utc=as_of,
        chain_key="logistics",
    )

    return {
        "ok": True,
        "reason": "ok",
        "decision": decision,
        "movement_ulid": mv_ulid,
    }


# -----------------
# Policy-only Issue:
# evaluate enforcer+policy,
# insert Issue (no stock/movement)
# -----------------


def issue_inventory_policy(
    customer_ulid: str,
    sku_code: Optional[str],
    when_iso: Optional[str] = None,
    project_ulid: Optional[str] = None,
    *,
    actor_ulid: Optional[str] = None,
    quantity: int = 1,
) -> IssueResult:
    """
    Policy-first path that records an Issue row after enforcer+policy OK,
    without touching stock or creating a movement.
    High-level issuance (policy-first) retained for CLI or other callers
    that don't need to pick a specific batch/location themselves.

    Steps:
      1) SKU parse/validate (if provided)
      2) Calendar blackout (enforcer)
      3) Policy decision (governance -> decide_issue)
      4) Persist Issue row (no stock math)
      5) (Optional) emit ledger event externally
    """
    as_of = when_iso or now_iso8601_ms()

    # 1) SKU parse/validate (optional flow supports classification-only issues)
    classification_key: Optional[str] = None
    if sku_code:
        if not validate_sku(sku_code):
            return IssueResult(ok=False, reason="invalid_sku")
        parts = parse_sku(sku_code)
        classification_key = f"{parts['cat']}-{parts['sub']}"
    else:
        parts = None

    ctx = _Ctx(
        customer_ulid=customer_ulid,
        sku_code=sku_code,
        classification_key=classification_key,
        sku_parts=sku_parts,
        when_iso=as_of,
        project_ulid=project_ulid,
    )

    # 2) Calendar blackout
    ok, meta = enforcers.calendar_blackout_ok(ctx)
    if not ok:
        return IssueResult(
            ok=False,
            reason=meta.get("reason", "calendar_blackout"),
            decision={"enforcer": meta},
        )

    # 3) Policy decision
    dec = gov.decide_issue(ctx)
    decision_dict = {
        "ok": bool(getattr(dec, "ok", False)),
        "reason": getattr(dec, "reason", None),
        "approver_required": getattr(dec, "approver_required", None),
        "limit_window_label": getattr(dec, "limit_window_label", None),
        "next_eligible_at_iso": getattr(dec, "next_eligible_at_iso", None),
    }
    if not decision_dict["ok"]:
        return IssueResult(
            ok=False,
            reason=decision_dict["reason"] or "denied",
            decision=decision_dict,
        )

    # 4) Persist Issue row (policy-only path; no movement/stock)
    row = Issue(
        customer_ulid=customer_ulid,
        classification_key=classification_key,
        sku_code=sku_code,
        quantity=quantity,
        issued_at=as_of,
        project_ulid=project_ulid,
        movement_ulid=None,
        created_by_actor=actor_ulid,
    )
    row.decision_json = pretty_dumps(decision_dict)

    db.session.add(row)
    db.session.commit()

    # 5) Caller can emit ledger via event_bus if desired
    return IssueResult(
        ok=True,
        reason="ok",
        issue_ulid=row.ulid,
        decision=decision_dict,
        meta={"policy_only": True},
    )


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


# -----------------
# List Allowed SKUs
# for Customer at time T
# (ask Governance per SKU)
# -----------------


def available_skus_for_customer(
    customer_ulid: str,
    as_of_iso: str,
    project_ulid: str | None = None,
    cost_cents: int | None = None,
) -> list[str]:
    """
    Iterate known SKUs and include those Governance approves for the given
    customer/time; Logistics defers all rules to Governance.
    """
    from app.slices.governance.services import decide_issue
    from app.extensions.contracts import governance_v2 as govc

    rows = db.session.execute(
        select(InventoryItem.sku, InventoryItem.category)
    ).all()

    allowed: list[str] = []
    for sku, category in rows:
        ctx = govc.RestrictionContext(
            customer_ulid=customer_ulid,
            sku_code=sku,
            classification_key=category,
            as_of_iso=as_of_iso,
            project_ulid=project_ulid,
            cost_cents=cost_cents,
        )
        decision = decide_issue(ctx)
        if getattr(decision, "ok", False):
            allowed.append(sku)
    return allowed
