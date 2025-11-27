# app/extensions/validate.py

"""
Thin JSON + JSON Schema helpers used by the policy layer.

This module is intentionally tiny and focused:

- `load_json(path)`: load UTF-8 JSON from disk.
- `load_json_schema(path)`: load a JSON Schema document and assert that
  it is a JSON object.
- `validate_json_payload(payload, schema_path)`:
    * Load the schema from disk.
    * Use Draft202012Validator to validate the payload in-place.
    * Raise jsonschema.ValidationError on failure.

`policies.py` and `policy_semantics.py` build on these helpers for all
policy/config validation. If you introduce new schema versions or change
Draft versions, this is the right place to wire that up so behavior
remains consistent across the app.
"""

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
