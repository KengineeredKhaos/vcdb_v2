# app/slices/resources/services.py
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import desc, func

from app.extensions import db, event_bus
from app.extensions.contracts import entity_v2
from app.extensions.errors import ContractError
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps
from app.services import poc as poc_svc
from app.services.entity_validate import require_person_entity_ulid
from app.slices.resources.models import (
    Resource,
    ResourceCapabilityIndex,
    ResourceHistory,
    ResourcePOC,
)

# -----------------
# Constants & conventions
# -----------------

CAPS_SECTION = "resource:capability:v1"
POC_RELATION = "poc"  # table-level convention, not board policy
_RESOURCE_POC_SPEC = poc_svc.POCSpec(owner_col="resource_ulid")


# -----------------
# Policy access (lazy imports)
# -----------------


def _poc_policy() -> dict:
    from app.extensions.contracts import governance_v2

    return governance_v2.get_poc_policy()


def _caps_policy():
    from app.extensions.contracts import governance_v2

    return governance_v2.get_resource_capabilities_policy()


def _lifecycle_policy() -> dict:
    from app.extensions.contracts import governance_v2

    return governance_v2.get_resource_lifecycle_policy()


# -----------------
# Contract Error
# normalization
# -----------------


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    # If we’re already looking at a ContractError, just bubble it up unchanged
    if isinstance(exc, ContractError):
        return exc

    msg = str(exc) or exc.__class__.__name__

    if isinstance(exc, ValueError):
        return ContractError(
            code="bad_argument",
            where=where,
            message=msg,
            http_status=400,
        )
    if isinstance(exc, PermissionError):
        return ContractError(
            code="permission_denied",
            where=where,
            message=msg,
            http_status=403,
        )
    if isinstance(exc, LookupError):
        return ContractError(
            code="not_found",
            where=where,
            message=msg,
            http_status=404,
        )

    # Fallback: unexpected system/runtime error
    return ContractError(
        code="internal_error",
        where=where,
        message="unexpected error in contract; see logs",
        http_status=500,
        data={"exc_type": exc.__class__.__name__},
    )


# -----------------
# Help for POC Validation
# thru Entity contract
# -----------------


def _require_person_entity_ulid(
    person_entity_ulid: str, *, where: str
) -> None:
    core = entity_v2.get_entity_core(db.session, person_entity_ulid)

    if core.kind != "person":
        raise ContractError(
            code="bad_request",
            where=where,
            message=f"person_entity_ulid must be a person entity (got kind='{core.kind}')",
            http_status=400,
            data={"entity_ulid": person_entity_ulid, "kind": core.kind},
        )

    if core.archived_at:
        raise ContractError(
            code="conflict",
            where=where,
            message="person entity is archived",
            http_status=409,
            data={
                "entity_ulid": person_entity_ulid,
                "archived_at": core.archived_at,
            },
        )


# -----------------
# Point of Contact
# wrappers for
# app.services.poc
# -----------------


