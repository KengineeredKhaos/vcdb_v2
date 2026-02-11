# app/slices/entity/services.py
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import asc
from sqlalchemy.orm import Session, joinedload, selectinload

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

from .mapper import OrgView, PersonView, map_org_view, map_person_view
from .models import (
    Entity,
    EntityAddress,
    EntityContact,
    EntityOrg,
    EntityPerson,
    EntityRole,
)

"""
Format Hints:

The uniformity pattern
1) Use explicit naming everywhere
Never overload ent to mean both “entity_ulid string” and “Entity model object”.

Use:
entity_ulid: str → the ULID string (PK/FK)
entity: Entity → the Entity ORM object
person: EntityPerson
org: EntityOrg
primary_contact: EntityContact | None

2) Split service functions into two categories (and name them accordingly)
This is the simplest pattern that stays consistent across slices:

Queries (read-only):
Prefix with q_ (or just get_/list_ if you hate prefixes)
No request_id required
Return typed view shapes or typed DTOs

Commands (mutations):
Prefix with cmd_ / create_ / upsert_ / ensure_
Always include: request_id, actor_ulid
Flush-only (route owns commit/rollback)

3) Strongly type “view dicts” with TypedDict (no Any)
If the return is “a dict for templates,” don’t return dict — return a TypedDict.

This gives you:
type safety
stable keys
no need for Any
no aliasing of model fields (keys can stay explicit)

# ---- View shape (internal: templates/forms only) ----

class PersonView(TypedDict):
    entity_ulid: str
    kind: str
    first_name: str
    last_name: str
    preferred_name: str | None
    email: str | None
    phone: str | None
    created_at_utc: datetime | None
    updated_at_utc: datetime | None


def _map_person_view(person: EntityPerson) -> PersonView:
    # Invariant: EntityPerson PK == FK -> entity_entity.ulid
    entity_ulid: str = person.entity_ulid

    entity: Entity | None = person.entity
    if entity is None:
        # This should never happen if the facet invariant is upheld.
        raise ValueError("EntityPerson.entity relationship missing")

    primary_contact: EntityContact | None = None
    if entity.contacts:
        primary_contact = next((c for c in entity.contacts if c.is_primary), None)

    return {
        "entity_ulid": entity_ulid,
        "kind": "person",
        "first_name": person.first_name,
        "last_name": person.last_name,
        "preferred_name": person.preferred_name,
        "email": primary_contact.email if primary_contact else None,
        "phone": primary_contact.phone if primary_contact else None,
        "created_at_utc": entity.created_at_utc,
        "updated_at_utc": entity.updated_at_utc,
    }

def q_person_view(*, entity_ulid: str, session: Session | None = None) -> PersonView | None:
    s = session or db.session
    person = s.get(EntityPerson, entity_ulid)
    if person is None:
        return None
    # ideally loaded via eager options in the query; OK to lazy-load for single view
    _ = person.entity and person.entity.contacts
    return _map_person_view(person)

For consistency everywhere, adopt these three rules:

Identity arg naming:
Always use entity_ulid for identity keys (facet PK=FK)
Never introduce person_ulid/resource_ulid/... unless it’s not identity (rare)

Command signature template:
def cmd_xxx(
    *, ...,
    request_id: str,
    actor_ulid: str | None,
    session: Session | None = None
) -> ResultType:

Query signature template:

def q_xxx(*, ..., session: Session | None = None) -> ViewType | DTOType:

Then enforce it with quick greps + a couple of ruff rules (and by deleting back-compat shims as you go).

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


# REFACTOR: ensure these show up in contracts


# -----------------
# DTO mappers
# (read shape for templates/contracts)
# -----------------
"""
These are internal-only dictionaries for view mapping and forms.
DO NOT refernce these for API data transfer.
"""


@dataclass(frozen=True, slots=True)
class EnsurePersonResult:
    entity_ulid: str
    created: bool


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


def _first_email_phone(entity_ulid: str) -> list[dict[str, str]]:
    q = (
        query(EntityContact)
        .filter(EntityContact.entity_ulid == entity_ulid)
        .order_by(EntityContact.created_at_utc.asc())
    )
    emails: list[dict[str, str]] = []
    phones: list[dict[str, str]] = []
    for c in q:
        if c.kind == "email" and not emails:
            emails.append({"kind": "email", "value": c.value})
        if c.kind == "phone" and not phones:
            phones.append({"kind": "phone", "value": c.value})
        if emails and phones:
            break
    return emails + phones


def get_entity_card(entity_ulid: str) -> EntityCardDTO:
    where = "entity_v2.get_entity_card"
    try:
        ent = get(Entity, entity_ulid)
        if not ent:
            raise ContractError(
                "not_found",
                where,
                "entity not found",
                404,
                data={"entity_ulid": entity_ulid},
            )

        person = get(EntityPerson, entity_ulid)
        org = None if person else get(EntityOrg, entity_ulid)

        if person:
            display = (
                f"{person.last_name}, {person.first_name}".strip().strip(",")
            )
            etype = "person"
        elif org:
            display = org.legal_name
            etype = "org"
        else:
            display = entity_ulid
            etype = "org"

        return EntityCardDTO(
            ulid=entity_ulid,
            type=etype,
            display_name=display,
            contacts=_first_email_phone(entity_ulid),
            address_short=None,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def get_entity_core(entity_ulid: str) -> EntityCoreDTO:
    where = "entity_v2.get_entity_core"
    try:
        ent = get(Entity, entity_ulid)
        if not ent:
            raise ContractError(
                "not_found",
                where,
                "entity not found",
                404,
                data={"entity_ulid": entity_ulid},
            )
        return EntityCoreDTO(
            ulid=ent.ulid,
            kind=(ent.kind or "").strip().lower(),
            archived_at=ent.archived_at,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


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
# Entity Contact (single primary record with email/phone fields)
# -----------------
def upsert_contacts(
    *,
    entity_ulid: str,
    email: str | None,
    phone: str | None,
    request_id: str,
    actor_ulid: str | None,
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
def person_view(entity_ulid: str) -> dict | None:
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
# Internals
# -----------------
def _upsert_primary_contact(
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
# New Wizard-related
# function definitions
# below this banner
# -----------------


def cmd_person_ensure_by_contact(
    *,
    first_name: str,
    last_name: str,
    email: str | None,
    phone: str | None,
    request_id: str,
    actor_ulid: str | None,
) -> EnsurePersonResult:
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    if not fn or not ln:
        raise ValueError("first_name and last_name are required")

    email_norm = normalize_email(email) if email else None
    if email is not None and email_norm and not validate_email(email_norm):
        raise ValueError("invalid email")

    phone_norm = normalize_phone(phone) if phone else None
    if phone is not None and phone_norm and not validate_phone(phone_norm):
        raise ValueError("invalid phone")

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
        ent = Entity(kind="person")
        db.session.add(ent)
        db.session.flush()

        db.session.add(
            EntityPerson(
                entity_ulid=ent.ulid,
                first_name=fn,
                last_name=ln,
            )
        )
        created = True
    else:
        p = ent.person
        if p:
            p.first_name = fn
            p.last_name = ln
        else:
            db.session.add(
                EntityPerson(
                    entity_ulid=ent.ulid,
                    first_name=fn,
                    last_name=ln,
                )
            )

    db.session.flush()

    # optional: upsert primary contact if explicitly provided
    if email is not None or phone is not None:
        _upsert_primary_contact(
            entity_ulid=ent.ulid,
            email=email_norm,
            phone=phone_norm,
        )
        db.session.flush()

    event_bus.emit(
        domain="entity",
        operation="person_created" if created else "person_upserted",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=ent.ulid,
        refs=None,
        changed={
            "fields": ["first_name", "last_name"]
            + (["email"] if email is not None else [])
            + (["phone"] if phone is not None else []),
        },
    )

    return EnsurePersonResult(entity_ulid=ent.ulid, created=created)
