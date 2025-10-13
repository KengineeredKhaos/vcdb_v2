# app/extensions/contracts/governance/v1/__init__.py
from typing import Any, Dict

from app.extensions.contracts.errors import (
    ContractDataNotFound,
    ContractError,
    ContractValidationError,
)
from app.extensions.contracts.validate import load_schema, validate_payload

# your helpers


_provider = None  # late-bound services module


def bind_provider(provider_module) -> None:
    """Bind the provider slice (e.g., app.slices.governance.services)."""
    global _provider
    _provider = provider_module


def require_provider():
    if _provider is None:
        raise RuntimeError("governance contract not bound to a provider")
    return _provider


# Facade API
def get_policy(name: str) -> dict:
    svc = require_provider()
    data = svc.policy_get(name)  # provider function
    if data is None:
        raise ContractDataNotFound(f"Policy '{name}' not found")
    return data


def set_policy(
    name: str, payload: dict, actor_ulid: str | None = None
) -> dict:
    svc = require_provider()
    # validate against schema (if you keep schemas here)
    # schema = load_schema("governance/policy_payload.json")
    # validate_payload(schema, payload)
    return svc.policy_set(name, payload, actor_ulid=actor_ulid)
