# app/slices/resources/services.py
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import desc, func

from app.extensions import db, event_bus
from app.extensions.contracts import entity_v2
from app.extensions.errors import ContractError
from app.lib.chrono import now_iso8601_ms
from app.lib.guards import ensure_actor_ulid, ensure_request_id
from app.lib.jsonutil import stable_dumps

from . import services_poc as poc
from . import taxonomy as tax
from .mapper import (
    ResourcePOCView,
    ResourceView,
    map_resource_poc_list,
    map_resource_view,
)
from .models import (
    Resource,
    ResourceCapabilityIndex,
    ResourceHistory,
    ResourcePOC,
)

PROFILE_SECTION = "resource:profile:v1"
CAPS_SECTION = "resource:capability:v1"

_RESOURCE_POC_SPEC = poc.POCSpec(
    owner_col="resource_entity_ulid",
    allowed_scopes=tuple(tax.POC_SCOPES),
    default_scope=str(tax.DEFAULT_POC_SCOPE),
    max_rank=int(tax.POC_MAX_RANK),
)

_ALLOWED_CAPS = frozenset(tax.all_capability_codes())
_NOTE_MAX = int(tax.RESOURCE_CAPABILITY_NOTE_MAX)

# -----------------
# Taxonomy-backed
# helpers
# -----------------


def allowed_capability_codes() -> list[str]:
    return tax.all_capability_codes()


def note_max() -> int:
    return int(tax.RESOURCE_CAPABILITY_NOTE_MAX)


def _ensure_reqid(rid: str | None) -> str:
    if not rid or not str(rid).strip():
        raise ValueError("request_id must be non-empty")
    return str(rid).strip()


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


def _flatten_caps_payload(payload: dict[str, object]) -> dict[str, object]:
    flat: dict[str, object] = {}
    if not payload:
        return flat

    for raw_key, raw_val in payload.items():
        key = str(raw_key).strip()

        if "." in key:
            items = [(key, raw_val)]
        else:
            domain = key
            if not isinstance(raw_val, dict):
                raise ValueError(
                    "nested capabilities must be objects per domain"
                )
            items = [(f"{domain}.{sub}", sv) for sub, sv in raw_val.items()]

        for flat_key, obj in items:
            domain, code = _split(str(flat_key))
            norm_key = f"{domain}.{code}"
            flat[norm_key] = obj

    return flat


def _validate_caps_replace(
    payload: dict[str, object],
) -> dict[str, dict[str, object]]:
    flat = _flatten_caps_payload(payload)
    if not flat:
        return {}

    norm: dict[str, dict[str, object]] = {}

    for flat_key, raw_val in flat.items():
        if flat_key not in _ALLOWED_CAPS:
            raise ValueError(f"unknown capability '{flat_key}'")

        if isinstance(raw_val, bool):
            norm[flat_key] = {"has": bool(raw_val)}
            continue

        if not isinstance(raw_val, dict):
            raise ValueError(f"invalid payload for '{flat_key}'")

        out: dict[str, object] = {"has": bool(raw_val.get("has", True))}

        note = raw_val.get("note")
        if note is not None:
            note_str = str(note).strip()
            if note_str:
                out["note"] = note_str[:_NOTE_MAX]

        norm[flat_key] = out

    return norm


def _normalize_profile_hints(payload: dict[str, Any]) -> dict[str, Any]:
    def _norm_note(v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    return {
        "service_area_note": _norm_note(payload.get("service_area_note")),
        "sla_note": _norm_note(payload.get("sla_note")),
    }


def _latest_snapshot(
    resource_entity_ulid: str,
    *,
    section: str = CAPS_SECTION,
) -> dict[str, dict]:
    h = (
        db.session.query(ResourceHistory)
        .filter_by(resource_entity_ulid=resource_entity_ulid, section=section)
        .order_by(desc(ResourceHistory.version))
        .first()
    )
    return json.loads(h.data_json) if h else {}


def _next_version(
    resource_entity_ulid: str,
    *,
    section: str = CAPS_SECTION,
) -> int:
    cur = (
        db.session.query(func.max(ResourceHistory.version))
        .filter_by(resource_entity_ulid=resource_entity_ulid, section=section)
        .scalar()
    )
    return int(cur or 0) + 1


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
        message="unexpected error in resources; see logs",
        http_status=500,
        data={"exc_type": exc.__class__.__name__},
    )


