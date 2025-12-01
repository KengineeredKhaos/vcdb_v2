# app/slices/entity/services.py
from __future__ import annotations

from typing import List, Optional, Set, Tuple

from sqlalchemy import asc
from sqlalchemy.orm import Session, joinedload, selectinload

from app.extensions import db, event_bus
from app.extensions.contracts.governance_v2 import get_role_catalogs
from app.lib.utils import (
    normalize_ein,
    normalize_email,
    normalize_phone,
    validate_ein,
    validate_email,
    validate_phone,
)

from .models import (
    Entity,
    EntityAddress,
    EntityContact,
    EntityOrg,
    EntityPerson,
    EntityRole,
)

# REFACTOR: ensure proper calls to governance_v2 contract
# -----------------
# Allowed Role Codes
# -----------------

# Prefer the governance_v2 contract; fall back to policy file in dev/test
try:
    from app.extensions.contracts.governance_v2 import (
        role_catalogs as _gov_role_catalogs,
    )
except Exception:
    _gov_role_catalogs = (
        None  # contract not wired yet (dev/test fallback path)
    )
"""
Any ALLOWED_*ROLE* constants → replace with:

Governance policy (governance.roles family) via contract call, or

DB-backed RoleCode catalog helper (list_domain_roles() in Governance) exposed
through governance_v2.

Any DTOs that are used by other slices → move definitions into
extensions/contracts/entity_v2.py and import them in entity.services
instead of defining them “locally”.
"""


def allowed_role_codes(session=None) -> Set[str]:
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
def _ensure_reqid(request_id: Optional[str]) -> str:
    if request_id is None or not str(request_id).strip():
        raise ValueError("request_id must be non-empty")
    return str(request_id)


# REFACTOR: ensure these show up in contracts


# -----------------
# DTO mappers (read shape for templates/contracts)
# -----------------
def _person_to_dto(p: EntityPerson) -> dict:
    ent = p.entity
    # We keep a SINGLE primary EntityContact row (is_primary=True);
    # it may carry email and/or phone (both in same row)
    primary_contact = None
    if ent and ent.contacts:
        primary_contact = next(
            (c for c in ent.contacts if c.is_primary), None
        )
    return {
        "entity_ulid": ent.ulid if ent else None,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "preferred_name": p.preferred_name,
        "email": primary_contact.email if primary_contact else None,
        "phone": primary_contact.phone if primary_contact else None,
        "created_at_utc": ent.created_at_utc if ent else None,
        "updated_at_utc": ent.updated_at_utc if ent else None,
    }


def _org_to_dto(o: EntityOrg) -> dict:
    ent = o.entity
    primary_contact = None
    if ent and ent.contacts:
        primary_contact = next(
            (c for c in ent.contacts if c.is_primary), None
        )
    return {
        "entity_ulid": ent.ulid if ent else None,
        "kind": "org",
        "legal_name": o.legal_name,
        "dba_name": o.dba_name,
        "ein": o.ein,
        "email": primary_contact.email if primary_contact else None,
        "phone": primary_contact.phone if primary_contact else None,
        "created_at_utc": ent.created_at_utc if ent else None,
        "updated_at_utc": ent.updated_at_utc if ent else None,
    }


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


def create_person_entity(
    *,
    first_name: str,
    last_name: str,
    preferred_name: str | None = None,
    session: Session | None = None,
) -> Entity:
    s = session or db.session
    e = Entity(kind="person")
    e.person = EntityPerson(
        first_name=first_name,
        last_name=last_name,
        preferred_name=preferred_name,
    )
    _validate_entity_shape(e)
    s.add(e)
    s.flush()  # assigns ULIDs and timestamps
    return e


def create_org_entity(
    *,
    legal_name: str,
    dba_name: str | None = None,
    ein: str | None = None,
    session: Session | None = None,
) -> Entity:
    s = session or db.session
    e = Entity(kind="org")
    e.org = EntityOrg(
        legal_name=legal_name,
        dba_name=dba_name,
        ein=ein,
    )
    _validate_entity_shape(e)
    s.add(e)
    s.flush()
    return e


