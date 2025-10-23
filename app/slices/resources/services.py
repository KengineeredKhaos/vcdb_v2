# app/slices/resources/services.py
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import desc, func

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps

from .models import Resource, ResourceCapabilityIndex, ResourceHistory

# ---------------------------------------------------------------------------
# Controlled Vocabulary (MVP) — move to Governance later
# ---------------------------------------------------------------------------
CLASSIFICATIONS: dict[str, tuple[str, ...]] = {
    "veterans_affairs": ("federal", "state", "local"),
    "quartermaster": (
        "dmro",
        "regional_depot",
        "regional_stand_down",
        "local_civil_donations",
        "local_commercial_discounts",
    ),
    "events": (
        "event_coordination",
        "promotions_print_radio",
        "promotions_social_media",
        "artwork_signage_fliers",
        "facility_rental",
        "equipment_rental",
        "food_service",
        "security_service",
        "staffing_coordination",
        "branded_swag",
    ),
    "basic_needs": (
        "food_pantry",
        "mobile_shower",
        "shelter_temp_men",
        "shelter_temp_women_children",
        "clothing",
        "barber",
    ),
    "health_wellness": (
        "urgent_care",
        "hospital",
        "dental",
        "vision",
        "audiology",
        "mobility_aids",
        "in_home_health_care",
        "service_animals",
    ),
    "counseling_services": (
        "employment_counseling",
        "education_counseling",
        "behavioral_psychological",
        "substance_abuse",
        "domestic_violence",
        "peer_group",
        "financial_counseling",
        "legal_criminal",
        "legal_civil",
    ),
    "housing": (
        "public_housing_coordination",
        "rent_assistance",
        "utilities_assistance",
        "household_goods",
        "internet_phone",
        "childcare_assistance",
        "handyman_general",
        "yard_maintenance",
        "weed_abatement",
        "junk_trash_removal",
    ),
    "transportation": (
        "public_transit",
        "ride_share",
        "medical_transport",
        "auto_repair",
    ),
    "meta": ("unclassified",),
}

SECTION = "resource:capability:v1"
NOTE_MAX = 120


# ---------------- helpers ----------------


def _ensure_reqid(rid: Optional[str]) -> str:
    if not rid or not str(rid).strip():
        raise ValueError("request_id must be non-empty")
    return str(rid)


def _split(flat_key: str) -> Tuple[str, str]:
    if "." not in flat_key:
        raise ValueError(
            f"invalid classification key '{flat_key}'; expected 'domain.key'"
        )
    domain, key = flat_key.split(".", 1)
    return domain.strip(), key.strip()


def _validate_payload(payload: Dict[str, Any]) -> Dict[str, dict]:
    """
    Input: { "domain.key": {"has": bool, "note"?: str} }
    Returns normalized dict with clamped note length and boolean has.
    """
    norm: Dict[str, dict] = {}
    for flat_key, obj in (payload or {}).items():
        domain, key = _split(flat_key)
        if (
            domain not in CLASSIFICATIONS
            or key not in CLASSIFICATIONS[domain]
        ):
            raise ValueError(f"unknown classification '{domain}.{key}'")
        if not isinstance(obj, dict) or "has" not in obj:
            raise ValueError(f"missing 'has' boolean for '{flat_key}'")
        has = bool(obj["has"])
        note = obj.get("note")
        if note is not None:
            note = str(note).strip()
            if len(note) > NOTE_MAX:
                note = note[:NOTE_MAX]
        norm[f"{domain}.{key}"] = {
            "has": has,
            **({"note": note} if note else {}),
        }
    return norm


def _latest_snapshot(resource_ulid: str) -> Dict[str, dict]:
    h = (
        db.session.query(ResourceHistory)
        .filter_by(resource_ulid=resource_ulid, section=SECTION)
        .order_by(desc(ResourceHistory.version))
        .first()
    )
    return json.loads(h.data_json) if h else {}


def _next_version(resource_ulid: str) -> int:
    cur = (
        db.session.query(func.max(ResourceHistory.version))
        .filter_by(resource_ulid=resource_ulid, section=SECTION)
        .scalar()
    )
    return int(cur or 0) + 1


