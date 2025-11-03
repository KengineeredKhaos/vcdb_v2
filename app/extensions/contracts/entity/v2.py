# app/extensions/contracts/entity/v2.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.slices.entity import services as entity_svc


# --- DTOs -----------------------------------------------------
@dataclass(frozen=True)
class ContractEnvelope:
    request_id: str
    actor_ulid: Optional[str] = None
    dry_run: bool = False


@dataclass(frozen=True)
class LedgerDTO:
    ok: bool
    event_type: str
    target_id: str
    request_id: str


# --- Helpers --------------------------------------------------
def _ledger_stub(
    event_type: str, target_id: str, request_id: str
) -> LedgerDTO:
    return LedgerDTO(
        ok=True,
        event_type=event_type,
        target_ulid=target_id,
        request_id=request_id,
    )


# --- Public API ----------------------------------------------


def ensure_person(
    env: ContractEnvelope,
    *,
    first_name: str,
    last_name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Idempotent create/update of a person-entity; returns {"ok": True, "entity_ulid": "...", "ledger": LedgerDTO}
    """
    if env.dry_run:
        # Predict normalized values only; no DB writes, no emit
        return {
            "ok": True,
            "would_create_or_update": True,
            "normalized": {
                "email": (email or "").strip().lower() or None,
                "phone": (phone or "").strip() or None,
            },
        }
    ent_ulid = entity_svc.ensure_person(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        request_id=env.request_id,
        actor_ulid=env.actor_ulid,
    )
    # Event already emitted by service; return a ledger stub for contract shape
    return {
        "ok": True,
        "entity_ulid": ent_ulid,
        "ledger": _ledger_stub(
            "entity.person.upserted", ent_ulid, env.request_id
        ),
    }


def ensure_org(
    env: ContractEnvelope,
    *,
    legal_name: str,
    dba_name: Optional[str] = None,
    ein: Optional[str] = None,
) -> Dict[str, Any]:
    if env.dry_run:
        return {
            "ok": True,
            "would_create_or_update": True,
            "normalized": {
                "legal_name": (legal_name or "").strip(),
                "dba_name": (dba_name or "").strip() or None,
                "ein": (ein or "").replace("-", "").strip() or None,
            },
        }
    ent_ulid = entity_svc.ensure_org(
        legal_name=legal_name,
        dba_name=dba_name,
        ein=ein,
        request_id=env.request_id,
        actor_ulid=env.actor_ulid,
    )
    return {
        "ok": True,
        "entity_ulid": ent_ulid,
        "ledger": _ledger_stub(
            "entity.org.upserted", ent_ulid, env.request_id
        ),
    }


def add_entity_role(
    env: ContractEnvelope, entity_ulid: str, role: str
) -> Dict[str, Any]:
    if env.dry_run:
        return {
            "ok": True,
            "would_attach_role": role,
            "entity_ulid": entity_ulid,
        }
    changed = entity_svc.ensure_role(
        entity_ulid=entity_ulid,
        role=role,
        request_id=env.request_id,
        actor_ulid=env.actor_ulid,
    )
    return {
        "ok": True,
        "changed": changed,
        "ledger": _ledger_stub(
            "entity.role.attached", entity_ulid, env.request_id
        ),
    }


def remove_entity_role(
    env: ContractEnvelope, entity_ulid: str, role: str
) -> Dict[str, Any]:
    if env.dry_run:
        return {
            "ok": True,
            "would_remove_role": role,
            "entity_ulid": entity_ulid,
        }
    changed = entity_svc.remove_role(
        entity_ulid=entity_ulid,
        role=role,
        request_id=env.request_id,
        actor_ulid=env.actor_ulid,
    )
    return {
        "ok": True,
        "changed": changed,
        "ledger": _ledger_stub(
            "entity.role.removed", entity_ulid, env.request_id
        ),
    }