def resource_link_poc(
    *,
    resource_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int = 0,
    is_primary: bool = False,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    require_person_entity_ulid(
        db.session,
        person_entity_ulid,
        where="resources.resource_link_poc",
    )
    return poc_svc.link_poc(
        db.session,
        POCModel=ResourcePOC,
        spec=_RESOURCE_POC_SPEC,
        domain="resources",
        owner_ulid=resource_ulid,
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
    resource_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int | None = None,
    is_primary: bool | None = None,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    require_person_entity_ulid(
        db.session,
        person_entity_ulid,
        where="resources.resource_link_poc",
    )
    return poc_svc.update_poc(
        db.session,
        POCModel=ResourcePOC,
        spec=_RESOURCE_POC_SPEC,
        domain="resources",
        owner_ulid=resource_ulid,
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
    resource_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    require_person_entity_ulid(
        db.session,
        person_entity_ulid,
        where="resources.resource_link_poc",
    )
    return poc_svc.unlink_poc(
        db.session,
        POCModel=ResourcePOC,
        spec=_RESOURCE_POC_SPEC,
        domain="resources",
        owner_ulid=resource_ulid,
        person_entity_ulid=person_entity_ulid,
        scope=scope,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def resource_list_pocs(*, resource_ulid: str) -> list[dict]:
    return poc_svc.list_pocs(
        db.session,
        POCModel=ResourcePOC,
        spec=_RESOURCE_POC_SPEC,
        owner_ulid=resource_ulid,
    )


# -----------------
# Helpers: validation
# -----------------


def _ensure_reqid(rid: Optional[str]) -> str:
    if not rid or not str(rid).strip():
        raise ValueError("request_id must be non-empty")
    return str(rid).strip()


# -----------------
# Helpers: capability history snapshots
# -----------------


def _latest_snapshot(resource_ulid: str) -> dict[str, dict]:
    h = (
        db.session.query(ResourceHistory)
        .filter_by(resource_ulid=resource_ulid, section=CAPS_SECTION)
        .order_by(desc(ResourceHistory.version))
        .first()
    )
    return json.loads(h.data_json) if h else {}


def _next_version(
    resource_ulid: str,
) -> int:
    cur = (
        db.session.query(func.max(ResourceHistory.version))
        .filter_by(resource_ulid=resource_ulid, section=CAPS_SECTION)
        .scalar()
    )
    return int(cur or 0) + 1


# -----------------
# Helpers: capability payload normalization/validation
# -----------------


def _split(flat_key: str) -> tuple[str, str]:
    if "." not in flat_key:
        raise ValueError(
            f"invalid classification key '{flat_key}'; expected 'domain.key'"
        )
    domain, key = flat_key.split(".", 1)
    domain = domain.strip()
    key = key.strip()
    if not domain or not key:
        raise ValueError(
            f"invalid classification key '{flat_key}'; expected 'domain.key'"
        )
    return domain, key


def _flatten_caps_payload(
    payload: dict[str, object],
) -> dict[str, dict[str, object]]:
    """
    Normalise capability payload into flat keys.

    Accepts:
      1) Flat:   {"basic_needs.food_pantry": true, ...}
      2) Nested: {"basic_needs": {"food_pantry": true, ...}, ...}

    Returns:
      { "<domain>.<code>": {"has": bool, "note": str?}, ... }
    """
    flat: dict[str, dict[str, object]] = {}
    if not payload:
        return flat

    policy = _caps_policy()
    note_max = int(policy.note_max)

    for key, value in payload.items():
        key = str(key).strip()

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
            domain, code = _split(str(flat_key))
            norm_key = f"{domain}.{code}"

            if isinstance(obj, bool):
                flat[norm_key] = {"has": bool(obj)}
                continue

            if isinstance(obj, dict):
                out: dict[str, object] = {}

                # has defaults True when omitted but other fields exist
                out["has"] = bool(obj.get("has", True))

                note_raw = obj.get("note")
                if note_raw is not None:
                    note = str(note_raw).strip()
                    if note:
                        out["note"] = note[:note_max]

                flat[norm_key] = out
                continue

            raise ValueError("invalid capability payload value")

    return flat


def _validate_caps(
    payload: dict[str, object]
) -> dict[str, dict[str, object]]:
    """
    Validate and normalise a capability payload against Board policy.

    - Accepts nested/flat shapes.
    - Ensures every capability is allowed by policy.
    - Trims note fields to policy.note_max.

    Returns:
        { "domain.code": {"has": bool, "note": str?}, ... }
    """
    # NOTE: keep copy-shaped with sponsors/resources _validate_caps()

    flat = _flatten_caps_payload(payload)
    if not flat:
        return flat

    caps = _caps_policy()
    allowed = set(caps.all_codes)
    note_max = caps.note_max

    norm: dict[str, dict[str, object]] = {}
    for flat_key, obj in flat.items():
        if flat_key not in allowed:
            raise ValueError(f"unknown capability '{flat_key}'")

        if not isinstance(obj, dict):
            raise ValueError(f"invalid payload for '{flat_key}'")

        out: dict[str, object] = {"has": bool(obj.get("has", True))}

        note = obj.get("note")
        if note is not None:
            note_str = str(note).strip()
            if note_str:
                out["note"] = note_str[:note_max]

        norm[flat_key] = out

    return norm


# -----------------
# Policy-backed helpers (Board policy via Governance)
# -----------------


def allowed_capability_codes() -> list[str]:
    caps = _caps_policy()
    return sorted(caps.all_codes)


def readiness_allowed() -> set[str]:
    pol = _lifecycle_policy()
    return set(pol["readiness_allowed"])


def mou_allowed() -> set[str]:
    pol = _lifecycle_policy()
    return set(pol["mou_allowed"])


def note_max() -> int:
    caps = _caps_policy()
    return int(caps.note_max)


def _default_readiness() -> str:
    pol = _lifecycle_policy()
    return str(pol["readiness_allowed"][0])


def _default_mou() -> str:
    pol = _lifecycle_policy()
    return str(pol["mou_allowed"][0])


# -----------------
# core API
# ------------------


def ensure_resource(
    *, entity_ulid: str, request_id: str, actor_ulid: Optional[str]
) -> str:
    _ensure_reqid(request_id)

    r = db.session.query(Resource).filter_by(entity_ulid=entity_ulid).first()
    now = now_iso8601_ms()

    if not r:
        r = Resource(
            entity_ulid=entity_ulid,
            first_seen_utc=now,
            last_touch_utc=now,
            readiness_status=_default_readiness(),
            mou_status=_default_mou(),
        )
        db.session.add(r)
        db.session.commit()

        event_bus.emit(
            domain="resources",
            operation="created_insert",
            actor_ulid=actor_ulid,
            target_ulid=r.ulid,
            request_id=request_id,
            happened_at_utc=now,
            refs={"entity_ulid": entity_ulid},
        )
        return r.ulid

    r.last_touch_utc = now
    db.session.commit()
    return r.ulid


def upsert_capabilities(
    *,
    resource_ulid: str,
    payload: dict[str, Any],
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
        section=CAPS_SECTION,
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
    “optimize later” (SQL UNION / exists / group by having count patterns)
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


# -----------------
# Readiness/MOU helpers
# -----------------


def set_readiness_status(
    *,
    resource_ulid: str,
    status: str,
    actor_ulid: str | None,
    request_id: str,
) -> None:
    _ensure_reqid(request_id)
    status = (status or "").strip().lower()

    allowed = readiness_allowed()
    if status not in allowed:
        raise ValueError(f"invalid readiness_status '{status}'")

    res = db.session.get(Resource, resource_ulid)
    if not res:
        raise ValueError("resource not found")

    if res.readiness_status == status:
        return

    prev = res.readiness_status
    now = now_iso8601_ms()
    res.readiness_status = status
    res.last_touch_utc = now
    db.session.commit()

    event_bus.emit(
        domain="resources",
        operation="readiness_update",
        actor_ulid=actor_ulid,
        target_ulid=resource_ulid,
        request_id=request_id,
        happened_at_utc=now,
        changed={"readiness_status": status, "prev": prev},
    )


def set_mou_status(
    *,
    resource_ulid: str,
    status: str,
    actor_ulid: str | None,
    request_id: str,
) -> None:
    _ensure_reqid(request_id)
    status = (status or "").strip().lower()

    allowed = mou_allowed()
    if status not in allowed:
        raise ValueError(f"invalid mou_status '{status}'")

    res = db.session.get(Resource, resource_ulid)
    if not res:
        raise ValueError("resource not found")

    if res.mou_status == status:
        return

    prev = res.mou_status
    now = now_iso8601_ms()
    res.mou_status = status
    res.last_touch_utc = now
    db.session.commit()

    event_bus.emit(
        domain="resources",
        operation="mou_update",
        actor_ulid=actor_ulid,
        target_ulid=resource_ulid,
        request_id=request_id,
        happened_at_utc=now,
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
        happened_at_utc=now,
        refs={"rows": count},
    )
    return count


def promote_readiness_if_clean(
    *, resource_ulid: str, request_id: str, actor_ulid: str | None
) -> bool:
    """
    Convenience: if no 'meta.unclassified' and currently 'review',
    promote to 'active'.
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
        section=CAPS_SECTION,
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
            happened_at_utc=now_iso8601_ms,
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