# ------------- core API ------------------


def ensure_resource(
    *, entity_ulid: str, request_id: str, actor_id: Optional[str]
) -> str:
    """
    Idempotently ensure a Resource row exists for this entity.
    (No cross-slice service calls; caller is responsible for entity lifecycle.)
    """
    _ensure_reqid(request_id)

    r = db.session.query(Resource).filter_by(entity_ulid=entity_ulid).first()
    if not r:
        now = now_iso8601_ms()
        r = Resource(
            entity_ulid=entity_ulid,
            first_seen_utc=now,
            last_touch_utc=now,
            readiness_status="draft",
            mou_status="none",
        )
        db.session.add(r)
        db.session.commit()

        event_bus.emit(
            domain="resources",
            operation="created_insert",
            actor_ulid=actor_id,
            target_ulid=r.ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"entity_ulid": entity_ulid},
        )
    else:
        r.last_touch_utc = now_iso8601_ms()
        db.session.commit()
    return r.ulid


def upsert_capabilities(
    *,
    resource_ulid: str,
    payload: Dict[str, Any],
    request_id: str,
    actor_id: Optional[str],
    idempotency_key: Optional[str] = None,
) -> str:
    """
    Replace semantics: incoming payload is the new truth.
    - Validates keys/values
    - Writes ResourceHistory (values + notes) with next version
    - Updates ResourceCapabilityIndex (names only)
    - Sets admin_review_required based on 'meta.unclassified'
    - Emits names-only ledger events for deltas with version pointer
    Returns history_ulid.
    """
    _ensure_reqid(request_id)

    res = db.session.get(Resource, resource_ulid)
    if not res:
        raise ValueError("resource not found")

    norm = _validate_payload(payload)

    # Idempotency (optional): if identical to last snapshot, no-op
    last = _latest_snapshot(resource_ulid)
    if last and stable_dumps(last) == stable_dumps(norm):
        # touch resource but don't write new version
        res.last_touch_utc = now_iso8601_ms()
        db.session.commit()
        return ""  # indicate no new version created

    # Compute deltas (names-only)
    before_active = {k for k, v in last.items() if v.get("has") is True}
    after_active = {k for k, v in norm.items() if v.get("has") is True}
    added = sorted(after_active - before_active)
    removed = sorted(before_active - after_active)

    # Write History
    version = _next_version(resource_ulid)
    hist = ResourceHistory(
        resource_ulid=resource_ulid,
        section=SECTION,
        version=version,
        data_json=stable_dumps(norm),
        created_by_actor=actor_id,
    )
    db.session.add(hist)

    # Rebuild projection table in-place
    # 1) Fetch existing projection entries
    existing = {
        (rc.domain, rc.key): rc
        for rc in db.session.query(ResourceCapabilityIndex)
        .filter_by(resource_ulid=resource_ulid)
        .all()
    }
    # 2) Upsert new/updated rows
    now = now_iso8601_ms()
    seen_pairs: set[tuple[str, str]] = set()
    for flat, obj in norm.items():
        domain, key = _split(flat)
        active = bool(obj.get("has"))
        seen_pairs.add((domain, key))
        row = existing.get((domain, key))
        if row:
            row.active = active
            row.updated_at_utc = now
        else:
            db.session.add(
                ResourceCapabilityIndex(
                    resource_ulid=resource_ulid,
                    domain=domain,
                    key=key,
                    active=active,
                    updated_at_utc=now,
                )
            )
    # 3) Remove projection rows that are no longer present
    for (domain, key), row in existing.items():
        if (domain, key) not in seen_pairs:
            db.session.delete(row)

    # Update Resource ops flags
    res.capability_last_update_utc = now
    res.last_touch_utc = now

    # Admin review: true when meta.unclassified is active
    res.admin_review_required = "meta.unclassified" in after_active

    # Auto bump readiness: if no 'unclassified' and previously draft, move to 'review'
    if not res.admin_review_required and res.readiness_status == "draft":
        res.readiness_status = "review"

    db.session.commit()

    # Emit names-only ledger events with pointer (values never leave History)
    for flat in added:
        domain, key = _split(flat)
        event_bus.emit(
            domain="resources",
            operation="capability_add",
            actor_ulid=actor_id,
            target_ulid=resource_ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"domain": domain, "key": key, "version_ptr": hist.ulid},
        )
    for flat in removed:
        domain, key = _split(flat)
        event_bus.emit(
            domain="resources",
            operation="capability_remove",
            actor_ulid=actor_id,
            target_ulid=resource_ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"domain": domain, "key": key, "version_ptr": hist.ulid},
        )

    return hist.ulid


