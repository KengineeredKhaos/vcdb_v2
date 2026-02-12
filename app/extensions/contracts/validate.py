# app/extensions/contracts/validate.py

import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JSONSchemaValidationError

from app.extensions.errors import ContractError


class ContractValidationError(ContractError):
    """
    Specialization used when JSON Schema validation fails.

    We don't add new fields, just a clearer error code and a helper
    to map jsonschema's ValidationError into our canonical ContractError
    shape.
    """

    @classmethod
    def from_jsonschema(
        cls, e: JSONSchemaValidationError
    ) -> "ContractValidationError":
        path = ".".join(str(p) for p in e.path) or "<root>"
        return cls(
            code="payload_invalid",
            where="contracts.validate.validate_payload",
            message=e.message,
            http_status=400,
            data={
                "path": path,
                "schema_path": list(e.schema_path),
            },
        )


def load_schema(module_file: str, rel_path: str) -> dict:
    # module_file is __file__ of the contract package; rel_path like
    # "schemas/event.request.json"
    pkg = module_file.rsplit("/", 1)[0]  # package directory
    with open(f"{pkg}/{rel_path}", encoding="utf-8") as f:
        return json.load(f)


def validate_payload(schema: dict, payload: dict) -> None:
    """
    Validate `payload` against `schema`. Raises ContractValidationError
    (http_status=400) on failure.
    """
    try:
        Draft202012Validator(schema).validate(payload)
    except JSONSchemaValidationError as e:
        raise ContractValidationError.from_jsonschema(e) from e
