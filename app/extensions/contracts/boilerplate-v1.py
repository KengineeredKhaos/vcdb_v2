# app/extensions/contracts/<slice>/v1.py
from typing import Any, Dict, Optional, Tuple

# TODO: point this import at the actual slice services implementation:
# e.g., from app.slices.governance import services as _svc
from app.slices.<slice> import services as _svc  # type: ignore

# Reuse shared errors
from app.extensions.errors import DataNotFoundError, ValidationError, ContractError

# TODO: swap these for your real helpers once exposed via app.lib
# e.g., from app.lib import new_ulid, utc_now_iso
def _new_request_id() -> str:
    # return new_ulid()
    import uuid
    return uuid.uuid4().hex

def _utc_now_iso() -> str:
    # return utc_now_iso()
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ------------------------
# Response envelope helpers
# ------------------------

def _ok(data: Any, request_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "ok": True,
        "data": data,
        "error": None,
        "request_id": request_id or _new_request_id(),
        "at": _utc_now_iso(),
        "version": "v1",
    }

def _fail(kind: str, message: str, *, details: Any = None,
          request_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": {"kind": kind, "message": message, "details": details},
        "request_id": request_id or _new_request_id(),
        "at": _utc_now_iso(),
        "version": "v1",
    }


# ------------------------
# Facade surface (examples)
# Keep these **thin** and stable. Do not leak slice internals.
# ------------------------

def get_one(key: str) -> Dict[str, Any]:
    """
    Read a single item by key/id (policy, record, etc.).
    Returns envelope with DTO in `data`.
    """
    rid = _new_request_id()
    try:
        dto = _svc.get_one(key)  # slice function returns a DTO/dict
        return _ok(dto, request_id=rid)
    except KeyError as e:
        return _fail(DataNotFoundError.kind, f"Not found: {key}", details=str(e), request_id=rid)
    except _svc.NotFoundError as e:  # if your slice defines this
        return _fail(DataNotFoundError.kind, str(e), request_id=rid)
    except Exception as e:  # last-resort guard
        return _fail(ContractError.kind, "Unhandled error", details=str(e), request_id=rid)


def list_items(**filters: Any) -> Dict[str, Any]:
    """
    List or search; `filters` are pass-through and slice-owned.
    """
    rid = _new_request_id()
    try:
        items = _svc.list_items(**filters)  # returns list[DTO]
        return _ok(items, request_id=rid)
    except Exception as e:
        return _fail(ContractError.kind, "Unhandled error", details=str(e), request_id=rid)


def create(payload: Dict[str, Any], *, dry_run: bool = False) -> Dict[str, Any]:
    """
    Create with validation. Slice owns schema + rules.
    If dry_run=True: validate & preview DTO changes but do not persist.
    Return created DTO (or preview DTO) in `data`.
    """
    rid = _new_request_id()
    try:
        dto = _svc.create(payload, dry_run=dry_run)
        return _ok(dto, request_id=rid)
    except (_svc.ValidationError, _svc.SchemaError) as e:
        return _fail(ValidationError.kind, str(e), request_id=rid)
    except Exception as e:
        return _fail(ContractError.kind, "Unhandled error", details=str(e), request_id=rid)


def update(key: str, payload: Dict[str, Any], *, dry_run: bool = False) -> Dict[str, Any]:
    """
    Update with validation. Return updated DTO (or preview DTO) in `data`.
    """
    rid = _new_request_id()
    try:
        dto = _svc.update(key, payload, dry_run=dry_run)
        return _ok(dto, request_id=rid)
    except KeyError as e:
        return _fail(DataNotFoundError.kind, f"Not found: {key}", details=str(e), request_id=rid)
    except (_svc.ValidationError, _svc.SchemaError) as e:
        return _fail(ValidationError.kind, str(e), request_id=rid)
    except Exception as e:
        return _fail(ContractError.kind, "Unhandled error", details=str(e), request_id=rid)


def delete(key: str, *, dry_run: bool = False) -> Dict[str, Any]:
    """
    Delete or preview delete. Return a tiny DTO summary (e.g., {'deleted': key}).
    """
    rid = _new_request_id()
    try:
        result = _svc.delete(key, dry_run=dry_run)
        return _ok(result, request_id=rid)
    except KeyError as e:
        return _fail(DataNotFoundError.kind, f"Not found: {key}", details=str(e), request_id=rid)
    except Exception as e:
        return _fail(ContractError.kind, "Unhandled error", details=str(e), request_id=rid)
