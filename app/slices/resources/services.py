# app/slices/resources/services.py
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session

from app.extensions import db, event_bus
from app.extensions.contracts.governance_v2 import (
    get_poc_policy,
    get_resource_capabilities_policy,
    get_resource_lifecycle_policy,
)
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps
from app.services import poc as poc_svc
from app.slices.resources.models import (
    Resource,
    ResourceCapabilityIndex,
    ResourceHistory,
    ResourcePOC,
)

# -----------------
# Controlled
# Vocabulary
# (MVP)
# -----------------

SECTION = "resource:capability:v1"
POC_RELATION = "poc"  # table-level convention, not board policy


# -----------------
# Point of Contact
# wrappers for
# app.services.poc
# -----------------


def resource_link_poc(
    *,
    org_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int = 0,
    is_primary: bool = False,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    return poc_svc.link_poc(
        db.session,
        POCModel=ResourcePOC,
        domain="resources",
        org_ulid=org_ulid,
        person_entity_ulid=person_entity_ulid,
        scope=scope,
        rank=rank,
        is_primary=is_primary,
        window=window,
        org_role=org_role,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def resource_update_poc(
    *,
    org_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int | None = None,
    is_primary: bool | None = None,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    return poc_svc.update_poc(
        db.session,
        POCModel=ResourcePOC,
        domain="resources",
        org_ulid=org_ulid,
        person_entity_ulid=person_entity_ulid,
        scope=scope,
        rank=rank,
        is_primary=is_primary,
        window=window,
        org_role=org_role,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def resource_unlink_poc(
    *,
    org_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    return poc_svc.unlink_poc(
        db.session,
        POCModel=ResourcePOC,
        domain="resources",
        org_ulid=org_ulid,
        person_entity_ulid=person_entity_ulid,
        scope=scope,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def resource_list_pocs(*, org_ulid: str) -> list[dict]:
    return poc_svc.list_pocs(
        db.session, POCModel=ResourcePOC, org_ulid=org_ulid
    )


# ---------------- helpers ----------------


def _ensure_reqid(rid: Optional[str]) -> str:
    if not rid or not str(rid).strip():
        raise ValueError("request_id must be non-empty")
    return str(rid)


def _resource_caps_policy():
    """
    Thin wrapper so the rest of this module doesn’t care where policy lives.
    Returns the ResourceCapsPolicy DTO from governance_v2.
    """
    return get_resource_capabilities_policy()


def allowed_resource_capability_codes() -> list[str]:
    """
    Convenience: all <domain>.<code> capability keys from Board policy,
    sorted for U.I. / CLI use.
    """
    policy = _resource_caps_policy()
    return sorted(policy.all_codes)


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


def _split(flat_key: str) -> tuple[str, str]:
    if "." not in flat_key:
        raise ValueError(
            f"invalid classification key '{flat_key}'; expected 'domain.key'"
        )
    domain, key = flat_key.split(".", 1)
    return domain.strip(), key.strip()


def _flatten_caps_payload(
    payload: dict[str, object],
) -> dict[str, dict[str, object]]:
    """
    Normalise capability payload into flat keys.

    Accepts two shapes:

      1) Flat:
         {
             "basic_needs.food_pantry": true,
             "housing.rent_assistance": {"has": false, "note": "..." },
         }

      2) Nested:
         {
             "basic_needs": {
                 "food_pantry": true,
                 "clothing": {"has": true, "note": "Seasonal drive"},
             },
             "housing": {
                 "rent_assistance": {"has": false},
             },
         }

    Returns a mapping of flat keys to objects of the form:
        { "<domain>.<code>": {"has": bool, "note": str?}, ... }
    """
    flat: dict[str, dict[str, object]] = {}
    if not payload:
        return flat

    policy = _resource_caps_policy()
    note_max = policy.note_max

    for key, value in payload.items():
        # Shape 1: already "domain.code"
        if "." in key:
            items = [(key, value)]
        else:
            # Shape 2: nested by domain
            domain = key
            if not isinstance(value, dict):
                raise ValueError(
                    "nested capabilities must be objects per domain"
                )
            items = [(f"{domain}.{sub}", sv) for sub, sv in value.items()]

        for flat_key, obj in items:
            if isinstance(obj, bool):
                flat[flat_key] = {"has": bool(obj)}
            elif isinstance(obj, dict):
                out: dict[str, object] = {}
                if "has" in obj:
                    out["has"] = bool(obj["has"])
                else:
                    # default has=True if omitted but something else is present
                    out["has"] = True
                note_raw = obj.get("note")
                if note_raw is not None:
                    note = str(note_raw).strip()
                    if note:
                        out["note"] = note[:note_max]
                flat[flat_key] = out
            else:
                raise ValueError("invalid capability payload value")

    return flat


def _validate_caps(
    payload: dict[str, object],
) -> dict[str, dict[str, object]]:
    """
    Validate and normalise a resource capability payload against Board policy.

    - Normalises nested/flat payload shapes.
    - Ensures every capability code is in policy_resource_capabilities.json.
    - Trims note fields to policy.note_max chars.

    Returns a dict keyed by flat capability code, for example:

        {
          "basic_needs.food_pantry": {"has": True, "note": "Staffed weekly"},
          "housing.rent_assistance": {"has": False},
        }
    """
    flat = _flatten_caps_payload(payload)
    if not flat:
        return flat

    policy = _resource_caps_policy()
    allowed = set(policy.all_codes)

    norm: dict[str, dict[str, object]] = {}
    for flat_key, obj in flat.items():
        domain, code = _split(flat_key)
        if flat_key not in allowed:
            raise ValueError(f"unknown capability '{domain}.{code}'")

        if not isinstance(obj, dict):
            raise ValueError(f"invalid payload for '{flat_key}'")

        has = bool(obj.get("has", True))
        note = obj.get("note")
        out: dict[str, object] = {"has": has}
        if note is not None:
            note_str = str(note).strip()
            if note_str:
                out["note"] = note_str[: policy.note_max]
        norm[flat_key] = out

    return norm


def _resource_lifecycle_policy():
    """
    Governance Board policy for resource readiness & MOU lifecycle.
    """
    return get_resource_lifecycle_policy()


# -----------------
# Policy-backed helpers
# (Board Policy
# via Governance)
# -----------------


def _caps_policy():
    """
    Board policy: resource capabilities & taxonomy.

    Backed by `policy_resource_capabilities.json` / Policy table via
    governance_v2.get_resource_capabilities_policy().
    """
    return get_resource_capabilities_policy()


def _lifecycle_policy() -> dict:
    """
    Board policy: resource readiness + MOU vocab.

    Backed by `policy_resource_lifecycle.json` / Policy table via
    governance_v2.get_resource_lifecycle_policy().
    """
    return get_resource_lifecycle_policy()


def all_classification_codes() -> list[str]:
    """
    Flattened 'domain.key' codes from the capabilities policy.

    Replaces the old CLASSIFICATIONS constant.
    """
    caps = _caps_policy()
    # caps is a ResourceCapsPolicy dataclass with .all_codes property
    return sorted(caps.all_codes)


def readiness_allowed() -> set[str]:
    """
    Allowed readiness states for Resource.readiness_status.

    Replaces READINESS_ALLOWED constant.
    """
    pol = _lifecycle_policy()
    return set(pol["readiness_allowed"])


def mou_allowed() -> set[str]:
    """
    Allowed MOU states for Resource.mou_status.

    Replaces MOU_ALLOWED constant.
    """
    pol = _lifecycle_policy()
    return set(pol["mou_allowed"])


def note_max() -> int:
    """
    Max length for capability notes; replaces NOTE_MAX constant.
    """
    caps = _caps_policy()
    return int(caps.note_max)


# -----------------
# core API
# ------------------


def ensure_resource(
    *, entity_ulid: str, request_id: str, actor_ulid: Optional[str]
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
            actor_ulid=actor_ulid,
            target_ulid=r.ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"entity_ulid": entity_ulid},
        )
    else:
        r.last_touch_utc = now_iso8601_ms()
        db.session.commit()
    return r.ulid


def allowed_capabilities() -> list[str]:
    """
    Returns canonical capability keys like 'basic_needs.food_pantry'.
    Useful for seeds/tools; read-only, PII-free.
    """
    return allowed_resource_capability_codes()


def upsert_capabilities(
    *,
    resource_ulid: str,
    payload: Dict[str, Any],
    request_id: str,
    actor_ulid: Optional[str],
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

    norm = _validate_caps(payload)

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
        created_by_actor=actor_ulid,
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
            actor_ulid=actor_ulid,
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
            actor_ulid=actor_ulid,
            target_ulid=resource_ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"domain": domain, "key": key, "version_ptr": hist.ulid},
        )

    return hist.ulid


def _normalize_policy(
    scope: Optional[str], rank: Optional[int]
) -> tuple[str, int, dict]:
    policy = get_poc_policy()
    scopes = policy["poc_scopes"]
    default = policy["default_scope"]
    max_rank = policy["max_rank"]

    norm_scope = scope or default
    if norm_scope not in scopes:
        raise ValueError("invalid scope")
    norm_rank = rank if rank is not None else 0
    if not (0 <= norm_rank <= max_rank):
        raise ValueError("invalid rank")
    return norm_scope, norm_rank, policy


def _enforce_primary(
    sess: Session, org_ulid: str, scope: str, is_primary: bool
):
    if not is_primary:
        return
    # Flip any existing primary for same (org, relation, scope)
    sess.query(ResourcePOC).filter(
        and_(
            ResourcePOC.org_ulid == org_ulid,
            ResourcePOC.relation == POC_RELATION,
            ResourcePOC.scope == scope,
            ResourcePOC.is_primary == True,  # noqa: E712
        )
    ).update({"is_primary": False}, synchronize_session=False)


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


def set_readiness_status(
    *,
    resource_ulid: str,
    status: str,
    actor_ulid: Optional[str],
    request_id: str,
) -> None:
    _ensure_reqid(request_id)
    policy = _resource_lifecycle_policy()

    if status not in policy.readiness_states:
        raise ValueError(f"invalid readiness_status '{status}'")

    res = db.session.get(Resource, resource_ulid)
    if not res:
        raise ValueError("resource not found")

    prev = res.readiness_status
    res.readiness_status = status
    res.last_touch_utc = now_iso8601_ms()
    db.session.commit()
    # (emit ledger event as you already do)

    event_bus.emit(
        domain="resources",
        operation="readiness_update",
        actor_ulid=actor_ulid,
        target_ulid=resource_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        changed={"readiness_status": status, "prev": prev},
    )


def set_mou_status(
    *,
    resource_ulid: str,
    status: str,
    actor_ulid: Optional[str],
    request_id: str,
) -> None:
    _ensure_reqid(request_id)
    policy = _resource_lifecycle_policy()

    if status not in policy.mou_states:
        raise ValueError(f"invalid mou_status '{status}'")

    res = db.session.get(Resource, resource_ulid)
    if not res:
        raise ValueError("resource not found")

    prev = res.readiness_status
    res.mou_status = status
    res.last_touch_utc = now_iso8601_ms()
    db.session.commit()
    # (emit ledger event as you already do)

    event_bus.emit(
        domain="resources",
        operation="mou_update",
        actor_ulid=actor_ulid,
        target_ulid=resource_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        changed={"mou_status": status, "prev": prev},
    )


def rebuild_capability_index(
    *, resource_ulid: str, request_id: str, actor_ulid: str | None
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
        actor_ulid=actor_ulid,
        target_ulid=resource_ulid,
        request_id=request_id,
        happened_at_utc=now_iso8601_ms(),
        refs={"rows": count},
    )
    return count


def promote_readiness_if_clean(
    *, resource_ulid: str, request_id: str, actor_ulid: str | None
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
            actor_ulid=actor_ulid,
        )
        return True
    return False


# ---- Patch semantics (merge into latest snapshot) --------------------------


def _merge_snapshot(
    latest: dict[str, dict], patch: dict[str, dict]
) -> dict[str, dict]:
    """
    For each provided key:
      - assumes key is valid and values are normalised by _validate_caps()
      - updates 'has' and/or 'note' (if provided)
    Keys not present in patch remain unchanged.
    """
    merged = {k: dict(v) for k, v in latest.items()}
    for flat, obj in patch.items():
        if flat not in merged:
            merged[flat] = {}
        if "has" in obj:
            merged[flat]["has"] = bool(obj["has"])
        if "note" in obj:
            note = obj["note"]
            if note is None or str(note).strip() == "":
                merged[flat].pop("note", None)
            else:
                # already trimmed by _validate_caps
                merged[flat]["note"] = str(note)
    return merged


def patch_capabilities(
    *,
    resource_ulid: str,
    payload: dict[
        str, dict
    ],  # subset of "domain.key": {"has"?: bool, "note"?: str|null}
    request_id: str,
    actor_ulid: str | None,
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

    norm_patch = _validate_caps(payload)
    # same validator; it requires "has" in each item
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
        created_by_actor=actor_ulid,
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
            operation="capability_add",
            actor_ulid=actor_ulid,
            target_ulid=resource_ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )
    for flat in removed:
        d, k = _split(flat)
        event_bus.emit(
            domain="resources",
            operation="capability_remove",
            actor_ulid=actor_ulid,
            target_ulid=resource_ulid,
            request_id=request_id,
            happened_at_utc=now_iso8601_ms(),
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )

    return hist.ulid


# ---- Batch rebuild (maintenance / recovery) --------------------------------


def rebuild_all_capability_indexes(
    *, page: int = 1, per: int = 200, request_id: str, actor_ulid: str | None
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
                resource_ulid=rid,
                request_id=request_id,
                actor_ulid=actor_ulid,
            )
            or 0
        )
    return {
        "processed": len(ids),
        "reindexed": total_rows,
        "page": int(page or 1),
        "per": per,
    }
