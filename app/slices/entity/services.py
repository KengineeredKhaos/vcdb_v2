# app/slices/entity/services.py
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import asc
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db, event_bus
from app.extensions.contracts.governance_v2 import get_role_catalogs
from app.lib.pagination import Page, paginate_sa, rewrap_page
from app.lib.utils import (
    normalize_ein,
    normalize_email,
    normalize_phone,
    validate_ein,
    validate_email,
    validate_phone,
)

from .mapper import (
    EntityLabelDTO,
    OrgView,
    PersonView,
    map_org_view,
    map_person_view,
)
from .models import (
    Entity,
    EntityAddress,
    EntityContact,
    EntityOrg,
    EntityPerson,
    EntityRole,
)

"""
TODO: Create:
        get_person_view(entity_ulid=entity_ulid)
        get_org_view(entity_ulid=entity_ulid)

"""


def allowed_role_codes(session=None) -> set[str]:
    """
    Return the canonical set of domain role codes allowed by Governance policy.
    This is a read-only call through the v2 contract (no DB writes here).
    """
    cats = get_role_catalogs()
    roles = cats.get("roles") or []
    return set(str(r) for r in roles)


# -----------------
# Internal guard
# -----------------


def _ensure_reqid(request_id: str | None) -> str:
    if request_id is None or not str(request_id).strip():
        raise ValueError("request_id must be non-empty")
    return str(request_id)


# -----------------
# Seed Functions
# -----------------


def _validate_entity_shape(e: Entity) -> None:
    """Hard guard: exactly one child matching kind."""
    if e.kind == "person":
        if e.person is None or e.org is not None:
            raise ValueError(
                "kind='person' requires person child and forbids org child"
            )
    elif e.kind == "org":
        if e.org is None or e.person is not None:
            raise ValueError(
                "kind='org' requires org child and forbids person child"
            )
    else:
        raise ValueError("Entity.kind must be 'person' or 'org'")


# -----------------
# Entity as Person (POC)
# -----------------


def ensure_person(
    *,
    first_name: str,
    last_name: str,
    email: str | None,
    phone: str | None,
    request_id: str,
    actor_ulid: str | None,
) -> str:
    # Back-compat shim for older call sites/tests.
    return ensure_person_by_contact(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )


def ensure_person_by_contact(
    *,
    first_name: str,
    last_name: str,
    email: str | None,
    phone: str | None,
    request_id: str,
    actor_ulid: str | None,
) -> str:
    return cmd_person_ensure_by_contact(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        request_id=request_id,
        actor_ulid=actor_ulid,
    ).entity_ulid


# -----------------
# Entity as Organization
# -----------------


def ensure_org(
    *,
    legal_name: str,
    dba_name: str | None = None,
    ein: str | None = None,
    request_id: str,
    actor_ulid: str | None,
) -> str:
    """
    Create/update an organization entity.
    Idempotent on EIN if provided (normalized to 9 digits).
    Returns entity_ulid.
    """
    _ensure_reqid(request_id)
    ln = (legal_name or "").strip()
    if not ln:
        raise ValueError("legal_name is required")

    ent: Entity | None = None
    ein_norm = normalize_ein(ein) if ein else None
    if ein is not None and ein_norm and not validate_ein(ein_norm):
        raise ValueError("Invalid EIN (must be 9 digits)")

    if ein_norm:
        ent = (
            db.session.query(Entity)
            .join(EntityOrg, EntityOrg.entity_ulid == Entity.ulid)
            .filter(Entity.kind == "org", EntityOrg.ein == ein_norm)
            .first()
        )

    created = False
    if not ent:
        ent = Entity(kind="org")
        db.session.add(ent)
        db.session.flush()
        db.session.add(
            EntityOrg(
                entity_ulid=ent.ulid,
                legal_name=ln,
                dba_name=dba_name or None,
                ein=ein_norm,
            )
        )
        created = True
    else:
        o = ent.org
        if o:
            o.legal_name = ln or o.legal_name
            if dba_name is not None:
                o.dba_name = dba_name or None
            if ein is not None:
                o.ein = ein_norm
        else:
            db.session.add(
                EntityOrg(
                    entity_ulid=ent.ulid,
                    legal_name=ln,
                    dba_name=dba_name or None,
                    ein=ein_norm,
                )
            )

    db.session.flush()
    # PII-safe, canon emit
    event_bus.emit(
        domain="entity",
        operation="org_created" if created else "org_upserted",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=ent.ulid,
        refs=None,
        changed={
            "fields": ["legal_name"]
            + (["dba_name"] if dba_name is not None else [])
            + (["ein"] if ein is not None else [])
        },
    )

    return ent.ulid


# -----------------
# Entity Contact
# (email/phone)
# -----------------


