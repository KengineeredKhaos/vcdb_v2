# app/extensions/contracts/entity_v2.py
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.lib.chrono import utcnow_naive  # not used here but stays consistent
from app.slices.entity.models import (
    ContactPoint,
    Entity,
    EntityOrg,
    EntityPerson,
)  # adjust names


@dataclass
class EntityCardDTO:
    ulid: str
    type: str  # "person" | "org"
    display_name: str
    contacts: list  # [{"kind":"email","value":"..."},{"kind":"phone","value":"..."}]
    address_short: str | None


def _first_email_phone(sess: Session, entity_ulid: str) -> list[dict]:
    q = (
        sess.query(ContactPoint)
        .filter(ContactPoint.entity_ulid == entity_ulid)
        .order_by(ContactPoint.created_at_utc.asc())
    )
    emails = []
    phones = []
    for c in q:
        if c.kind == "email" and len(emails) == 0:
            emails.append({"kind": "email", "value": c.value})
        if c.kind == "phone" and len(phones) == 0:
            phones.append({"kind": "phone", "value": c.value})
        if emails and phones:
            break
    return emails + phones


def get_entity_card(sess: Session, entity_ulid: str) -> EntityCardDTO:
    ent = sess.query(Entity).get(entity_ulid)
    if not ent:
        raise LookupError("entity not found")

    person = sess.query(EntityPerson).get(entity_ulid)
    org = None if person else sess.query(EntityOrg).get(entity_ulid)

    if person:
        display = f"{person.last_name}, {person.first_name}".strip().strip(
            ","
        )
        etype = "person"
    elif org:
        display = org.legal_name
        etype = "org"
    else:
        display = entity_ulid
        etype = "org"

    contacts = _first_email_phone(sess, entity_ulid)
    # (Optional) short address can be stitched from your address table if desired
    return EntityCardDTO(
        ulid=entity_ulid,
        type=etype,
        display_name=display,
        contacts=contacts,
        address_short=None,
    )