# -----------------
# Entity as Person
# -----------------
def ensure_person(
    *,
    first_name: str,
    last_name: str,
    email: Optional[str],
    phone: Optional[str],
    request_id: str,
    actor_ulid: Optional[str],
) -> str:
    """
    Idempotently ensure an 'Entity(kind=person)' exists with a Person row.
    If email/phone are provided, upsert them as the single primary contact record.
    Returns entity_ulid.
    """
    _ensure_reqid(request_id)
    fn, ln = (first_name or "").strip(), (last_name or "").strip()
    if not fn or not ln:
        raise ValueError("first_name and last_name are required")

    email_norm = normalize_email(email) if email else None
    if email is not None and email_norm and not validate_email(email_norm):
        raise ValueError("Invalid email")
    phone_norm = normalize_phone(phone) if phone else None
    if phone is not None and phone_norm and not validate_phone(phone_norm):
        raise ValueError("Invalid phone")

    # Try to find an existing person by primary contact (email first, then phone)
    ent: Entity | None = None
    if email_norm:
        ent = (
            db.session.query(Entity)
            .join(EntityContact, EntityContact.entity_ulid == Entity.ulid)
            .filter(
                Entity.kind == "person",
                EntityContact.is_primary.is_(True),
                EntityContact.email == email_norm,
            )
            .first()
        )
    if not ent and phone_norm:
        ent = (
            db.session.query(Entity)
            .join(EntityContact, EntityContact.entity_ulid == Entity.ulid)
            .filter(
                Entity.kind == "person",
                EntityContact.is_primary.is_(True),
                EntityContact.phone == phone_norm,
            )
            .first()
        )

    created = False
    if not ent:
        ent = Entity(kind="person")  # ulid auto-filled via ULIDPK.default
        db.session.add(ent)
        db.session.flush()  # so ent.ulid is available
        db.session.add(
            EntityPerson(entity_ulid=ent.ulid, first_name=fn, last_name=ln)
        )
        created = True
    else:
        p = ent.person
        if p:
            p.first_name = fn or p.first_name
            p.last_name = ln or p.last_name
        else:
            db.session.add(
                EntityPerson(
                    entity_ulid=ent.ulid, first_name=fn, last_name=ln
                )
            )

    db.session.commit()

    # Upsert a single *primary* contact row
    if email is not None or phone is not None:
        _upsert_primary_contact(
            entity_ulid=ent.ulid, email=email_norm, phone=phone_norm
        )
        db.session.commit()

    # PII-safe, canon emit
    event_bus.emit(
        domain="entity",
        operation="person.created" if created else "person.upserted",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=ent.ulid,
        refs=None,
        changed={
            "fields": ["first_name", "last_name"]
            + (["email"] if email is not None else [])
            + (["phone"] if phone is not None else [])
        },
    )

    return ent.ulid


