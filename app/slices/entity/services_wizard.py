# app/slices/entity/services_wizard.py

"""
Wizard designed for entity creation/editing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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

from .models import (
    Entity,
    EntityContact,
    EntityPerson,
    EntityRole,
    # EntityAddress,  # <- adjust if your model name differs
)


@dataclass(frozen=True, slots=True)
class WizardPersonCommitResult:
    entity_ulid: str
    created: bool
    changed_fields: tuple[str, ...]
    as_of_iso: str


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


def _cmd_wizard_person_upsert_core(
    *,
    ent: Entity,
    first_name: str,
    last_name: str,
    preferred_name: str | None,
) -> tuple[EntityPerson, tuple[str, ...]]:
    changed: list[str] = []

    fn = (first_name or "").strip()
    ln = (last_name or "").strip()
    pn = (preferred_name or "").strip() or None

    if not fn or not ln:
        raise ValueError("first_name and last_name are required")

    p = ent.person
    if p is None:
        p = EntityPerson(
            entity_ulid=ent.ulid,
            first_name=fn,
            last_name=ln,
            preferred_name=pn,
        )
        db.session.add(p)
        changed.extend(["first_name", "last_name"])
        if pn is not None:
            changed.append("preferred_name")
        return p, tuple(changed)

    if p.first_name != fn:
        p.first_name = fn
        changed.append("first_name")
    if p.last_name != ln:
        p.last_name = ln
        changed.append("last_name")
    if preferred_name is not None and p.preferred_name != pn:
        p.preferred_name = pn
        changed.append("preferred_name")

    return p, tuple(changed)


def _cmd_wizard_person_upsert_customer_facts(
    *,
    p: EntityPerson,
    dob: str | None,
    last_4: str | None,
    branch: str | None,
    era: str | None,
) -> tuple[str, ...]:
    """
    Entity-owned customer-ish facts (PII); keep rules minimal.
    """
    changed: list[str] = []

    if dob is not None:
        dob_norm = normalize_dob(dob)
        if dob_norm and not validate_dob(dob_norm):
            raise ValueError("invalid dob")
        if getattr(p, "dob", None) != dob_norm:
            setattr(p, "dob", dob_norm)
            changed.append("dob")

    if last_4 is not None:
        l4 = (last_4 or "").strip()
        if l4 and (not l4.isdigit() or len(l4) != 4):
            raise ValueError("last_4 must be 4 digits")
        if getattr(p, "last_4", None) != (l4 or None):
            setattr(p, "last_4", l4 or None)
            changed.append("last_4")

    if branch is not None:
        b = (branch or "").strip() or None
        if getattr(p, "branch", None) != b:
            setattr(p, "branch", b)
            changed.append("branch")

    if era is not None:
        e = (era or "").strip() or None
        if getattr(p, "era", None) != e:
            setattr(p, "era", e)
            changed.append("era")

    return tuple(changed)


def _cmd_wizard_upsert_primary_contact(
    *,
    ent: Entity,
    email: Any,
    phone: Any,
    is_primary: bool | None,
) -> tuple[str, ...]:
    """
    Semantics:
    - If caller omits contact entirely: wizard should not call this.
    - If caller provides contact, keys may be missing or null:
      - missing key => no change
      - explicit null => clear the field
    - Single canonical primary contact row only.
    """
    if is_primary is not None and is_primary is False:
        raise ValueError("wizard supports only primary contact (is_primary)")

    changed: list[str] = []

    email_set = email is not ...  # sentinel convention not used in JSON
    phone_set = phone is not ...

    email_norm: str | None = None
    phone_norm: str | None = None

    if email_set:
        if email is None:
            email_norm = None
        else:
            email_norm = normalize_email(str(email))
            if email_norm and not validate_email(email_norm):
                raise ValueError("invalid email")

    if phone_set:
        if phone is None:
            phone_norm = None
        else:
            phone_norm = normalize_phone(str(phone))
            if phone_norm and not validate_phone(phone_norm):
                raise ValueError("invalid phone")

    c = None
    if ent.contacts:
        c = next((x for x in ent.contacts if x.is_primary), None)

    if c is None:
        c = EntityContact(
            entity_ulid=ent.ulid,
            is_primary=True,
            email=email_norm if email_set else None,
            phone=phone_norm if phone_set else None,
        )
        db.session.add(c)
        if email_set:
            changed.append("email")
        if phone_set:
            changed.append("phone")
        return tuple(changed)

    if email_set and c.email != email_norm:
        c.email = email_norm
        changed.append("email")
    if phone_set and c.phone != phone_norm:
        c.phone = phone_norm
        changed.append("phone")

    return tuple(changed)


def _cmd_wizard_ensure_role(
    *,
    entity_ulid: str,
    role: str | None,
) -> tuple[str, ...]:
    if not role:
        return ()

    exists = (
        db.session.query(EntityRole)
        .filter(
            EntityRole.entity_ulid == entity_ulid,
            EntityRole.role == role,
        )
        .one_or_none()
    )
    if exists:
        return ()

    db.session.add(EntityRole(entity_ulid=entity_ulid, role=role))
    return ("role:" + role,)


def _cmd_wizard_upsert_address(
    *,
    entity_ulid: str,
    payload: dict[str, Any] | None,
) -> tuple[str, ...]:
    """
    Placeholder: implement once your EntityAddress model is confirmed.
    Keep this function name and signature stable for the wizard.
    """
    if not payload:
        return ()

    is_physical = bool(payload.get("is_physical", True))
    is_postal = bool(payload.get("is_postal", False))
    address1 = (payload.get("address") or "").strip()
    address2 = payload.get("address2") or None
    address2 = (
        (str(address2).strip() or None) if address2 is not None else None
    )
    city = (payload.get("city") or "").strip()
    state = (payload.get("state") or "").strip().upper()
    postal_code = (payload.get("postal_code") or "").strip()

    if state and not is_valid_state_code(state):
        raise ValueError("invalid state code")

    # TODO: upsert your EntityAddress row here using entity_ulid as FK.
    # Return changed field names as needed.

    _ = (is_physical, is_postal, address1, address2, city, state, postal_code)
    return ("address",)


def cmd_wizard_person_commit(
    *,
    payload: dict[str, Any],
    request_id: str,
    actor_ulid: str | None,
) -> WizardPersonCommitResult:
    """
    Entity-slice wizard commit for a person.

    Writes Entity + EntityPerson + primary contact + (optional) role + address.
    Flush-only. Route must commit/rollback.
    """
    _ensure_request_id(request_id)

    entity_ulid = (payload.get("entity_ulid") or "").strip() or None
    role = _ensure_role(payload.get("role"))

    person = payload.get("person") or {}
    contact = payload.get("contact")
    address = payload.get("address")

    ent, created = _ensure_person_entity(entity_ulid=entity_ulid)

    changed: list[str] = []

    p, core_changed = _cmd_wizard_person_upsert_core(
        ent=ent,
        first_name=person.get("first_name"),
        last_name=person.get("last_name"),
        preferred_name=person.get("preferred_name"),
    )
    changed.extend(core_changed)

    facts_changed = _cmd_wizard_person_upsert_customer_facts(
        p=p,
        dob=person.get("dob"),
        last_4=person.get("last_4"),
        branch=person.get("branch"),
        era=person.get("era"),
    )
    changed.extend(facts_changed)

    if contact is not None:
        # interpret missing keys as "no change"
        email = contact.get("email", ...)
        phone = contact.get("phone", ...)
        is_primary = contact.get("is_primary", True)
        changed.extend(
            _cmd_wizard_upsert_primary_contact(
                ent=ent,
                email=email,
                phone=phone,
                is_primary=bool(is_primary),
            )
        )

    changed.extend(_cmd_wizard_ensure_role(entity_ulid=ent.ulid, role=role))

    changed.extend(
        _cmd_wizard_upsert_address(
            entity_ulid=ent.ulid,
            payload=address if isinstance(address, dict) else None,
        )
    )

    db.session.flush()

    event_bus.emit(
        domain="entity",
        operation="wizard_person_committed",
        request_id=request_id,
        actor_ulid=actor_ulid,
        target_ulid=ent.ulid,
        refs=None,
        changed={"fields": sorted(set(changed))},
        happened_at_utc=now_iso8601_ms(),
    )

    return WizardPersonCommitResult(
        entity_ulid=ent.ulid,
        created=bool(created),
        changed_fields=tuple(sorted(set(changed))),
        as_of_iso=now_iso8601_ms(),
    )
