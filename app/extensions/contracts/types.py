# extensions/contracts/types.py
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, NotRequired, Optional, TypedDict


class ContractRequest(TypedDict):
    contract: str  # e.g., "governance.roles.v1"
    request_id: str  # ULID
    ts: str  # ISO8601 UTC "…Z"
    actor_ulid: NotRequired[str]  # ULID of caller (if any)
    dry_run: NotRequired[bool]
    data: dict  # contract-specific payload


class ContractError(TypedDict, total=False):
    code: str  # "INVALID_ROLE" | "UNKNOWN_ENTITY" | ...
    message: str
    field: NotRequired[str]
    details: NotRequired[dict]


class ContractResponse(TypedDict, total=False):
    contract: str
    request_id: str
    ts: str
    ok: bool
    data: NotRequired[dict]  # contract-specific DTO
    warnings: NotRequired[list[str]]
    errors: NotRequired[list[ContractError]]
    ledger: NotRequired[dict]  # commit-only hints, e.g. {emitted,event_id}


@dataclass(frozen=True)
class ContractEnvelope:
    request_id: str  # ULID
    actor_ulid: Optional[str]  # entity ULID or None for system
    dry_run: bool = False


@dataclass(frozen=True)
class LedgerRef:
    entity_id: Optional[str] = None
    extra: Dict[str, Any] = None


@dataclass(frozen=True)
class LedgerDTO:
    id: str
    type: str  # e.g., "auth.user_role.assigned"
    slice: str  # "auth" | "entity" | "governance" | ...
    operation: str  # "assigned" | "removed" | "updated"
    happened_at: datetime
    actor_ulid: Optional[str]
    target_id: Optional[str]
    changed_fields: Dict[str, Any]
    refs: Dict[str, Any]
    request_id: str
    correlation_id: Optional[str] = None
    prev_event_id: Optional[str] = None
    prev_hash: Optional[str] = None
    event_hash: Optional[str] = None
