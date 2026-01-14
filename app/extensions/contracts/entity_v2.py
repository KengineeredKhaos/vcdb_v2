# app/extensions/contracts/entity_v2.py
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.extensions.errors import ContractError

# not used here but stays consistent
from app.slices.entity.models import (
    Entity,
    EntityContact,
    EntityOrg,
    EntityPerson,
)


@dataclass(frozen=True)
class EntityCoreDTO:
    ulid: str
    kind: str  # "person" | "org" | ...
    archived_at: str | None


def get_entity_core(sess: Session, entity_ulid: str) -> EntityCoreDTO:
    where = "entity_v2.get_entity_core"
    try:
        ent = sess.query(Entity).get(entity_ulid)
        if not ent:
            raise ContractError(
                code="not_found",
                where=where,
                message="entity not found",
                http_status=404,
                data={"entity_ulid": entity_ulid},
            )
        return EntityCoreDTO(
            ulid=ent.ulid,
            kind=(ent.kind or "").strip().lower(),
            archived_at=ent.archived_at,
        )
    except Exception as exc:
        # IMPORTANT: use "from exc" (Ruff B904)
        raise _as_contract_error(where, exc) from exc


@dataclass
class EntityCardDTO:
    ulid: str
    type: str  # "person" | "org"
    display_name: str
    contacts: list  # [{"kind":"email","value":"..."},{"kind":"phone","value":"..."}]
    address_short: str | None


def _first_email_phone(sess: Session, entity_ulid: str) -> list[dict]:
    q = (
        sess.query(EntityContact)
        .filter(EntityContact.entity_ulid == entity_ulid)
        .order_by(EntityContact.created_at_utc.asc())
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
    where = "entity_v2.get_entity_card"
    try:
        ent = sess.query(Entity).get(entity_ulid)
        if not ent:
            raise ContractError(
                code="not_found",
                where="entity_v2.get_entity_card",
                message="entity not found",
                http_status=404,
                data={"entity_ulid": entity_ulid},
            )

        person = sess.query(EntityPerson).get(entity_ulid)
        org = None if person else sess.query(EntityOrg).get(entity_ulid)

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

        contacts = _first_email_phone(sess, entity_ulid)
        # (Optional) short address can be stitched from your address table if desired
        return EntityCardDTO(
            ulid=entity_ulid,
            type=etype,
            display_name=display,
            contacts=contacts,
            address_short=None,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    # If we’re already looking at a ContractError, just bubble it up unchanged
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

    # Fallback: unexpected system/runtime error
    return ContractError(
        code="internal_error",
        where=where,
        message="unexpected error in contract; see logs",
        http_status=500,
        data={"exc_type": exc.__class__.__name__},
    )
