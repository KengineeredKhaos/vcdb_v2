# app/extensions/validate.py
from __future__ import annotations

from pathlib import Path

from jsonschema import Draft202012Validator

from app.lib.jsonutil import read_json_file


def validate_json_payload(payload: dict, schema_path: Path) -> None:
    schema = read_json_file(schema_path)
    Draft202012Validator(schema).validate(payload)


def validate_json_file(file_path: Path, schema_path: Path) -> dict:
    data = read_json_file(file_path, default=None)
    if data is None:
        raise FileNotFoundError(f"Missing or invalid JSON: {file_path}")
    validate_json_payload(data, schema_path)
    return data
