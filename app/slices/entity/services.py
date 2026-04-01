# app/slices/entity/services.py
from __future__ import annotations

import re

from sqlalchemy import asc, desc
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.geo import is_state_code
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
    EntityAddressSummaryDTO,
    EntityCardDTO,
    EntityContactSummaryDTO,
    EntityLabelDTO,
    OperatorCoreCreatedDTO,
    OrgView,
    PersonView,
    map_org_view,
    map_person_view,
    to_address_summary,
    to_contact_summary,
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


_ZIP5_RE = re.compile(r"^\d{5}$")


def allowed_role_codes() -> set[str]:
    rows = (
        db.session.query(EntityRole.role)
        .filter(EntityRole.archived_at.is_(None))
        .distinct()
        .all()
    )
    return {str(r[0]).strip().lower() for r in rows if r and r[0]}


# -----------------
# Internal guard
# -----------------


def _require_entity(entity_ulid: str) -> Entity:
    ent = db.session.get(Entity, entity_ulid)
    if ent is None:
        raise ValueError("entity not found")
    return ent


def _normalize_contact_value(
    *,
    email: str | None,
    phone: str | None,
) -> tuple[str | None, str | None]:
    em = normalize_email(email) if email is not None else None
    if email is not None and em and not validate_email(em):
        raise ValueError("Invalid email")

    ph = normalize_phone(phone) if phone is not None else None
    if phone is not None and ph and not validate_phone(ph):
        raise ValueError("Invalid phone")

    if not em and not ph:
        raise ValueError("email or phone is required")

    return em, ph


def _demote_conflicting_primaries(
    *,
    entity_ulid: str,
    for_email: bool,
    for_phone: bool,
    exclude_contact_ulid: str | None,
) -> None:
    rows = (
        db.session.query(EntityContact)
        .filter_by(entity_ulid=entity_ulid)
        .filter(EntityContact.archived_at.is_(None))
        .all()
    )
    for row in rows:
        if not row.is_primary:
            continue
        if exclude_contact_ulid and row.ulid == exclude_contact_ulid:
            continue
        has_conflict = (for_email and bool(row.email)) or (
            for_phone and bool(row.phone)
        )
        if has_conflict:
            row.is_primary = False


def add_contact(
    *,
    entity_ulid: str,
    email: str | None = None,
    phone: str | None = None,
    is_primary: bool = False,
    request_id: str,
    actor_ulid: str | None,
) -> str:
    """
    Add an active contact row.

    Notes:
    - New writes may carry email, phone, or both.
    - Primary is enforced per contact-type by demoting other active rows that
      carry the same type(s).
    - Exact active duplicates are treated idempotently.
    """
    _ensure_reqid(request_id)
    _require_entity(entity_ulid)

    em, ph = _normalize_contact_value(email=email, phone=phone)

    row = (
        db.session.query(EntityContact)
        .filter_by(entity_ulid=entity_ulid, email=em, phone=ph)
        .filter(EntityContact.archived_at.is_(None))
        .order_by(
            desc(EntityContact.updated_at_utc),
            desc(EntityContact.created_at_utc),
        )
        .first()
    )

    created = False
    changed_fields: list[str] = []

    if row is None:
        row = EntityContact(
            entity_ulid=entity_ulid,
            email=em,
            phone=ph,
            is_primary=False,
        )
        db.session.add(row)
        created = True
        if em:
            changed_fields.append("email")
        if ph:
            changed_fields.append("phone")

    db.session.flush()

    if is_primary and not row.is_primary:
        _demote_conflicting_primaries(
            entity_ulid=entity_ulid,
            for_email=bool(row.email),
            for_phone=bool(row.phone),
            exclude_contact_ulid=row.ulid,
        )
        row.is_primary = True
        changed_fields.append("is_primary")

    db.session.flush()

    if created or changed_fields:
        event_bus.emit(
            domain="entity",
            operation="contact_added" if created else "contact_updated",
            request_id=request_id,
            actor_ulid=actor_ulid,
            target_ulid=entity_ulid,
            refs={"contact_ulid": row.ulid},
            changed={"fields": list(dict.fromkeys(changed_fields))},
            happened_at_utc=now_iso8601_ms(),
        )

    return row.ulid


def _ensure_reqid(request_id: str | None) -> str:
    if request_id is None or not str(request_id).strip():
        raise ValueError("request_id must be non-empty")
    return str(request_id)


