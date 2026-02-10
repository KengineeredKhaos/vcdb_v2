# app/slices/resources/services.py
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import desc, func

from app.extensions import db, event_bus
from app.extensions.contracts import entity_v2
from app.extensions.errors import ContractError
from app.lib.chrono import now_iso8601_ms
from app.lib.jsonutil import stable_dumps
from app.slices.entity import services_poc as poc_svc
from app.slices.resources.mapper import (
    ResourcePOCView,
    ResourceView,
    map_resource_poc_list,
    map_resource_view,
)
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
_RESOURCE_POC_SPEC = poc_svc.POCSpec(owner_col="resource_entity_ulid")

# -----------------
# Policy access (lazy imports)
# -----------------


def _poc_policy() -> dict:
    from app.extensions.contracts import governance_v2

    return governance_v2.get_poc_policy()


def _caps_policy() -> Any:
    """
    Governance-backed resource capabilities policy.

    We tolerate both dict and attribute-style objects coming back from Governance.
    Required fields:
      - all_codes: iterable[str] of "domain.key" codes
      - note_max: int
    """
    from app.extensions.contracts import governance_v2

    return governance_v2.get_resource_capabilities_policy()


def _lifecycle_policy() -> dict:
    from app.extensions.contracts import governance_v2

    return governance_v2.get_resource_lifecycle_policy()


def _pol_get(pol: Any, key: str, default: Any = None) -> Any:
    if pol is None:
        return default
    if isinstance(pol, dict):
        return pol.get(key, default)
    return getattr(pol, key, default)


# -----------------
# Contract Error normalization
# -----------------


def _as_contract_error(where: str, exc: Exception) -> ContractError:
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

    return ContractError(
        code="internal_error",
        where=where,
        message="unexpected error in resources contract; see logs",
        http_status=500,
        data={"exc_type": exc.__class__.__name__},
    )


# -----------------
# Point of Contact wrappers for app.services.poc
# -----------------