# ----------- views / search -------------


def resource_view(resource_ulid: str) -> Optional[dict]:
    r = db.session.get(Resource, resource_ulid)
    if not r:
        return None
    caps = (
        db.session.query(ResourceCapabilityIndex)
        .filter_by(resource_ulid=resource_ulid, active=True)
        .all()
    )
    return {
        "resource_ulid": r.ulid,
        "entity_ulid": r.entity_ulid,
        "admin_review_required": r.admin_review_required,
        "readiness_status": r.readiness_status,
        "mou_status": r.mou_status,
        "active_capabilities": [
            {"domain": c.domain, "key": c.key} for c in caps
        ],
        "capability_last_update_utc": r.capability_last_update_utc,
        "first_seen_utc": r.first_seen_utc,
        "last_touch_utc": r.last_touch_utc,
        "created_at_utc": r.created_at_utc,
        "updated_at_utc": r.updated_at_utc,
    }


def find_resources(
    *,
    any_of: Optional[list[tuple[str, str]]] = None,  # OR of (domain, key)
    all_of: Optional[list[tuple[str, str]]] = None,  # AND of (domain, key)
    admin_review_required: Optional[bool] = None,
    readiness_in: Optional[list[str]] = None,
    page: int = 1,
    per: int = 50,
) -> tuple[list[dict], int]:
    """
    Search by capability keys quickly via the projection table.
    """
    q = db.session.query(Resource)

    # Join to projection as needed
    if any_of:
        from sqlalchemy import or_, and_

        ors = []
        for d, k in any_of:
            ors.append(
                db.session.query(ResourceCapabilityIndex.resource_ulid)
                .filter_by(domain=d, key=k, active=True)
                .with_entities(ResourceCapabilityIndex.resource_ulid)
            )
        # filter Resource.ulid IN union of ors
        sub_ids = set()
        for sub in ors:
            sub_ids.update([row[0] for row in sub.all()])
        if sub_ids:
            q = q.filter(Resource.ulid.in_(list(sub_ids)))
        else:
            return [], 0

    if all_of:
        # for AND, chain filters
        for d, k in all_of:
            q = q.join(
                ResourceCapabilityIndex,
                ResourceCapabilityIndex.resource_ulid == Resource.ulid,
            ).filter(
                ResourceCapabilityIndex.domain == d,
                ResourceCapabilityIndex.key == k,
                ResourceCapabilityIndex.active.is_(True),
            )

    if admin_review_required is not None:
        q = q.filter(
            Resource.admin_review_required.is_(bool(admin_review_required))
        )
    if readiness_in:
        q = q.filter(Resource.readiness_status.in_(list(set(readiness_in))))

    total = q.count()
    rows = (
        q.order_by(Resource.updated_at_utc.desc())
        .offset((page - 1) * per)
        .limit(per)
        .all()
    )
    return [resource_view(r.ulid) for r in rows], total


# ---- constants for status enums ----
READINESS_ALLOWED = {"draft", "review", "active", "suspended"}
MOU_ALLOWED = {"none", "pending", "active", "expired", "terminated"}


def set_readiness_status(
    *, resource_ulid: str, status: str, request_id: str, actor_id: str | None
) -> None:
    """Set readiness_status with validation and emit a names-only ledger event."""
    _ensure_reqid(request_id)
    status = (status or "").strip().lower()
    if status not in READINESS_ALLOWED:
        raise ValueError(f"invalid readiness_status '{status}'")

    r = db.session.get(Resource, resource_ulid)
    if not r:
        raise ValueError("resource not found")

    prev = r.readiness_status
    if prev == status:
        return

    r.readiness_status = status
    r.last_touch_utc = now_iso8601_ms()
    db.session.commit()

    event_bus.emit(
        domain="resources",
        operation="readiness_update",
        actor_ulid=actor_id,
        target_ulid=resource_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        changed_fields={"readiness_status": status, "prev": prev},
    )


