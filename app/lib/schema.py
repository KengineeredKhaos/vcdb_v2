# app/lib/schema.py
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from jsonschema import Draft202012Validator

from .errors import ValidationError

# Optional: tiny cache if you validate the same schema often
_VALIDATOR_CACHE: Dict[int, Draft202012Validator] = {}


def _get_validator(schema: Dict[str, Any]) -> Draft202012Validator:
    key = id(schema)
    v = _VALIDATOR_CACHE.get(key)
    if v is None:
        v = Draft202012Validator(schema)
        _VALIDATOR_CACHE[key] = v
    return v


def validate_json(schema: Dict[str, Any], payload: Any) -> None:
    try:
        _get_validator(schema).validate(payload)
    except Exception as e:  # jsonschema.ValidationError subtype
        raise ValidationError(str(e)) from e


def try_validate_json(
    schema: Dict[str, Any], payload: Any
) -> Tuple[bool, Optional[str]]:
    try:
        validate_json(schema, payload)
        return True, None
    except ValidationError as e:
        return False, str(e)


def enum_values(schema: Dict[str, Any], path: Iterable[str]) -> List[str]:
    node = schema
    for key in path:
        node = node["properties"][key]
    items = node.get("items", {})
    return items.get("enum", [])
