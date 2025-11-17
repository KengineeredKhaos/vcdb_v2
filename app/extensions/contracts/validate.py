# app/extensions/contracts/validate.py

import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JSONSchemaValidationError

from .errors import ContractValidationError


def load_schema(module_file: str, rel_path: str) -> dict:
    # module_file is __file__ of the contract package; rel_path like "schemas/event.request.json"
    pkg = module_file.rsplit("/", 1)[0]  # package directory
    # Simple loader; if you prefer importlib.resources for packages, use that instead.
    with open(f"{pkg}/{rel_path}", "r", encoding="utf-8") as f:
        return json.load(f)


def validate_payload(schema: dict, payload: dict) -> None:
    try:
        Draft202012Validator(schema).validate(payload)
    except JSONSchemaValidationError as e:
        raise ContractValidationError.from_jsonschema(e)
