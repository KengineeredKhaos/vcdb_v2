# app/slices/entity/services_wizard.py

"""
Entity creation wizard (slice-local).
Wizard designed explictly and solely for entity creation.
DO NOT hijack or repurpose these routes!
Wizard is *only* for initial creation of a brand-new Entity in a minimally
complete, valid, editable state.

All general Edit/Update paths must flow through the Entity contract.

"""

from __future__ import annotations

import re

from sqlalchemy import select

from app.extensions import db, event_bus
from app.extensions.contracts import governance_v2
from app.lib.chrono import now_iso8601_ms
from app.lib.geo import is_state_code
from app.lib.utils import (
    normalize_dob,
    normalize_ein,
    normalize_email,
    normalize_phone,
    validate_dob,
    validate_ein,
    validate_email,
    validate_phone,
)

from .guards import _validate_entity_shape, require_wizard_entity
from .mapper import WizardEntityCreatedDTO, WizardStepDTO
from .models import (
    Entity,
    EntityAddress,
    EntityContact,
    EntityOrg,
    EntityPerson,
    EntityRole,
)

# -----------------
# Constants / Tools
# -----------------

_ZIP5_RE = re.compile(r"^\d{5}$")


# -----------------
# Local Helper
# Functions
# -----------------


def _req_str(label: str, v: str) -> str:
    s = (v or "").strip()
    if not s:
        raise ValueError(f"{label} is required")
    return s


def _opt_str(v: str | None) -> str | None:
    s = (v or "").strip()
    return s or None


def _normalize_zip5(v: str) -> str:
    s = (v or "").strip()
    if not _ZIP5_RE.match(s):
        raise ValueError("postal_code must be 5 digits")
    return s


def _display_name_person(
    *, first_name: str, last_name: str, preferred_name: str | None
) -> str:
    given = (preferred_name or first_name).strip()
    fam = last_name.strip()
    return f"{given} {fam}".strip()


def _display_name_org(*, legal_name: str, dba_name: str | None) -> str:
    return (dba_name or legal_name).strip()


# -----------------
# Wizard Step Check
# -----------------


def wizard_next_step(*, entity_ulid: str) -> str:
    ent = require_wizard_entity(entity_ulid)
    _validate_entity_shape(ent)

    has_contact = (
        db.session.execute(
            select(EntityContact).where(
                EntityContact.entity_ulid == entity_ulid,
                EntityContact.is_primary.is_(True),
                EntityContact.archived_at.is_(None),
            )
        ).scalar_one_or_none()
        is not None
    )
    if not has_contact:
        return "entity.wizard_contact"

    has_addr = (
        db.session.execute(
            select(EntityAddress).where(
                EntityAddress.entity_ulid == entity_ulid,
                EntityAddress.archived_at.is_(None),
            )
        ).scalar_one_or_none()
        is not None
    )
    if not has_addr:
        return "entity.wizard_address"

    has_role = (
        db.session.execute(
            select(EntityRole).where(
                EntityRole.entity_ulid == entity_ulid,
                EntityRole.archived_at.is_(None),
            )
        ).scalar_one_or_none()
        is not None
    )
    if not has_role:
        return "entity.wizard_role_get"

    return "entity.wizard_next"


# -----------------
# Entity Creation
# Step 1 - Core
# -----------------


def wizard_create_person_core(
    *,
    first_name: str,
    last_name: str,
    preferred_name: str | None = None,
    dob: str | None = None,
    last_4: str | None = None,
    request_id: str,
    actor_ulid: str | None,
) -> WizardEntityCreatedDTO:
    fn = _req_str("first_name", first_name)
    ln = _req_str("last_name", last_name)
    pn = _opt_str(preferred_name)

    dob_raw = _opt_str(dob)
    dob_norm = normalize_dob(dob_raw) if dob_raw else None
    if dob_norm and not validate_dob(dob_norm):
        raise ValueError("invalid dob")

    l4_raw = _opt_str(last_4)
    if l4_raw and ((not l4_raw.isdigit()) or len(l4_raw) != 4):
        raise ValueError("last_4 must be 4 digits")

    ent = Entity(kind="person")
    ent.person = EntityPerson(
        first_name=fn,
        last_name=ln,
        preferred_name=pn,
        dob=dob_norm,
        last_4=l4_raw,
    )
    db.session.add(ent)
    db.session.flush()

    as_of = now_iso8601_ms()
    event_bus.emit(
        domain="entity",
        operation="wizard_person_core_created",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=ent.ulid,
        refs=None,
        changed={"fields": ["first_name", "last_name"]},
        happened_at_utc=as_of,
    )

    return WizardEntityCreatedDTO(
        entity_ulid=ent.ulid,
        entity_kind="person",
        display_name=_display_name_person(
            first_name=fn,
            last_name=ln,
            preferred_name=pn,
        ),
        next_step="entity.wizard_contact",
    )