def resourse_link_poc(
    *,
    resource_entity_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int = 0,
    is_primary: bool = False,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    entity_v2.require_person_entity_ulid(
        entity_ulid=person_entity_ulid,
        where="resources.resource_link_poc",
    )
    return poc_svc.link_poc(
        POCModel=ResourcePOC,
        spec=_RESOURCE_POC_SPEC,
        domain="resources",
        owner_ulid=resource_entity_ulid,
        person_entity_ulid=person_entity_ulid,
        scope=scope,
        rank=rank,
        is_primary=is_primary,
        window=window,
        org_role=org_role,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )  # type: ignore


def resource_update_poc(
    *,
    resource_entity_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    rank: int | None = None,
    is_primary: bool | None = None,
    window: dict | None = None,
    org_role: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    entity_v2.require_person_entity_ulid(
        entity_ulid=person_entity_ulid,
        where="resources.resource_update_poc",
    )
    return poc_svc.update_poc(
        db.session,
        POCModel=ResourcePOC,
        spec=_RESOURCE_POC_SPEC,
        domain="resources",
        owner_ulid=resource_entity_ulid,
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
    resource_entity_ulid: str,
    person_entity_ulid: str,
    scope: str | None = None,
    actor_ulid: str | None = None,
    request_id: str,
):
    entity_v2.require_person_entity_ulid(
        Entity_ulid=person_entity_ulid,
        where="resources.resource_unlink_poc",
    )
    return poc_svc.unlink_poc(
        POCModel=ResourcePOC,
        spec=_RESOURCE_POC_SPEC,
        domain="resources",
        owner_ulid=resource_entity_ulid,
        person_entity_ulid=person_entity_ulid,
        scope=scope,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )


def resource_list_pocs(*, resource_ulid: str) -> list[ResourcePOCView]:
    rows = poc_svc.list_pocs(
        POCModel=ResourcePOC,
        spec=_RESOURCE_POC_SPEC,
        owner_ulid=resource_ulid,
    )
    return map_resource_poc_list(rows)


# -----------------
# Helpers: validation
# -----------------


def _ensure_reqid(rid: str | None) -> str:
    if not rid or not str(rid).strip():
        raise ValueError("request_id must be non-empty")
    return str(rid).strip()


# -----------------
# Helpers: capability history snapshots
# -----------------


def _latest_snapshot(resource_entity_ulid: str) -> dict[str, dict]:
    h = (
        db.session.query(ResourceHistory)
        .filter_by(
            resource_entity_ulid=resource_entity_ulid, section=CAPS_SECTION
        )
        .order_by(desc(ResourceHistory.version))
        .first()
    )
    return json.loads(h.data_json) if h else {}


def _next_version(resource_entity_ulid: str) -> int:
    cur = (
        db.session.query(func.max(ResourceHistory.version))
        .filter_by(
            resource_entity_ulid=resource_entity_ulid, section=CAPS_SECTION
        )
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
    note_max = int(_pol_get(policy, "note_max", 0) or 0)

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

                # replace semantics: "has" defaults True when omitted
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
    payload: dict[str, object],
) -> dict[str, dict[str, object]]:
    """
    Validate and normalise a capability payload against Board policy.

    Replace semantics.
    Returns:
        { "domain.code": {"has": bool, "note": str?}, ... }
    """
    flat = _flatten_caps_payload(payload)
    if not flat:
        return flat

    caps = _caps_policy()
    allowed = set(_pol_get(caps, "all_codes", []) or [])
    note_max = int(_pol_get(caps, "note_max", 0) or 0)

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


def _validate_caps_patch(
    payload: dict[str, object],
) -> dict[str, dict[str, object]]:
    """
    Patch semantics.
    Allows:
      - bool values (treated as {"has": bool})
      - dict values with optional "has" and/or "note"
    Important difference vs replace: if "has" is omitted, we DO NOT default it.
    """
    if not payload:
        return {}

    caps = _caps_policy()
    allowed = set(_pol_get(caps, "all_codes", []) or [])
    note_max = int(_pol_get(caps, "note_max", 0) or 0)

    norm: dict[str, dict[str, object]] = {}

    for raw_key, raw_val in payload.items():
        key = str(raw_key).strip()
        if "." not in key:
            raise ValueError(
                f"invalid classification key '{key}'; expected 'domain.key'"
            )
        domain, code = _split(key)
        flat_key = f"{domain}.{code}"

        if flat_key not in allowed:
            raise ValueError(f"unknown capability '{flat_key}'")

        if isinstance(raw_val, bool):
            norm[flat_key] = {"has": bool(raw_val)}
            continue

        if not isinstance(raw_val, dict):
            raise ValueError(f"invalid payload for '{flat_key}'")

        out: dict[str, object] = {}

        if "has" in raw_val:
            out["has"] = bool(raw_val.get("has"))

        if "note" in raw_val:
            note = raw_val.get("note")
            if note is None or str(note).strip() == "":
                out["note"] = None  # explicit clear
            else:
                out["note"] = str(note).strip()[:note_max]

        if not out:
            raise ValueError(f"empty patch for '{flat_key}'")

        norm[flat_key] = out

    return norm


# -----------------
# Policy-backed helpers (Board policy via Governance)
# -----------------


def allowed_capability_codes() -> list[str]:
    caps = _caps_policy()
    return sorted(list(_pol_get(caps, "all_codes", []) or []))


def readiness_allowed() -> set[str]:
    pol = _lifecycle_policy()
    return set(pol.get("readiness_allowed") or [])


def mou_allowed() -> set[str]:
    pol = _lifecycle_policy()
    return set(pol.get("mou_allowed") or [])


def note_max() -> int:
    caps = _caps_policy()
    return int(_pol_get(caps, "note_max", 0) or 0)


def _default_readiness() -> str:
    pol = _lifecycle_policy()
    allowed = pol.get("readiness_allowed") or ["draft"]
    return str(allowed[0])


def _default_mou() -> str:
    pol = _lifecycle_policy()
    allowed = pol.get("mou_allowed") or ["none"]
    return str(allowed[0])


# -----------------
# core API
# ------------------


def ensure_resource(
    *, resource_entity_ulid: str, request_id: str, actor_ulid: str | None
) -> str:
    _ensure_reqid(request_id)
    r = db.session.get(Resource, resource_entity_ulid)
    now = now_iso8601_ms()

    if not r:
        r = Resource(
            entity_ulid=resource_entity_ulid,
            first_seen_utc=now,
            last_touch_utc=now,
            readiness_status=_default_readiness(),
            mou_status=_default_mou(),
        )
        db.session.add(r)
        db.session.flush()

        event_bus.emit(
            domain="resources",
            operation="created_insert",
            actor_ulid=actor_ulid,
            target_ulid=resource_entity_ulid,
            request_id=request_id,
            happened_at_utc=now,
            refs={"entity_ulid": resource_entity_ulid},
        )
        return resource_entity_ulid

    r.last_touch_utc = now
    db.session.flush()
    return resource_entity_ulid


def upsert_capabilities(
    *,
    resource_entity_ulid: str,
    payload: dict[str, Any],
    request_id: str,
    actor_ulid: str | None,
    idempotency_key: str | None = None,
) -> str:
    """
    Replace semantics: incoming payload is the new truth.
    Returns history_ulid, or "" if idempotent (no new version created).
    """
    _ensure_reqid(request_id)
    now = now_iso8601_ms()
    res = db.session.get(Resource, resource_entity_ulid)
    if not res:
        raise ValueError("resource not found")

    norm = _validate_caps(payload)

    last = _latest_snapshot(resource_entity_ulid)
    if last and stable_dumps(last) == stable_dumps(norm):
        res.last_touch_utc = now
        db.session.flush()
        return ""

    before_active = {k for k, v in last.items() if v.get("has") is True}
    after_active = {k for k, v in norm.items() if v.get("has") is True}
    added = sorted(after_active - before_active)
    removed = sorted(before_active - after_active)

    version = _next_version(resource_entity_ulid)
    hist = ResourceHistory(
        resource_entity_ulid=resource_entity_ulid,
        section=CAPS_SECTION,
        version=version,
        data_json=stable_dumps(norm),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    existing = {
        (rc.domain, rc.key): rc
        for rc in db.session.query(ResourceCapabilityIndex)
        .filter_by(resource_entity_ulid=resource_entity_ulid)
        .all()
    }
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
                    resource_entity_ulid=resource_entity_ulid,
                    domain=domain,
                    key=key,
                    active=active,
                    updated_at_utc=now,
                )
            )

    for (domain, key), row in existing.items():
        if (domain, key) not in seen_pairs:
            db.session.delete(row)

    res.capability_last_update_utc = now
    res.last_touch_utc = now

    res.admin_review_required = "meta.unclassified" in after_active
    if not res.admin_review_required and res.readiness_status == "draft":
        res.readiness_status = "review"

    db.session.flush()

    for flat in added:
        domain, key = _split(flat)
        event_bus.emit(
            domain="resources",
            operation="capability_add",
            actor_ulid=actor_ulid,
            target_ulid=resource_entity_ulid,
            request_id=request_id,
            happened_at_utc=now,
            refs={"domain": domain, "key": key, "version_ptr": hist.ulid},
        )
    for flat in removed:
        domain, key = _split(flat)
        event_bus.emit(
            domain="resources",
            operation="capability_remove",
            actor_ulid=actor_ulid,
            target_ulid=resource_entity_ulid,
            request_id=request_id,
            happened_at_utc=now,
            refs={"domain": domain, "key": key, "version_ptr": hist.ulid},
        )

    return hist.ulid


def resource_view(resource_entity_ulid: str) -> ResourceView | None:
    r = db.session.get(Resource, resource_entity_ulid)
    if not r:
        return None
    caps = (
        db.session.query(ResourceCapabilityIndex)
        .filter_by(resource_entity_ulid=resource_entity_ulid, active=True)
        .all()
    )
    return map_resource_view(r, caps)


def find_resources(
    *,
    any_of: list[tuple[str, str]] | None = None,
    all_of: list[tuple[str, str]] | None = None,
    admin_review_required: bool | None = None,
    readiness_in: list[str] | None = None,
    page: int = 1,
    per: int = 50,
) -> tuple[list[ResourceView], int]:
    q = db.session.query(Resource.entity_ulid)

    if any_of:
        sub_ids: set[str] = set()
        for d, k in any_of:
            rows = (
                db.session.query(ResourceCapabilityIndex.resource_entity_ulid)
                .filter_by(domain=d, key=k, active=True)
                .all()
            )
            sub_ids.update([row[0] for row in rows])
        if sub_ids:
            q = q.filter(Resource.entity_ulid.in_(list(sub_ids)))
        else:
            return [], 0

    if all_of:
        for d, k in all_of:
            q = q.join(
                ResourceCapabilityIndex,
                ResourceCapabilityIndex.resource_entity_ulid
                == Resource.entity_ulid,
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
    views = [resource_view(r.entity_ulid) for r in rows]
    return [v for v in views if v is not None], total


def set_readiness_status(
    *,
    resource_entity_ulid: str,
    status: str,
    actor_ulid: str | None,
    request_id: str,
) -> None:
    _ensure_reqid(request_id)
    now = now_iso8601_ms()
    status = (status or "").strip().lower()

    allowed = readiness_allowed()
    if status not in allowed:
        raise ValueError(f"invalid readiness_status '{status}'")

    res = db.session.get(Resource, resource_entity_ulid)
    if not res:
        raise ValueError("resource not found")

    if res.readiness_status == status:
        return

    prev = res.readiness_status
    res.readiness_status = status
    res.last_touch_utc = now
    db.session.flush()

    event_bus.emit(
        domain="resources",
        operation="readiness_update",
        actor_ulid=actor_ulid,
        target_ulid=resource_entity_ulid,
        request_id=request_id,
        happened_at_utc=now,
        changed={"readiness_status": status, "prev": prev},
    )


def set_mou_status(
    *,
    resource_entity_ulid: str,
    status: str,
    actor_ulid: str | None,
    request_id: str,
) -> None:
    _ensure_reqid(request_id)
    now = now_iso8601_ms()
    status = (status or "").strip().lower()

    allowed = mou_allowed()
    if status not in allowed:
        raise ValueError(f"invalid mou_status '{status}'")

    res = db.session.get(Resource, resource_entity_ulid)
    if not res:
        raise ValueError("resource not found")

    if res.mou_status == status:
        return

    prev = res.mou_status
    res.mou_status = status
    res.last_touch_utc = now
    db.session.flush()

    event_bus.emit(
        domain="resources",
        operation="mou_update",
        actor_ulid=actor_ulid,
        target_ulid=resource_entity_ulid,
        request_id=request_id,
        happened_at_utc=now,
        changed={"mou_status": status, "prev": prev},
    )


def rebuild_capability_index(
    *, resource_entity_ulid: str, request_id: str, actor_ulid: str | None
) -> int:
    _ensure_reqid(request_id)
    now = now_iso8601_ms()
    r = db.session.get(Resource, resource_entity_ulid)
    if not r:
        raise ValueError("resource not found")

    snapshot = _latest_snapshot(resource_entity_ulid)

    db.session.query(ResourceCapabilityIndex).filter_by(
        resource_entity_ulid=resource_entity_ulid
    ).delete()

    count = 0
    for flat, obj in snapshot.items():
        domain, key = _split(flat)
        active = bool(obj.get("has"))
        db.session.add(
            ResourceCapabilityIndex(
                resource_entity_ulid=resource_entity_ulid,
                domain=domain,
                key=key,
                active=active,
                updated_at_utc=now,
            )
        )
        count += 1

    r.last_touch_utc = now
    r.capability_last_update_utc = now
    db.session.flush()

    event_bus.emit(
        domain="resources",
        operation="capability_rebuild",
        actor_ulid=actor_ulid,
        target_ulid=resource_entity_ulid,
        request_id=request_id,
        happened_at_utc=now,
        refs={"rows": count},
    )
    return count


def promote_readiness_if_clean(
    *, resource_entity_ulid: str, request_id: str, actor_ulid: str | None
) -> bool:
    _ensure_reqid(request_id)
    r = db.session.get(Resource, resource_entity_ulid)
    if not r:
        raise ValueError("resource not found")

    latest = _latest_snapshot(resource_entity_ulid)
    has_unclassified = bool(
        latest.get("meta.unclassified", {}).get("has") is True
    )
    if not has_unclassified and r.readiness_status == "review":
        set_readiness_status(
            resource_entity_ulid=resource_entity_ulid,
            status="active",
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return True
    return False


def _merge_snapshot(
    latest: dict[str, dict], patch: dict[str, dict]
) -> dict[str, dict]:
    merged = {k: dict(v) for k, v in latest.items()}
    for flat, obj in patch.items():
        if flat not in merged:
            merged[flat] = {}
        if "has" in obj:
            merged[flat]["has"] = bool(obj["has"])
        if "note" in obj:
            note = obj["note"]
            if note is None:
                merged[flat].pop("note", None)
            else:
                note_str = str(note).strip()
                if not note_str:
                    merged[flat].pop("note", None)
                else:
                    merged[flat]["note"] = note_str
    return merged


def patch_capabilities(
    *,
    resource_entity_ulid: str,
    payload: dict[str, object],
    request_id: str,
    actor_ulid: str | None,
) -> str | None:
    _ensure_reqid(request_id)
    now = now_iso8601_ms()
    res = db.session.get(Resource, resource_entity_ulid)
    if not res:
        raise ValueError("resource not found")

    norm_patch = _validate_caps_patch(payload)
    latest = _latest_snapshot(resource_entity_ulid)
    merged = _merge_snapshot(latest, norm_patch)

    if stable_dumps(merged) == stable_dumps(latest):
        res.last_touch_utc = now
        db.session.flush()
        return None

    before_active = {k for k, v in latest.items() if v.get("has") is True}
    after_active = {k for k, v in merged.items() if v.get("has") is True}
    added = sorted(after_active - before_active)
    removed = sorted(before_active - after_active)

    version = _next_version(resource_entity_ulid)
    hist = ResourceHistory(
        resource_entity_ulid=resource_entity_ulid,
        section=CAPS_SECTION,
        version=version,
        data_json=stable_dumps(merged),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    # Upsert only touched keys; leave other index rows unchanged.
    for flat, obj in norm_patch.items():
        domain, key = _split(flat)
        if "has" not in obj:
            continue  # note-only change doesn't affect index state
        active = bool(obj.get("has"))
        row = (
            db.session.query(ResourceCapabilityIndex)
            .filter_by(
                resource_entity_ulid=resource_entity_ulid,
                domain=domain,
                key=key,
            )
            .first()
        )
        if row:
            row.active = active
            row.updated_at_utc = now
        else:
            db.session.add(
                ResourceCapabilityIndex(
                    resource_entity_ulid=resource_entity_ulid,
                    domain=domain,
                    key=key,
                    active=active,
                    updated_at_utc=now,
                )
            )

    res.last_touch_utc = now
    res.capability_last_update_utc = now
    res.admin_review_required = "meta.unclassified" in after_active
    if not res.admin_review_required and res.readiness_status == "draft":
        res.readiness_status = "review"

    db.session.flush()

    for flat in added:
        d, k = _split(flat)
        event_bus.emit(
            domain="resources",
            operation="capability_add",
            actor_ulid=actor_ulid,
            target_ulid=resource_entity_ulid,
            request_id=request_id,
            happened_at_utc=now,
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )
    for flat in removed:
        d, k = _split(flat)
        event_bus.emit(
            domain="resources",
            operation="capability_remove",
            actor_ulid=actor_ulid,
            target_ulid=resource_entity_ulid,
            request_id=request_id,
            happened_at_utc=now,
            refs={"domain": d, "key": k, "version_ptr": hist.ulid},
        )

    return hist.ulid


def rebuild_all_capability_indexes(
    *, page: int = 1, per: int = 200, request_id: str, actor_ulid: str | None
) -> dict:
    _ensure_reqid(request_id)
    per = max(1, min(int(per or 200), 500))

    q = (
        db.session.query(Resource.entity_ulid)
        .order_by(Resource.created_at_utc.asc())
        .offset((int(page or 1) - 1) * per)
        .limit(per)
    )
    ids = [row[0] for row in q.all()]
    total_rows = 0
    for rid in ids:
        total_rows += int(
            rebuild_capability_index(
                resource_entity_ulid=rid,
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


__all__ = [
    "ensure_resource",
    "upsert_capabilities",
    "patch_capabilities",
    "resource_view",
    "find_resources",
    "set_readiness_status",
    "set_mou_status",
    "rebuild_capability_index",
    "rebuild_all_capability_indexes",
    "promote_readiness_if_clean",
    "resource_list_pocs",
]