def edit_contact(
    *,
    entity_ulid: str,
    email: str | None,
    phone: str | None,
    request_id: str,
    actor_ulid: str | None,
) -> None:
    """
    edit the single primary contact row for an entity;
    emits one event.
    """
    # TODO: add choose primary or secondary contact for edit

    _ensure_reqid(request_id)

    ent = db.session.get(Entity, entity_ulid)
    if not ent:
        raise ValueError("entity not found")

    em = normalize_email(email) if email is not None else None
    if email is not None and em and not validate_email(em):
        raise ValueError("Invalid email")

    ph = normalize_phone(phone) if phone is not None else None
    if phone is not None and ph and not validate_phone(ph):
        raise ValueError("Invalid phone")

    changed = {}
    _edit_contact(entity_ulid=entity_ulid, email=em, phone=ph)
    if email is not None:
        changed["email"] = em
    if phone is not None:
        changed["phone"] = ph

    db.session.flush()
    if changed:
        event_bus.emit(
            domain="entity",
            operation="contact_upserted",
            request_id=request_id,
            actor_ulid=actor_ulid,
            target_ulid=entity_ulid,
            refs=None,
            changed={"fields": list(changed.keys())},
        )
    return ()


def _edit_contact(
    *, entity_ulid: str, email: str | None, phone: str | None
) -> None:
    """
    Maintain exactly one primary EntityContact row per entity.
    - If no row exists, create one with provided fields (could be email, phone or both).
    - If row exists, update only fields that are not None.
    - If a provided field is explicitly None, clear that field (treat as removal).
    """
    c = (
        db.session.query(EntityContact)
        .filter_by(entity_ulid=entity_ulid, is_primary=True)
        .first()
    )
    if not c:
        c = EntityContact(entity_ulid=entity_ulid, is_primary=True)
        if email is not None:
            c.email = email
        if phone is not None:
            c.phone = phone
        db.session.add(c)
        return

    # Update in-place
    if email is not None:
        c.email = email
    if phone is not None:
        c.phone = phone


# -----------------
# Entity Address
# -----------------


def upsert_address(
    *,
    entity_ulid: str,
    is_physical: bool = True,
    is_postal: bool = False,
    address1: str = "",
    address2: str | None = None,
    city: str = "",
    state: str = "",
    postal_code: str = "",
    request_id: str,
    actor_ulid: str | None,
) -> str:
    """
    Create/update the single 'primary' address by (is_physical, is_postal) flags.
    Returns the address ulid.
    """
    _ensure_reqid(request_id)
    ent = db.session.get(Entity, entity_ulid)
    if not ent:
        raise ValueError("entity not found")

    def _norm(s: str | None) -> str | None:
        return (s or "").strip() or None

    addr = (
        db.session.query(EntityAddress)
        .filter_by(
            entity_ulid=entity_ulid,
            is_physical=is_physical,
            is_postal=is_postal,
        )
        .first()
    )

    # created = False
    if not addr:
        addr = EntityAddress(
            entity_ulid=entity_ulid,
            is_physical=is_physical,
            is_postal=is_postal,
            address1=_norm(address1) or "",
            address2=_norm(address2),
            city=_norm(city) or "",
            state=_norm(state) or "",
            postal_code=_norm(postal_code) or "",
        )
        db.session.add(addr)
        # created = True
    else:
        addr.address1 = _norm(address1) or addr.address1
        addr.address2 = _norm(address2)
        addr.city = _norm(city) or addr.city
        addr.state = _norm(state) or addr.state
        addr.postal_code = _norm(postal_code) or addr.postal_code

    db.session.flush()

    event_bus.emit(
        domain="entity",
        operation="address_upserted",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=entity_ulid,
        refs={"address_ulid": addr.ulid},
        changed={
            "fields": ["is_physical", "is_postal"]
            + (["postal_code"] if postal_code else [])
        },
    )

    return addr.ulid


# -----------------
# Entity Role Codes
# -----------------


def ensure_role(
    *,
    entity_ulid: str,
    role: str,
    request_id: str,
    actor_ulid: str | None | None,
) -> bool:
    """
    Attach a role to an entity if allowed by Governance and not already attached.
    """
    _ensure_reqid(request_id)

    allowed = set(
        allowed_role_codes()
    )  # e.g., ('customer','resource','sponsor','staff','admin')
    if role not in allowed:
        raise ValueError(f"Role '{role}' not allowed by policy")

    existing = (
        db.session.query(EntityRole)
        .filter_by(entity_ulid=entity_ulid, role=role)
        .first()
    )
    if existing:
        return False  # idempotent: already has role

    rr = EntityRole(entity_ulid=entity_ulid, role=role)
    db.session.add(rr)
    db.session.flush()

    # attached
    event_bus.emit(
        domain="entity",
        operation="role_attached",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=entity_ulid,
        refs=None,
        changed={"fields": ["role"], "role": role},
    )
    return True