def wizard_create_org_core(
    *,
    legal_name: str,
    dba_name: str | None = None,
    ein: str | None = None,
    request_id: str,
    actor_ulid: str | None,
) -> WizardEntityCreatedDTO:
    ln = _req_str("legal_name", legal_name)
    dba = _opt_str(dba_name)

    ein_raw = _opt_str(ein)
    ein_norm = normalize_ein(ein_raw) if ein_raw else None
    if ein_norm and not validate_ein(ein_norm):
        raise ValueError("invalid ein")

    ent = Entity(kind="org")
    ent.org = EntityOrg(legal_name=ln, dba_name=dba, ein=ein_norm)
    db.session.add(ent)
    db.session.flush()

    as_of = now_iso8601_ms()
    event_bus.emit(
        domain="entity",
        operation="wizard_org_core_created",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=ent.ulid,
        refs=None,
        changed={"fields": ["legal_name"]},
        happened_at_utc=as_of,
    )

    return WizardEntityCreatedDTO(
        entity_ulid=ent.ulid,
        entity_kind="org",
        display_name=_display_name_org(legal_name=ln, dba_name=dba),
        next_step="entity.wizard_contact",
    )


# -----------------
# Step 2 — Contact
# -----------------


def wizard_contact(
    *,
    entity_ulid: str,
    email: str | None,
    phone: str | None,
    request_id: str,
    actor_ulid: str | None,
) -> WizardStepDTO:
    return wizard_upsert_primary_contact(
        entity_ulid=entity_ulid,
        email=email,
        phone=phone,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )


def wizard_upsert_primary_contact(
    *,
    entity_ulid: str,
    email: str | None,
    phone: str | None,
    request_id: str,
    actor_ulid: str | None,
) -> WizardStepDTO:
    ent = require_wizard_entity(entity_ulid)
    _validate_entity_shape(ent)

    email_norm = None
    phone_norm = None

    if email is not None:
        email_norm = normalize_email(email)
        if email_norm and not validate_email(email_norm):
            raise ValueError("invalid email")

    if phone is not None:
        phone_norm = normalize_phone(phone)
        if phone_norm and not validate_phone(phone_norm):
            raise ValueError("invalid phone")

    changed: list[str] = []

    c = db.session.execute(
        select(EntityContact).where(
            EntityContact.entity_ulid == entity_ulid,
            EntityContact.is_primary.is_(True),
            EntityContact.archived_at.is_(None),
        )
    ).scalar_one_or_none()

    created = False
    if c is None:
        created = True
        c = EntityContact(
            entity_ulid=entity_ulid,
            is_primary=True,
            email=email_norm,
            phone=phone_norm,
        )
        db.session.add(c)
        if email is not None:
            changed.append("email")
        if phone is not None:
            changed.append("phone")
    else:
        if email is not None and c.email != email_norm:
            c.email = email_norm
            changed.append("email")
        if phone is not None and c.phone != phone_norm:
            c.phone = phone_norm
            changed.append("phone")

    db.session.flush()

    as_of = now_iso8601_ms()
    event_bus.emit(
        domain="entity",
        operation="wizard_contact_upserted",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=entity_ulid,
        refs=None,
        changed={"fields": list(changed)},
        happened_at_utc=as_of,
    )

    return WizardStepDTO(
        entity_ulid=entity_ulid,
        created=created,
        changed_fields=tuple(changed),
        next_step="entity.wizard_address",
    )


# -----------------
# Step 3 — Address
# -----------------


def wizard_address(
    *,
    entity_ulid: str,
    is_physical: bool | None,
    is_postal: bool | None,
    address1: str,
    address2: str | None,
    city: str,
    state: str,
    postal_code: str,
    request_id: str,
    actor_ulid: str | None,
) -> WizardStepDTO:
    return wizard_upsert_address(
        entity_ulid=entity_ulid,
        is_physical=is_physical,
        is_postal=is_postal,
        address1=address1,
        address2=address2,
        city=city,
        state=state,
        postal_code=postal_code,
        request_id=request_id,
        actor_ulid=actor_ulid,
    )


