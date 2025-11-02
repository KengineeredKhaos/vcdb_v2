# app/lib/schema.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from jsonschema import Draft202012Validator

from .errors import ValidationError
from .jsonutil import stable_dumps

# Optional: tiny cache if you validate the same schema often
_VALIDATOR_CACHE: Dict[int, Draft202012Validator] = {}


def validate_json(schema: Dict[str, Any], payload: Any) -> None:
    try:
        _get_validator(schema).validate(payload)
    except Exception as e:  # jsonschema.ValidationError subtype
        # Try to enrich with dotted path, if present
        path = getattr(e, "json_path", None) or getattr(e, "path", None)
        loc = f" at {'.'.join(map(str, path))}" if path else ""
        raise ValidationError(f"{e}{loc}") from e


def try_validate_json(
    schema: Dict[str, Any], payload: Any
) -> Tuple[bool, Optional[str]]:
    try:
        validate_json(schema, payload)
        return True, None
    except ValidationError as e:
        return False, str(e)


def enum_values(schema: Dict[str, Any], path: Iterable[str]) -> List[str]:
    node: Dict[str, Any] = schema
    try:
        for key in path:
            node = node["properties"][key]
    except KeyError as ke:
        raise ValidationError(
            f"Schema path not found: {'/'.join(path)}"
        ) from ke
    # handle either array-of-enum or direct enum node
    if "items" in node:
        return list(node.get("items", {}).get("enum", []) or [])
    if "enum" in node:
        return list(node.get("enum", []) or [])
    return []


def _schema_cache_key(schema: Dict[str, Any]) -> str:
    s = stable_dumps(schema)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _get_validator(schema: Dict[str, Any]) -> Draft202012Validator:
    key = _schema_cache_key(schema)
    v = _VALIDATOR_CACHE.get(key)
    if v is None:
        v = Draft202012Validator(schema)
        _VALIDATOR_CACHE[key] = v
    return v


def load_json_schema(path: str) -> dict:
    """Read a JSON Schema from disk and return it as a dict."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


__all__ = [
    "ValidationError",
    "validate_json",
    "try_validate_json",
    "enum_values",
    "load_json_schema",
]