def remove_role(
    *,
    entity_ulid: str,
    role: str,
    request_id: str,
    actor_ulid: str | None | None,
) -> bool:
    """
    Remove a role from an entity (idempotent).
    """
    _ensure_reqid(request_id)

    allowed = set(allowed_role_codes())
    if role not in allowed:
        raise ValueError(f"Role '{role}' not allowed by policy")

    existing = (
        db.session.query(EntityRole)
        .filter_by(entity_ulid=entity_ulid, role=role)
        .first()
    )
    if not existing:
        return False

    db.session.delete(existing)
    db.session.flush()

    # removed
    event_bus.emit(
        domain="entity",
        operation="role_removed",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=entity_ulid,
        refs=None,
        changed={"fields": ["role"], "role": role},
    )
    return True


# -----------------
# Views / listings
# -----------------
def get_person_view(entity_ulid: str) -> dict | None:
    person = db.session.get(EntityPerson, entity_ulid)
    if person is None:
        return None
    # eager-load primary contact for DTO
    _ = person.entity and person.entity.contacts
    return map_person_view(person)


def list_people(*, page: int, per_page: int) -> Page[PersonView]:
    q = (
        db.session.query(EntityPerson)
        .join(Entity, EntityPerson.entity_ulid == Entity.ulid)
        .options(
            joinedload(EntityPerson.entity).options(
                selectinload(Entity.contacts),
                selectinload(Entity.roles),
            )
        )
        .order_by(
            asc(EntityPerson.last_name),
            asc(EntityPerson.first_name),
            asc(Entity.ulid),
        )
    )

    return paginate_sa(q, page=page, per_page=per_page).map(map_person_view)


def get_org_view(entity_ulid: str) -> dict | None:
    org = db.session.get(EntityOrg, entity_ulid)
    if org is None:
        return None
    # eager-load primary contact for DTO
    _ = org.entity and org.entity.contacts
    return map_org_view(org)


def list_orgs_by_roles(
    *, roles: list[str], page: int, per_page: int
) -> Page[OrgView]:
    q = (
        db.session.query(EntityOrg)
        .join(Entity, EntityOrg.entity_ulid == Entity.ulid)
        .join(EntityRole, EntityRole.entity_ulid == Entity.ulid)
        .filter(EntityRole.role.in_(roles))
        .options(
            joinedload(EntityOrg.entity).options(
                selectinload(Entity.contacts),
                selectinload(Entity.roles),
            )
        )
        .order_by(asc(EntityOrg.legal_name), asc(Entity.ulid))
        .distinct(EntityOrg.entity_ulid)
    )

    org_page = paginate_sa(q, page=page, per_page=per_page)
    views = [map_org_view(o) for o in org_page.items]
    return rewrap_page(org_page, views)


# -----------------
# Cross-slice labels
# -----------------


def get_entity_labels(
    *, entity_ulids: list[str]
) -> dict[str, EntityLabelDTO]:
    raw = [str(u).strip() for u in (entity_ulids or []) if str(u).strip()]
    if not raw:
        return {}

    seen: set[str] = set()
    ulids: list[str] = []
    for u in raw:
        if u not in seen:
            seen.add(u)
            ulids.append(u)

    if len(ulids) > 500:
        raise ValueError("too many entity_ulids (max 500)")

    q = (
        db.session.query(Entity)
        .filter(Entity.ulid.in_(ulids))
        .options(
            joinedload(Entity.person),
            joinedload(Entity.org),
        )
    )
    ents = q.all()
    by_ulid = {e.ulid: e for e in ents}

    out: dict[str, EntityLabelDTO] = {}
    for u in ulids:
        e = by_ulid.get(u)
        if e is None:
            out[u] = EntityLabelDTO(
                entity_ulid=u,
                kind="unknown",
                display_name=u,
                first_name=None,
                last_name=None,
                preferred_name=None,
                legal_name=None,
                dba_name=None,
            )
            continue

        if e.kind == "person" and e.person is not None:
            p = e.person
            pref = (p.preferred_name or "").strip() or None
            full = " ".join(x for x in [p.first_name, p.last_name] if x)
            disp = (pref or full).strip() or e.ulid
            out[u] = EntityLabelDTO(
                entity_ulid=e.ulid,
                kind="person",
                display_name=disp,
                first_name=p.first_name,
                last_name=p.last_name,
                preferred_name=p.preferred_name,
                legal_name=None,
                dba_name=None,
            )
            continue

        if e.kind == "org" and e.org is not None:
            o = e.org
            disp = (o.dba_name or o.legal_name or "").strip() or e.ulid
            out[u] = EntityLabelDTO(
                entity_ulid=e.ulid,
                kind="org",
                display_name=disp,
                first_name=None,
                last_name=None,
                preferred_name=None,
                legal_name=o.legal_name,
                dba_name=o.dba_name,
            )
            continue

        out[u] = EntityLabelDTO(
            entity_ulid=e.ulid,
            kind="unknown",
            display_name=e.ulid,
            first_name=None,
            last_name=None,
            preferred_name=None,
            legal_name=None,
            dba_name=None,
        )

    return out


# -----------------
# Internals
# -----------------
