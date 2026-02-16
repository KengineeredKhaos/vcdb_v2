# app/slices/entity/services_wizard.py

"""
Wizard designed for entity creation/editing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.lib.geo import normalize_state
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

from .mapper import (
    WizardEntityCreatedDTO,
    WizardStepDTO,
)
from .models import (
    Entity,
    EntityAddress,
    EntityContact,
    EntityOrg,
    EntityPerson,
    EntityRole,
    # EntityAddress,  # <- adjust if your model name differs
)

# -----------------
# Constants / Tools
# -----------------

_ZIP5_RE = re.compile(r"^\d{5}$")
_ZIP9_RE = re.compile(r"^\d{5}-\d{4}$")


# -----------------
# DTO's & TypedDict
# -----------------


@dataclass(frozen=True, slots=True)
class WizardPersonCommitResult:
    entity_ulid: str
    created: bool
    changed_fields: tuple[str, ...]
    as_of_iso: str


# -----------------
# Local Helper
# Functions
# -----------------


def _clean_req(label: str, v: str) -> str:
    s = (v or "").strip()
    if not s:
        raise ValueError(f"{label} is required")
    return s


def _clean_opt(v: str | None) -> str | None:
    s = (v or "").strip()
    return s or None


def _ensure_request_id(request_id: str | None) -> str:
    rid = (request_id or "").strip()
    if not rid:
        raise ValueError("request_id must be non-empty")
    return rid


def _ensure_role(role: str | None) -> str | None:
    if role is None:
        return None
    r = (role or "").strip().lower()
    if not r:
        return None
    return r


def _ensure_person_entity(
    *,
    entity_ulid: str | None,
) -> tuple[Entity, bool]:
    """
    Ensure Entity(kind='person') exists.
    Returns (entity, created).
    """
    if entity_ulid:
        ent = db.session.get(Entity, entity_ulid)
        if ent is None:
            raise LookupError("entity not found")
        if ent.kind != "person":
            raise ValueError("entity kind mismatch (expected person)")
        return ent, False

    ent = Entity(kind="person")
    db.session.add(ent)
    db.session.flush()
    return ent, True


def _ensure_org_entity(
    *,
    entity_ulid: str | None,
) -> tuple[Entity, bool]:
    """
    Ensure Entity(kind='org') exists.
    Returns (entity, created).
    """
    if entity_ulid:
        ent = db.session.get(Entity, entity_ulid)
        if ent is None:
            raise LookupError("entity not found")
        if ent.kind != "org":
            raise ValueError("entity kind mismatch (expected person)")
        return ent, False

    ent = Entity(kind="org")
    db.session.add(ent)
    db.session.flush()
    return ent, True


def _display_name_person(
    *, first_name: str, last_name: str, preferred_name: str | None
) -> str:
    given = (preferred_name or first_name).strip()
    fam = last_name.strip()
    return f"{given} {fam}".strip()


def _display_name_org(*, legal_name: str, dba_name: str | None) -> str:
    base = (dba_name or legal_name).strip()
    return base


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


# -----------------
# Wizard Step Check
# -----------------


def wizard_next_step(*, entity_ulid: str) -> str:
    ent = db.session.get(Entity, entity_ulid)
    if ent is None:
        raise LookupError("entity not found")

    _validate_entity_shape(ent)  # hard guard

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
        return "entity.wizard_role"

    return "entity.wizard_next"


# TODO: sort out _validate_entity_shape(ent)  # hard guard

# TODO: add entity.wizard_resume(entity_ulid) that just redirects to
# wizard_next_step()

# TODO: at the top of every wizard GET route, do:
# expected = wizard_next_step(entity_ulid)
# if you’re not on expected, redirect to expected

# That single trick solves “interrupted workflows” without adding new columns.


# -----------------
# Entity Creation
# Wizard Functions
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
    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    pn = (preferred_name or "").strip() or None

    if not fn or not ln:
        raise ValueError("first_name and last_name are required")

    dob_raw = (dob or "").strip() or None
    dob_norm = normalize_dob(dob_raw) if dob_raw else None
    if dob_norm and not validate_dob(dob_norm):
        raise ValueError("invalid dob")

    l4_raw = (last_4 or "").strip() or None
    if l4_raw and ((not l4_raw.isdigit()) or len(l4_raw) != 4):
        raise ValueError("last_4 must be 4 digits")
    l4_norm = l4_raw or None

    ent = Entity(kind="person")
    ent.person = EntityPerson(
        first_name=fn,
        last_name=ln,
        preferred_name=pn,
        dob=dob_norm,
        last_4=l4_norm,
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
    ln = (legal_name or "").strip()
    dba = (dba_name or "").strip() or None
    ein_raw = (ein or "").strip() or None
    ein_norm = normalize_ein(ein_raw) if ein_raw else None
    if ein_norm and not validate_ein(ein_norm):
        raise ValueError("invalid ein")

    if not ln:
        raise ValueError("legal_name is required")

    ent = Entity(kind="org")
    ent.org = EntityOrg(
        legal_name=ln,
        dba_name=dba,
        ein=ein_norm,
    )
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
        next_step="entity.wizard_upsert_primary_contact",
    )


def wizard_upsert_primary_contact(
    *,
    entity_ulid: str,
    email: str | None,
    phone: str | None,
    next_step: str = "entity.wizard_address",
) -> WizardStepDTO:
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

    return WizardStepDTO(
        entity_ulid=entity_ulid,
        created=created,
        changed_fields=tuple(changed),
        next_step=next_step,
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
    next_step: str = "entity.wizard_role",
) -> WizardStepDTO:
    phy = True if is_physical is None else bool(is_physical)
    post = False if is_postal is None else bool(is_postal)

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

    return WizardStepDTO(
        entity_ulid=entity_ulid,
        created=created,
        changed_fields=tuple(changed),
        next_step=next_step,
    )


def wizard_set_single_role(
    *,
    entity_ulid: str,
    role: str,
    next_step: str = "entity.wizard_next",
) -> WizardStepDTO:
    r = (role or "").strip().lower()
    if not r:
        raise ValueError("role is required")

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
    created = False

    if active and any(x.role == r for x in active):
        return WizardStepDTO(
            entity_ulid=entity_ulid,
            created=False,
            changed_fields=(),
            next_step=next_step,
        )

    # archive prior actives (MVP: only one “current” role)
    for x in active:
        x.archived_at = now_iso8601_ms()
        changed.append(f"archived_role:{x.role}")

    db.session.add(EntityRole(entity_ulid=entity_ulid, role=r))
    created = True
    changed.append(f"role:{r}")

    db.session.flush()

    return WizardStepDTO(
        entity_ulid=entity_ulid,
        created=created,
        changed_fields=tuple(changed),
        next_step=next_step,
    )
