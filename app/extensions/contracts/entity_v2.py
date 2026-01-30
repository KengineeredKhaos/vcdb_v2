# app/extensions/contracts/entity_v2.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Optional

from sqlalchemy.orm import Session

from app.extensions.errors import ContractError
from app.slices.entity.models import (
    Entity,
    EntityContact,
    EntityOrg,
    EntityPerson,
)

# -----------------
# DTO's
# -----------------


@dataclass(frozen=True)
class EntityCoreDTO:
    ulid: str
    kind: str
    archived_at: str | None


@dataclass(frozen=True)
class EntityCardDTO:
    ulid: str
    type: str
    display_name: str
    contacts: list[dict[str, str]]
    address_short: str | None


@dataclass(frozen=True)
class MatchDTO:
    entity_ulid: str
    score: int
    reasons: list[str]


@dataclass(frozen=True)
class CreateCustomerPersonResultDTO:
    entity_ulid: str
    created: bool


@dataclass(frozen=True)
class EnsurePersonResultDTO:
    entity_ulid: str
    created: bool | None


# -----------------
# Contract Errors
# -----------------


def _as_contract_error(where: str, exc: Exception) -> ContractError:
    if isinstance(exc, ContractError):
        return exc

    # lazy import to reduce circular-import risk
    from app.slices.entity import services as entity_svc  # noqa: WPS433

    if isinstance(
        exc, getattr(entity_svc, "DuplicateCandidateError", Exception)
    ):
        return ContractError(
            code="duplicate_candidate",
            where=where,
            message="possible duplicate customer",
            http_status=409,
            data={
                "hint": "run intake lookup; if you must proceed, set allow_duplicate=true",
            },
        )

    msg = str(exc) or exc.__class__.__name__

    if isinstance(exc, ValueError):
        return ContractError("bad_argument", where, msg, 400)
    if isinstance(exc, PermissionError):
        return ContractError("permission_denied", where, msg, 403)
    if isinstance(exc, LookupError):
        return ContractError("not_found", where, msg, 404)

    return ContractError(
        code="internal_error",
        where=where,
        message="unexpected error in contract; see logs",
        http_status=500,
        data={"exc_type": exc.__class__.__name__},
    )


# -----------------
# Functions
# -----------------


def get_entity_core(sess: Session, entity_ulid: str) -> EntityCoreDTO:
    where = "entity_v2.get_entity_core"
    try:
        ent = sess.get(Entity, entity_ulid)
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


def _first_email_phone(
    sess: Session, entity_ulid: str
) -> list[dict[str, str]]:
    q = (
        sess.query(EntityContact)
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


def get_entity_card(sess: Session, entity_ulid: str) -> EntityCardDTO:
    where = "entity_v2.get_entity_card"
    try:
        ent = sess.get(Entity, entity_ulid)
        if not ent:
            raise ContractError(
                "not_found",
                where,
                "entity not found",
                404,
                data={"entity_ulid": entity_ulid},
            )

        person = sess.get(EntityPerson, entity_ulid)
        org = None if person else sess.get(EntityOrg, entity_ulid)

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
            contacts=_first_email_phone(sess, entity_ulid),
            address_short=None,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def search_customer_candidates(
    sess: Session,
    *,
    last_name: str,
    dob: str,
    last_4: str,
) -> list[MatchDTO]:
    where = "entity_v2.search_customer_candidates"
    try:
        from app.slices.entity import services as entity_svc  # noqa: WPS433

        return entity_svc.search_customer_candidates(
            last_name=last_name,
            dob=dob,
            last_4=last_4,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def create_customer_person(
    sess: Session,
    *,
    first_name: str,
    last_name: str,
    preferred_name: str | None,
    dob: str,
    last_4: str,
    branch: str | None,
    era: str | None,
    request_id: str,
    actor_ulid: str | None,
    allow_duplicate: bool = False,
) -> CreateCustomerPersonResultDTO:
    where = "entity_v2.create_customer_person"
    try:
        from app.slices.entity import services as entity_svc  # noqa: WPS433

        return entity_svc.create_customer_person(
            first_name=first_name,
            last_name=last_name,
            preferred_name=preferred_name,
            dob=dob,
            last_4=last_4,
            branch=branch,
            era=era,
            request_id=request_id,
            actor_ulid=actor_ulid,
            allow_duplicate=allow_duplicate,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc


def ensure_person(
    sess: Session,
    *,
    first_name: str,
    last_name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    request_id: str,
    actor_ulid: str | None,
) -> EnsurePersonResultDTO:
    where = "entity_v2.ensure_person"
    try:
        from app.slices.entity import services as entity_svc  # noqa: WPS433

        fn = getattr(entity_svc, "ensure_person_by_contact", None) or getattr(
            entity_svc, "ensure_person", None
        )
        if not fn:
            raise AttributeError(
                "entity provider missing ensure_person[_by_contact]"
            )

        ulid = fn(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            request_id=request_id,
            actor_ulid=actor_ulid,
        )
        return EnsurePersonResultDTO(entity_ulid=ulid, created=None)
    except Exception as exc:
        raise _as_contract_error(where, exc) from exc