def _clean_person_name(label: str, value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{label} is required.")
    return clean


def _clean_optional_name(value: str | None) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def create_operator_core(
    *,
    first_name: str,
    last_name: str,
    preferred_name: str,
    request_id: str,
    actor_ulid: str | None,
) -> OperatorCoreCreatedDTO:
    _ensure_reqid(request_id)
    fn = _clean_person_name("first_name", first_name)
    ln = _clean_person_name("last_name", last_name)
    pn = _clean_optional_name(preferred_name)

    ent = Entity(kind="person")
    ent.person = EntityPerson(
        first_name=fn,
        last_name=ln,
        preferred_name=pn,
        dob=None,
        last_4=None,
    )
    db.session.add(ent)
    db.session.flush()

    event_bus.emit(
        domain="entity",
        operation="operator_core_created",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=ent.ulid,
        refs=None,
        changed={"fields": ["first_name", "last_name"]},
    )

    display_name = " ".join(part for part in ((pn or fn), ln) if part).strip()
    return OperatorCoreCreatedDTO(
        entity_ulid=ent.ulid,
        entity_kind="person",
        display_name=display_name or ent.ulid,
    )


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
    _ensure_reqid(request_id)

    fn = _clean_person_name("first_name", first_name)
    ln = _clean_person_name("last_name", last_name)

    em = normalize_email(email) if email is not None else None
    if email is not None and em and not validate_email(em):
        raise ValueError("Invalid email")

    ph = normalize_phone(phone) if phone is not None else None
    if phone is not None and ph and not validate_phone(ph):
        raise ValueError("Invalid phone")

    def _find_by_email(value: str) -> Entity | None:
        return (
            db.session.query(Entity)
            .join(EntityContact, EntityContact.entity_ulid == Entity.ulid)
            .filter(
                Entity.kind == "person",
                Entity.archived_at.is_(None),
                EntityContact.archived_at.is_(None),
                EntityContact.email == value,
            )
            .first()
        )

    def _find_by_phone(value: str) -> Entity | None:
        return (
            db.session.query(Entity)
            .join(EntityContact, EntityContact.entity_ulid == Entity.ulid)
            .filter(
                Entity.kind == "person",
                Entity.archived_at.is_(None),
                EntityContact.archived_at.is_(None),
                EntityContact.phone == value,
            )
            .first()
        )

    ent: Entity | None = None
    if em:
        ent = _find_by_email(em)
    if not ent and ph:
        ent = _find_by_phone(ph)

    if ent:
        # If we matched an existing person, make sure any newly supplied
        # contact method is attached/upserted using the normal contact path.
        if em is not None or ph is not None:
            edit_contact(
                entity_ulid=ent.ulid,
                email=em,
                phone=ph,
                request_id=request_id,
                actor_ulid=actor_ulid,
            )
        return ent.ulid

    created = create_operator_core(
        first_name=fn,
        last_name=ln,
        preferred_name="",
        request_id=request_id,
        actor_ulid=actor_ulid,
    )

    if em is not None or ph is not None:
        edit_contact(
            entity_ulid=created.entity_ulid,
            email=em,
            phone=ph,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )

    return created.entity_ulid


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
    Upsert the best/current contact choices for the supplied method types.

    This convenience path now writes one active primary row per supplied
    method, which aligns better with the active/archive/primary model than the
    older single-row primary-contact behavior.
    """
    _ensure_reqid(request_id)

    if email is None and phone is None:
        raise ValueError("email or phone is required")

    if email is not None:
        add_contact(
            entity_ulid=entity_ulid,
            email=email,
            is_primary=True,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )

    if phone is not None:
        add_contact(
            entity_ulid=entity_ulid,
            phone=phone,
            is_primary=True,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )

    return ()


def set_contact_primary(
    *,
    contact_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> bool:
    _ensure_reqid(request_id)

    row = db.session.get(EntityContact, contact_ulid)
    if row is None:
        raise ValueError("contact not found")
    if row.archived_at is not None:
        raise ValueError("contact is archived")
    if row.is_primary:
        return False

    _demote_conflicting_primaries(
        entity_ulid=row.entity_ulid,
        for_email=bool(row.email),
        for_phone=bool(row.phone),
        exclude_contact_ulid=row.ulid,
    )
    row.is_primary = True
    db.session.flush()

    event_bus.emit(
        domain="entity",
        operation="contact_primary_set",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.entity_ulid,
        refs={"contact_ulid": row.ulid},
        changed={"fields": ["is_primary"]},
        happened_at_utc=now_iso8601_ms(),
    )
    return True


def archive_contact(
    *,
    contact_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> bool:
    _ensure_reqid(request_id)

    row = db.session.get(EntityContact, contact_ulid)
    if row is None or row.archived_at is not None:
        return False

    row.archived_at = now_iso8601_ms()
    row.is_primary = False
    db.session.flush()

    event_bus.emit(
        domain="entity",
        operation="contact_archived",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.entity_ulid,
        refs={"contact_ulid": row.ulid},
        changed={"fields": ["archived_at"]},
        happened_at_utc=row.archived_at,
    )
    return True


# -----------------
# Entity Address
# -----------------


def _normalize_zip5(v: str) -> str:
    s = (v or "").strip()
    if not _ZIP5_RE.match(s):
        raise ValueError("postal_code must be 5 digits")
    return s


def _norm_str(
    label: str, value: str, *, required: bool = False
) -> str | None:
    clean = (value or "").strip()
    if required and not clean:
        raise ValueError(f"{label} is required")
    return clean or None


def _active_address_rows(entity_ulid: str) -> list[EntityAddress]:
    return (
        db.session.query(EntityAddress)
        .filter_by(entity_ulid=entity_ulid)
        .filter(EntityAddress.archived_at.is_(None))
        .order_by(
            desc(EntityAddress.updated_at_utc),
            desc(EntityAddress.created_at_utc),
        )
        .all()
    )


def _address_matches(
    row: EntityAddress,
    *,
    address1: str,
    address2: str | None,
    city: str,
    state: str,
    postal_code: str,
) -> bool:
    return (
        row.address1 == address1
        and (row.address2 or None) == address2
        and row.city == city
        and row.state == state
        and row.postal_code == postal_code
    )


def _move_address_role(
    *,
    current: EntityAddress | None,
    target: EntityAddress,
    role_field: str,
    as_of: str,
    changed_fields: list[str],
) -> None:
    if current is not None and current.ulid != target.ulid:
        if getattr(current, "is_physical") and getattr(current, "is_postal"):
            setattr(current, role_field, False)
        else:
            current.archived_at = as_of
            changed_fields.append(f"archived_{role_field}")

    if not getattr(target, role_field):
        setattr(target, role_field, True)
        changed_fields.append(role_field)


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
    Upsert active address roles.

    Rules:
    - at most one active physical role per entity
    - at most one active postal role per entity
    - the same address row may satisfy both roles
    - replacing one role archives or downgrades the prior active row
    """
    _ensure_reqid(request_id)
    _require_entity(entity_ulid)

    phy = bool(is_physical)
    post = bool(is_postal)
    if not phy and not post:
        phy = True

    a1 = _norm_str("address1", address1, required=True) or ""
    a2 = _norm_str("address2", address2)
    cty = _norm_str("city", city, required=True) or ""
    st = (_norm_str("state", state, required=True) or "").upper()
    if not is_state_code(st):
        raise ValueError("invalid state code")
    zipc = _normalize_zip5(postal_code)

    rows = _active_address_rows(entity_ulid)

    target = next(
        (
            row
            for row in rows
            if _address_matches(
                row,
                address1=a1,
                address2=a2,
                city=cty,
                state=st,
                postal_code=zipc,
            )
        ),
        None,
    )

    created = False
    changed_fields: list[str] = []
    as_of = now_iso8601_ms()

    if target is None:
        target = EntityAddress(
            entity_ulid=entity_ulid,
            is_physical=False,
            is_postal=False,
            address1=a1,
            address2=a2,
            city=cty,
            state=st,
            postal_code=zipc,
        )
        db.session.add(target)
        db.session.flush()
        created = True
        changed_fields.extend(
            ["address1", "city", "state", "postal_code"]
            + (["address2"] if a2 else [])
        )

    current_physical = next((row for row in rows if row.is_physical), None)
    current_postal = next((row for row in rows if row.is_postal), None)

    if phy:
        _move_address_role(
            current=current_physical,
            target=target,
            role_field="is_physical",
            as_of=as_of,
            changed_fields=changed_fields,
        )
    if post:
        _move_address_role(
            current=current_postal,
            target=target,
            role_field="is_postal",
            as_of=as_of,
            changed_fields=changed_fields,
        )

    db.session.flush()

    if created or changed_fields:
        event_bus.emit(
            domain="entity",
            operation="address_upserted",
            request_id=request_id,
            actor_ulid=actor_ulid,
            target_ulid=entity_ulid,
            refs={"address_ulid": target.ulid},
            changed={"fields": list(dict.fromkeys(changed_fields))},
            happened_at_utc=as_of,
        )

    return target.ulid


def archive_address(
    *,
    address_ulid: str,
    request_id: str,
    actor_ulid: str | None,
) -> bool:
    _ensure_reqid(request_id)

    row = db.session.get(EntityAddress, address_ulid)
    if row is None or row.archived_at is not None:
        return False

    row.archived_at = now_iso8601_ms()
    db.session.flush()

    event_bus.emit(
        domain="entity",
        operation="address_archived",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=row.entity_ulid,
        refs={"address_ulid": row.ulid},
        changed={"fields": ["archived_at"]},
        happened_at_utc=row.archived_at,
    )
    return True


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


def list_people_by_role(
    *,
    role: str,
    page: int,
    per_page: int,
) -> Page[PersonView]:
    q = (
        db.session.query(EntityPerson)
        .join(Entity, EntityPerson.entity_ulid == Entity.ulid)
        .join(EntityRole, EntityRole.entity_ulid == Entity.ulid)
        .filter(EntityRole.role == role)
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
        .distinct(EntityPerson.entity_ulid)
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
# Cross-slice
# Entity Rolodex
# labels, contacts,
# addresses access
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


def get_entity_contact_summary(
    *, entity_ulids: list[str]
) -> dict[str, EntityContactSummaryDTO]:
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

    rows = (
        db.session.query(EntityContact)
        .filter(EntityContact.entity_ulid.in_(ulids))
        .filter(EntityContact.archived_at.is_(None))
        .order_by(
            EntityContact.entity_ulid.asc(),
            desc(EntityContact.is_primary),
            desc(EntityContact.updated_at_utc),
            desc(EntityContact.created_at_utc),
        )
        .all()
    )

    by_ulid: dict[str, list[EntityContact]] = {u: [] for u in ulids}
    for c in rows:
        by_ulid.setdefault(c.entity_ulid, []).append(c)

    out: dict[str, EntityContactSummaryDTO] = {}
    for u in ulids:
        out[u] = to_contact_summary(u, by_ulid.get(u, []))
    return out


def get_entity_address_summary(
    *, entity_ulids: list[str]
) -> dict[str, EntityAddressSummaryDTO]:
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

    rows = (
        db.session.query(EntityAddress)
        .filter(EntityAddress.entity_ulid.in_(ulids))
        .filter(EntityAddress.archived_at.is_(None))
        .order_by(
            EntityAddress.entity_ulid.asc(),
            desc(EntityAddress.updated_at_utc),
            desc(EntityAddress.created_at_utc),
        )
        .all()
    )

    by_ulid: dict[str, list[EntityAddress]] = {u: [] for u in ulids}
    for a in rows:
        by_ulid.setdefault(a.entity_ulid, []).append(a)

    out: dict[str, EntityAddressSummaryDTO] = {}
    for u in ulids:
        out[u] = to_address_summary(u, by_ulid.get(u, []))
    return out


def get_entity_cards(
    *,
    entity_ulids: list[str],
    include_contacts: bool = False,
    include_addresses: bool = False,
) -> dict[str, EntityCardDTO]:
    labels = get_entity_labels(entity_ulids=entity_ulids)

    contacts = (
        get_entity_contact_summary(entity_ulids=entity_ulids)
        if include_contacts
        else {}
    )
    addresses = (
        get_entity_address_summary(entity_ulids=entity_ulids)
        if include_addresses
        else {}
    )

    out: dict[str, EntityCardDTO] = {}
    for u, lab in labels.items():
        out[u] = EntityCardDTO(
            entity_ulid=u,
            label=lab,
            contacts=contacts.get(u) if include_contacts else None,
            addresses=addresses.get(u) if include_addresses else None,
        )
    return out


# -----------------
# Internals
# -----------------