# -----------------
# POC wrappers
# -----------------


def resource_link_poc(
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
    return poc.link_poc(
        session=db.session(),
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
    return poc.update_poc(
        session=db.session(),
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
        entity_ulid=person_entity_ulid,
        where="resources.resource_unlink_poc",
    )
    return poc.unlink_poc(
        session=db.session(),
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
    rows = poc.list_pocs(
        session=db.session(),
        POCModel=ResourcePOC,
        spec=_RESOURCE_POC_SPEC,
        owner_ulid=resource_ulid,
    )
    return map_resource_poc_list(rows)


def resource_list_pocs_expanded(
    *,
    resource_entity_ulid: str,
    request_id: str,
    actor_ulid: str | None = None,
) -> dict[str, Any]:
    _ensure_reqid(request_id)

    pocs_view = resource_list_pocs(resource_ulid=resource_entity_ulid)

    person_ulids: list[str] = []
    seen: set[str] = set()
    for p in pocs_view:
        u = str(p.person_entity_ulid).strip()
        if u and u not in seen:
            seen.add(u)
            person_ulids.append(u)

    if not person_ulids:
        return {"resource_entity_ulid": resource_entity_ulid, "pocs": []}

    cards_dc = entity_v2.get_entity_cards(
        entity_ulids=person_ulids,
        include_contacts=True,
        include_addresses=False,
    )
    cards = {u: asdict(c) for u, c in cards_dc.items()}

    out: list[dict[str, Any]] = []
    for p in pocs_view:
        out.append(
            {
                "person_entity_ulid": p.person_entity_ulid,
                "org_role": p.org_role,
                "scope": p.scope,
                "rank": p.rank,
                "is_primary": p.is_primary,
                "active": p.active,
                "valid_from_utc": p.valid_from_utc,
                "valid_to_utc": p.valid_to_utc,
                "card": cards.get(p.person_entity_ulid),
            }
        )

    return {"resource_entity_ulid": resource_entity_ulid, "pocs": out}


# -----------------
# Core API
# -----------------


def ensure_resource(
    *,
    resource_entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> str:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()

    # Resources are org-backed facets; enforce this early.
    entity_v2.require_org_entity_ulid(
        resource_entity_ulid,
        where="resources.ensure_resource",
    )

    r = db.session.get(Resource, resource_entity_ulid)
    if not r:
        r = Resource(
            entity_ulid=resource_entity_ulid,
            first_seen_utc=now,
            last_touch_utc=now,
            readiness_status="draft",
            mou_status="none",
        )
        db.session.add(r)
        db.session.flush()

        event_bus.emit(
            domain="resources",
            operation="created_insert",
            actor_ulid=act,
            target_ulid=resource_entity_ulid,
            request_id=rid,
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
) -> str | None:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()

    res = db.session.get(Resource, resource_entity_ulid)
    if not res:
        raise ValueError("resource not found")

    norm = _validate_caps_replace(payload)

    last = _latest_snapshot(resource_entity_ulid, section=CAPS_SECTION) or {}
    if last and stable_dumps(last) == stable_dumps(norm):
        res.last_touch_utc = now
        db.session.flush()
        return None

    before_active = {k for k, v in last.items() if v.get("has") is True}
    after_active = {k for k, v in norm.items() if v.get("has") is True}
    added = sorted(after_active - before_active)
    removed = sorted(before_active - after_active)

    version = _next_version(resource_entity_ulid, section=CAPS_SECTION)
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
        for rc in (
            db.session.query(ResourceCapabilityIndex)
            .filter_by(resource_entity_ulid=resource_entity_ulid)
            .all()
        )
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
            actor_ulid=act,
            target_ulid=resource_entity_ulid,
            request_id=rid,
            happened_at_utc=now,
            refs={"domain": domain, "key": key, "version_ptr": hist.ulid},
        )
    for flat in removed:
        domain, key = _split(flat)
        event_bus.emit(
            domain="resources",
            operation="capability_remove",
            actor_ulid=act,
            target_ulid=resource_entity_ulid,
            request_id=rid,
            happened_at_utc=now,
            refs={"domain": domain, "key": key, "version_ptr": hist.ulid},
        )

    return hist.ulid


def set_profile_hints(
    *,
    resource_entity_ulid: str,
    payload: dict[str, Any],
    request_id: str,
    actor_ulid: str | None,
) -> str | None:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()

    res = db.session.get(Resource, resource_entity_ulid)
    if not res:
        raise ValueError("resource not found")

    norm = _normalize_profile_hints(payload)

    last = (
        _latest_snapshot(resource_entity_ulid, section=PROFILE_SECTION) or {}
    )
    if last and stable_dumps(last) == stable_dumps(norm):
        res.last_touch_utc = now
        db.session.flush()
        return None

    version = _next_version(resource_entity_ulid, section=PROFILE_SECTION)
    hist = ResourceHistory(
        resource_entity_ulid=resource_entity_ulid,
        section=PROFILE_SECTION,
        version=version,
        data_json=stable_dumps(norm),
        created_by_actor=actor_ulid,
    )
    db.session.add(hist)

    res.last_touch_utc = now
    db.session.flush()

    event_bus.emit(
        domain="resources",
        operation="profile_update",
        actor_ulid=act,
        target_ulid=resource_entity_ulid,
        request_id=rid,
        happened_at_utc=now,
        refs={"version_ptr": hist.ulid},
        changed_fields=["service_area_note", "sla_note"],
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


def get_profile_hints(resource_entity_ulid: str) -> dict[str, str | None]:
    res = db.session.get(Resource, resource_entity_ulid)
    if not res:
        raise LookupError("resource not found")

    snap = (
        _latest_snapshot(resource_entity_ulid, section=PROFILE_SECTION) or {}
    )
    return {
        "service_area_note": snap.get("service_area_note"),
        "sla_note": snap.get("sla_note"),
    }


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
            sub_ids.update(row[0] for row in rows)
        if sub_ids:
            q = q.filter(Resource.entity_ulid.in_(list(sub_ids)))
        else:
            return [], 0

    if all_of:
        sub_ids: set[str] | None = None
        for d, k in all_of:
            rows = (
                db.session.query(ResourceCapabilityIndex.resource_entity_ulid)
                .filter_by(domain=d, key=k, active=True)
                .all()
            )
            ids = {row[0] for row in rows}
            sub_ids = ids if sub_ids is None else (sub_ids & ids)
        if sub_ids:
            q = q.filter(Resource.entity_ulid.in_(list(sub_ids)))
        else:
            return [], 0

    if admin_review_required is not None:
        q = q.filter(
            Resource.admin_review_required.is_(bool(admin_review_required))
        )

    if readiness_in:
        norm = sorted({str(s).strip().lower() for s in readiness_in if s})
        q = q.filter(Resource.readiness_status.in_(norm))

    page = max(1, int(page))
    per = min(200, max(1, int(per)))
    total = q.count()
    rows = (
        q.order_by(Resource.updated_at_utc.desc())
        .offset((page - 1) * per)
        .limit(per)
        .all()
    )
    views = [resource_view(row[0]) for row in rows]
    return [v for v in views if v is not None], total


def set_readiness_status(
    *,
    resource_entity_ulid: str,
    to_status: str,
    actor_ulid: str | None,
    request_id: str,
) -> None:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()

    status_key = (to_status or "").strip().lower()
    if not status_key:
        raise ValueError("readiness_status is required")
    if not tax.is_valid_readiness_status(status_key):
        raise ValueError(f"invalid readiness_status: {to_status!r}")

    res = db.session.get(Resource, resource_entity_ulid)
    if not res:
        raise ValueError("resource not found")

    if (res.readiness_status or "").strip().lower() == status_key:
        return

    res.readiness_status = status_key
    res.last_touch_utc = now
    db.session.flush()

    event_bus.emit(
        domain="resources",
        operation="readiness_update",
        actor_ulid=act,
        target_ulid=resource_entity_ulid,
        request_id=rid,
        happened_at_utc=now,
        changed={"readiness_status": status_key},
    )


def set_mou_status(
    *,
    resource_entity_ulid: str,
    to_status: str,
    actor_ulid: str | None,
    request_id: str,
) -> None:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()

    status_key = (to_status or "").strip().lower()
    if not status_key:
        raise ValueError("mou_status is required")
    if not tax.is_valid_mou_status(status_key):
        raise ValueError(f"invalid mou_status: {to_status!r}")

    res = db.session.get(Resource, resource_entity_ulid)
    if not res:
        raise ValueError("resource not found")

    prev = (res.mou_status or "").strip().lower()
    if prev == status_key:
        return

    res.mou_status = status_key
    res.last_touch_utc = now
    db.session.flush()

    event_bus.emit(
        domain="resources",
        operation="mou_update",
        actor_ulid=act,
        target_ulid=resource_entity_ulid,
        request_id=rid,
        happened_at_utc=now,
        changed={"mou_status": status_key, "prev": prev},
    )


def rebuild_capability_index(
    *,
    resource_entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> int:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)
    now = now_iso8601_ms()

    r = db.session.get(Resource, resource_entity_ulid)
    if not r:
        raise ValueError("resource not found")

    snapshot = _latest_snapshot(resource_entity_ulid, section=CAPS_SECTION)

    (
        db.session.query(ResourceCapabilityIndex)
        .filter_by(resource_entity_ulid=resource_entity_ulid)
        .delete()
    )

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
        actor_ulid=act,
        target_ulid=resource_entity_ulid,
        request_id=rid,
        happened_at_utc=now,
        refs={"rows": count},
    )
    return count


def rebuild_all_capability_indexes(
    *,
    page: int = 1,
    per: int = 200,
    request_id: str = "",
    actor_ulid: str | None = None,
) -> dict[str, Any]:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)

    per = max(1, min(int(per or 200), 500))
    page = max(1, int(page or 1))

    q = (
        db.session.query(Resource.entity_ulid)
        .order_by(Resource.created_at_utc.asc())
        .offset((page - 1) * per)
        .limit(per)
    )
    ids = [row[0] for row in q.all()]

    total_rows = 0
    for rowid in ids:
        total_rows += int(
            rebuild_capability_index(
                resource_entity_ulid=rowid,
                request_id=rid,
                actor_ulid=act,
            )
            or 0
        )

    return {
        "processed": len(ids),
        "reindexed": total_rows,
        "page": page,
        "per": per,
    }


def promote_readiness_if_clean(
    *,
    resource_entity_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> bool:
    rid = ensure_request_id(request_id)

    r = db.session.get(Resource, resource_entity_ulid)
    if not r:
        raise ValueError("resource not found")

    latest = _latest_snapshot(resource_entity_ulid, section=CAPS_SECTION)
    has_unclassified = bool(
        latest.get("meta.unclassified", {}).get("has") is True
    )

    if not has_unclassified and r.readiness_status == "review":
        set_readiness_status(
            resource_entity_ulid=resource_entity_ulid,
            to_status="active",
            request_id=rid,
            actor_ulid=actor_ulid,
        )
        return True
    return False


__all__ = [
    "allowed_capability_codes",
    "note_max",
    "ensure_resource",
    "upsert_capabilities",
    "set_profile_hints",
    "resource_view",
    "get_profile_hints",
    "find_resources",
    "set_readiness_status",
    "set_mou_status",
    "promote_readiness_if_clean",
    "rebuild_capability_index",
    "rebuild_all_capability_indexes",
    "resource_link_poc",
    "resource_update_poc",
    "resource_unlink_poc",
    "resource_list_pocs",
    "resource_list_pocs_expanded",
]