def set_mou_status(
    *, resource_ulid: str, status: str, request_id: str, actor_id: str | None
) -> None:
    """Set MOU status with validation and emit a names-only ledger event."""
    _ensure_reqid(request_id)
    status = (status or "").strip().lower()
    if status not in MOU_ALLOWED:
        raise ValueError(f"invalid mou_status '{status}'")

    r = db.session.get(Resource, resource_ulid)
    if not r:
        raise ValueError("resource not found")

    prev = r.mou_status
    if prev == status:
        return

    r.mou_status = status
    r.last_touch_utc = now_iso8601_ms()
    db.session.commit()

    event_bus.emit(
        domain="resources",
        operation="mou_update",
        actor_ulid=actor_id,
        target_ulid=resource_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        changed_fields={"mou_status": status, "prev": prev},
    )


def rebuild_capability_index(
    *, resource_ulid: str, request_id: str, actor_id: str | None
) -> int:
    """
    Rebuild the projection table from the latest History snapshot.
    Returns number of index rows after rebuild.
    """
    _ensure_reqid(request_id)

    r = db.session.get(Resource, resource_ulid)
    if not r:
        raise ValueError("resource not found")

    snapshot = _latest_snapshot(resource_ulid)
    now = now_iso8601_ms()

    # wipe and recreate for deterministic state
    db.session.query(ResourceCapabilityIndex).filter_by(
        resource_ulid=resource_ulid
    ).delete()

    count = 0
    for flat, obj in snapshot.items():
        domain, key = _split(flat)
        active = bool(obj.get("has"))
        db.session.add(
            ResourceCapabilityIndex(
                resource_ulid=resource_ulid,
                domain=domain,
                key=key,
                active=active,
                updated_at_utc=now,
            )
        )
        count += 1

    r.last_touch_utc = now
    r.capability_last_update_utc = now
    db.session.commit()

    event_bus.emit(
        domain="resources",
        operation="capability_rebuild",
        actor_ulid=actor_id,
        target_ulid=resource_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"rows": count},
    )
    return count


def promote_readiness_if_clean(
    *, resource_ulid: str, request_id: str, actor_id: str | None
) -> bool:
    """
    Convenience: if no 'meta.unclassified' and currently 'review', promote to 'active'.
    Returns True if promoted.
    """
    _ensure_reqid(request_id)
    r = db.session.get(Resource, resource_ulid)
    if not r:
        raise ValueError("resource not found")

    latest = _latest_snapshot(resource_ulid)
    has_unclassified = bool(
        latest.get("meta.unclassified", {}).get("has") is True
    )
    if not has_unclassified and r.readiness_status == "review":
        set_readiness_status(
            resource_ulid=resource_ulid,
            status="active",
            request_id=request_id,
            actor_ulid=actor_id,
        )
        return True
    return False


# ---- Patch semantics (merge into latest snapshot) --------------------------


def _merge_snapshot(
    latest: dict[str, dict], patch: dict[str, dict]
) -> dict[str, dict]:
    """
    For each provided key:
      - ensures it exists/validates
      - updates 'has' and/or 'note' (if provided)
    Keys not present in patch remain unchanged.
    """
    merged = {k: dict(v) for k, v in latest.items()}
    for flat, obj in patch.items():
        domain, key = _split(flat)
        # _validate_payload() already verified the key and normalized fields
        if flat not in merged:
            merged[flat] = {}
        if "has" in obj:
            merged[flat]["has"] = bool(obj["has"])
        if "note" in obj:
            note = obj["note"]
            if note is None or str(note).strip() == "":
                merged[flat].pop("note", None)
            else:
                merged[flat]["note"] = str(note)[:NOTE_MAX]
    return merged


