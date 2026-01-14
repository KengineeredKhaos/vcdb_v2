# app/services/entity_validate.py
from __future__ import annotations

from sqlalchemy.orm import Session

from app.extensions.contracts import entity_v2
from app.extensions.errors import ContractError


def require_person_entity_ulid(
    sess: Session,
    entity_ulid: str,
    *,
    where: str,
    allow_archived: bool = False,
) -> None:
    """
    Verify that entity_ulid exists and refers to a non-archived Entity(kind='person').

    This is a shared, slice-agnostic guard used by POC wrappers in Resources/Sponsors.
    """
    core = entity_v2.get_entity_core(sess, entity_ulid)

    if core.kind != "person":
        raise ContractError(
            code="bad_request",
            where=where,
            message=f"expected person entity (got kind='{core.kind}')",
            http_status=400,
            data={"entity_ulid": entity_ulid, "kind": core.kind},
        )

    if (not allow_archived) and core.archived_at:
        raise ContractError(
            code="conflict",
            where=where,
            message="entity is archived",
            http_status=409,
            data={
                "entity_ulid": entity_ulid,
                "archived_at": core.archived_at,
            },
        )