def wizard_upsert_address(
    *,
    entity_ulid: str,
    is_physical: bool | None,
    is_postal: bool | None,
    address1: str,
    address2: str | None,
    city: str,
    state: str,
    postal_code: str,
    request_id: str,
    actor_ulid: str | None,
) -> WizardStepDTO:
    ent = require_wizard_entity(entity_ulid)
    _validate_entity_shape(ent)

    # Default to physical=True if user doesn't explicitly choose.
    phy = True if is_physical is None else bool(is_physical)
    post = False if is_postal is None else bool(is_postal)
    if not phy and not post:
        phy = True

    a1 = _req_str("address1", address1)
    a2 = _opt_str(address2)
    cty = _req_str("city", city)

    st = _req_str("state", state).upper()
    if not is_state_code(st):
        raise ValueError("invalid state code")

    zipc = _normalize_zip5(postal_code)

    addr = db.session.execute(
        select(EntityAddress).where(
            EntityAddress.entity_ulid == entity_ulid,
            EntityAddress.archived_at.is_(None),
        )
    ).scalar_one_or_none()

    changed: list[str] = []
    created = False

    if addr is None:
        created = True
        addr = EntityAddress(
            entity_ulid=entity_ulid,
            is_physical=phy,
            is_postal=post,
            address1=a1,
            address2=a2,
            city=cty,
            state=st,
            postal_code=zipc,
        )
        db.session.add(addr)
        changed.extend(
            [
                "is_physical",
                "is_postal",
                "address1",
                "city",
                "state",
                "postal_code",
            ]
        )
        if a2 is not None:
            changed.append("address2")
    else:
        if addr.is_physical != phy:
            addr.is_physical = phy
            changed.append("is_physical")
        if addr.is_postal != post:
            addr.is_postal = post
            changed.append("is_postal")
        if addr.address1 != a1:
            addr.address1 = a1
            changed.append("address1")
        if addr.address2 != a2:
            addr.address2 = a2
            changed.append("address2")
        if addr.city != cty:
            addr.city = cty
            changed.append("city")
        if addr.state != st:
            addr.state = st
            changed.append("state")
        if addr.postal_code != zipc:
            addr.postal_code = zipc
            changed.append("postal_code")

    db.session.flush()

    as_of = now_iso8601_ms()
    event_bus.emit(
        domain="entity",
        operation="wizard_address_upserted",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=entity_ulid,
        refs=None,
        changed={"fields": list(changed)},
        happened_at_utc=as_of,
    )

    return WizardStepDTO(
        entity_ulid=entity_ulid,
        created=created,
        changed_fields=tuple(changed),
        next_step="entity.wizard_role_get",
    )


# -----------------
# Step 4 — Role
# -----------------


def wizard_set_single_role(
    *,
    entity_ulid: str,
    role: str,
    request_id: str,
    actor_ulid: str | None,
) -> WizardStepDTO:
    ent = require_wizard_entity(entity_ulid)
    _validate_entity_shape(ent)

    r = (role or "").strip().lower()
    if not r:
        raise ValueError("role is required")

    allowed = set(governance_v2.list_entity_role_codes())
    if r not in allowed:
        raise ValueError("invalid role")

    active = (
        db.session.execute(
            select(EntityRole).where(
                EntityRole.entity_ulid == entity_ulid,
                EntityRole.archived_at.is_(None),
            )
        )
        .scalars()
        .all()
    )

    changed: list[str] = []

    # If already active, keep going.
    if active and any(x.role == r for x in active):
        return WizardStepDTO(
            entity_ulid=entity_ulid,
            created=False,
            changed_fields=(),
            next_step="entity.wizard_next",
        )

    as_of = now_iso8601_ms()

    # Archive prior actives (MVP: only one “current” role)
    for x in active:
        x.archived_at = as_of
        changed.append(f"archived_role:{x.role}")

    db.session.add(EntityRole(entity_ulid=entity_ulid, role=r))
    changed.append(f"role:{r}")

    db.session.flush()

    event_bus.emit(
        domain="entity",
        operation="wizard_domain_role_set",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=entity_ulid,
        refs=None,
        changed={"fields": list(changed)},
        happened_at_utc=as_of,
    )

    return WizardStepDTO(
        entity_ulid=entity_ulid,
        created=True,
        changed_fields=tuple(changed),
        next_step="entity.wizard_next",
    )