def patch_capabilities(
    *,
    resource_ulid: str,
    payload: dict[
        str, dict
    ],  # subset of "domain.key": {"has"?: bool, "note"?: str|null}
    request_id: str,
    actor_id: str | None,
) -> str | None:
    """
    PATCH semantics: update only provided keys; others remain as-is.
    - Validates keys
    - Computes deltas (names-only)
    - Writes ResourceHistory if there is any change
    - Updates projection accordingly
    - Emits names-only ledger events for added/removed
    Returns history_ulid if a new version was created, else None (no change).
    """
    _ensure_reqid(request_id)

    res = db.session.get(Resource, resource_ulid)
    if not res:
        raise ValueError("resource not found")

    norm_patch = _validate_payload(
        payload
    )  # same validator; it requires "has" in each item
    latest = _latest_snapshot(resource_ulid)
    merged = _merge_snapshot(latest, norm_patch)

    if stable_dumps(merged) == stable_dumps(latest):
        # no effective change
        res.last_touch_utc = now_iso8601_ms()
        db.session.commit()
        return None

    # deltas
    before_active = {k for k, v in latest.items() if v.get("has") is True}
    after_active = {k for k, v in merged.items() if v.get("has") is True}
    added = sorted(after_active - before_active)
    removed = sorted(before_active - after_active)

    # write history
    version = _next_version(resource_ulid)
    hist = ResourceHistory(
        resource_ulid=resource_ulid,
        section=SECTION,
        version=version,
        data_json=stable_dumps(merged),
        created_by_actor=actor_id,
    )
    db.session.add(hist)

    # update projection (only touched keys)
    now = now_iso8601_ms()
    # 1) upsert keys from patch payload
    for flat, obj in norm_patch.items():
        domain, key = _split(flat)
        active = bool(obj.get("has"))
        row = (
            db.session.query(ResourceCapabilityIndex)
            .filter_by(resource_ulid=resource_ulid, domain=domain, key=key)
            .first()
        )
        if row:
            row.active = active
            row.updated_at_utc = now
        else:
            db.session.add(
                ResourceCapabilityIndex(
                    resource_ulid=resource_ulid,
                    domain=domain,
                    key=key,
                    active=active,
                    updated_at_utc=now,
                )
            )
    # 2) if any key became inactive and we want strict replace of its presence, leave row with active=False
    #    (no deletion here, unlike replace semantics which removes unknown rows)

    # update resource ops
    res.last_touch_utc = now
    res.capability_last_update_utc = now
    res.admin_review_required = "meta.unclassified" in after_active
    if not res.admin_review_required and res.readiness_status == "draft":
        res.readiness_status = "review"

    db.session.commit()

    # emit names-only deltas
    for flat in added:
        d, k = _split(flat)
        event_bus.emit(
            domain="resources",
            operation="classification_add",
            actor_ulid=actor_id,
            target_ulid=resource_ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )
    for flat in removed:
        d, k = _split(flat)
        event_bus.emit(
            domain="resources",
            operation="classification_remove",
            actor_ulid=actor_id,
            target_ulid=resource_ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )

    return hist.ulid


# ---- Batch rebuild (maintenance / recovery) --------------------------------


def rebuild_all_capability_indexes(
    *, page: int = 1, per: int = 200, request_id: str, actor_id: str | None
) -> dict:
    """
    Rebuild the projection for a page of resources (safety-limited).
    Returns {"processed": N, "reindexed": total_rows, "page": page, "per": per}
    """
    _ensure_reqid(request_id)
    per = max(1, min(int(per or 200), 500))  # safety cap 500

    q = (
        db.session.query(Resource.ulid)
        .order_by(Resource.created_at_utc.asc())
        .offset((int(page or 1) - 1) * per)
        .limit(per)
    )
    ids = [row[0] for row in q.all()]
    total_rows = 0
    for rid in ids:
        total_rows += (
            rebuild_capability_index(
                resource_ulid=rid, request_id=request_id, actor_ulid=actor_id
            )
            or 0
        )
    return {
        "processed": len(ids),
        "reindexed": total_rows,
        "page": int(page or 1),
        "per": per,
    }