# -----------------
# Entity as Organization
# -----------------
def ensure_org(
    *,
    legal_name: str,
    dba_name: Optional[str] = None,
    ein: Optional[str] = None,
    request_id: str,
    actor_ulid: Optional[str],
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

    db.session.commit()
    # PII-safe, canon emit
    event_bus.emit(
        domain="entity",
        operation="org.created" if created else "org.upserted",
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
# Entity Contact (single primary record with email/phone fields)
# -----------------
def upsert_contacts(
    *,
    entity_ulid: str,
    email: Optional[str],
    phone: Optional[str],
    request_id: str,
    actor_ulid: Optional[str],
) -> None:
    """Upsert the single primary contact row for an entity; emits one event."""
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
    _upsert_primary_contact(entity_ulid=entity_ulid, email=em, phone=ph)
    if email is not None:
        changed["email"] = em
    if phone is not None:
        changed["phone"] = ph

    db.session.commit()
    if changed:
        event_bus.emit(
            domain="entity",
            operation="contact.upserted",
            request_id=request_id,
            actor_ulid=actor_ulid,
            target_ulid=entity_ulid,
            refs=None,
            changed={"fields": list(changed.keys())},
        )


# -----------------
# Entity Address
# -----------------
def upsert_address(
    *,
    entity_ulid: str,
    is_physical: bool = True,
    is_postal: bool = False,
    address1: str = "",
    address2: Optional[str] = None,
    city: str = "",
    state: str = "",
    postal_code: str = "",
    request_id: str,
    actor_ulid: Optional[str],
) -> str:
    """
    Create/update the single 'primary' address by (is_physical, is_postal) flags.
    Returns the address ulid.
    """
    _ensure_reqid(request_id)
    ent = db.session.get(Entity, entity_ulid)
    if not ent:
        raise ValueError("entity not found")

    def _norm(s: Optional[str]) -> Optional[str]:
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

    created = False
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
        created = True
    else:
        addr.address1 = _norm(address1) or addr.address1
        addr.address2 = _norm(address2)
        addr.city = _norm(city) or addr.city
        addr.state = _norm(state) or addr.state
        addr.postal_code = _norm(postal_code) or addr.postal_code

    db.session.commit()

    event_bus.emit(
        domain="entity",
        operation="address.upserted",
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
    actor_ulid: Optional[str] | None,
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
    db.session.commit()

    # attached
    event_bus.emit(
        domain="entity",
        operation="role.attached",
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
    actor_ulid: Optional[str] | None,
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
    db.session.commit()

    # removed
    event_bus.emit(
        domain="entity",
        operation="role.removed",
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
def person_view(person_ulid: str) -> Optional[dict]:
    p = db.session.get(EntityPerson, person_ulid)
    if not p:
        return None
    # eager-load primary contact for DTO
    _ = p.entity and p.entity.contacts  # touch relationship
    return _person_to_dto(p)


def list_people_with_role(
    role: str, page: int, per: int
) -> Tuple[List[dict], int]:
    page = max(int(page or 1), 1)
    per = min(max(int(per or 20), 1), 100)

    q = (
        db.session.query(EntityPerson)
        .join(Entity, EntityPerson.entity_ulid == Entity.ulid)
        .join(EntityRole, EntityRole.entity_ulid == Entity.ulid)
        .filter(EntityRole.role == role)
        .options(
            joinedload(EntityPerson.entity).options(
                selectinload(Entity.contacts), selectinload(Entity.roles)
            )
        )
        .order_by(
            asc(EntityPerson.last_name),
            asc(EntityPerson.first_name),
            asc(Entity.ulid),
        )
    )
    total = q.count()
    if total == 0:
        return [], 0

    rows = q.offset((page - 1) * per).limit(per).all()
    return [_person_to_dto(p) for p in rows], total


def list_orgs_with_role(
    role: str, page: int, per: int
) -> Tuple[List[dict], int]:
    page = max(int(page or 1), 1)
    per = min(max(int(per or 20), 1), 100)

    q = (
        db.session.query(EntityOrg)
        .join(Entity, EntityOrg.entity_ulid == Entity.ulid)
        .join(EntityRole, EntityRole.entity_ulid == Entity.ulid)
        .filter(EntityRole.role == role)
        .options(
            joinedload(EntityOrg.entity).options(
                selectinload(Entity.contacts), selectinload(Entity.roles)
            )
        )
        .order_by(asc(EntityOrg.legal_name), asc(Entity.ulid))
    )
    total = q.count()
    if total == 0:
        return [], 0

    rows = q.offset((page - 1) * per).limit(per).all()
    return [_org_to_dto(o) for o in rows], total


def list_people(*, page: int, per: int) -> Tuple[List[dict], int]:
    """
    List ALL people (no role filter), paginated.
    """
    page = max(int(page or 1), 1)
    per = min(max(int(per or 20), 1), 100)

    q = (
        db.session.query(EntityPerson)
        .join(Entity, EntityPerson.entity_ulid == Entity.ulid)
        .options(
            joinedload(EntityPerson.entity).options(
                selectinload(Entity.contacts), selectinload(Entity.roles)
            )
        )
        .order_by(
            asc(EntityPerson.last_name),
            asc(EntityPerson.first_name),
            asc(Entity.ulid),
        )
    )
    total = q.count()
    if total == 0:
        return [], 0
    rows = q.offset((page - 1) * per).limit(per).all()
    return [_person_to_dto(p) for p in rows], total


def list_orgs(
    *, roles: List[str], page: int, per: int
) -> Tuple[List[dict], int]:
    """
    List orgs whose entity has ANY of the supplied roles (OR semantics),
    typically roles=['resource','sponsor'].
    """
    page = max(int(page or 1), 1)
    per = min(max(int(per or 20), 1), 100)

    # Select orgs where the backing entity has any of the roles
    q = (
        db.session.query(EntityOrg)
        .join(Entity, EntityOrg.entity_ulid == Entity.ulid)
        .join(EntityRole, EntityRole.entity_ulid == Entity.ulid)
        .filter(EntityRole.role.in_(roles))
        .options(
            joinedload(EntityOrg.entity).options(
                selectinload(Entity.contacts), selectinload(Entity.roles)
            )
        )
        .order_by(asc(EntityOrg.legal_name), asc(Entity.ulid))
        .distinct(EntityOrg.ulid)  # avoid dup rows for multi-role orgs
    )

    total = q.count()
    if total == 0:
        return [], 0

    rows = q.offset((page - 1) * per).limit(per).all()
    return [_org_to_dto(o) for o in rows], total


# -----------------
# Internals
# -----------------
def _upsert_primary_contact(
    *, entity_ulid: str, email: Optional[str], phone: Optional[str]
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
