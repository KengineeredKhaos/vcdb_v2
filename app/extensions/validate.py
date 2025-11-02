# app/extensions/validate.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def load_json(path: str | Path) -> Any:
    """Load a JSON file (UTF-8) and return the parsed object."""
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def load_json_schema(path: str | Path) -> dict:
    """Load a JSON Schema (just JSON under the hood)."""
    obj = load_json(path)
    if not isinstance(obj, dict):
        raise TypeError(f"Schema at {path} must be a JSON object")
    return obj


def validate_json_payload(payload: Any, schema_path: str | Path) -> None:
    """Validate a JSON payload against a JSON Schema file path."""
    schema = load_json_schema(schema_path)
    Draft202012Validator(schema).validate(payload)
