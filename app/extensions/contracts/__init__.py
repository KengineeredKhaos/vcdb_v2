# app/extensions/contracts/__init__.py

# Package marker for contracts. Re-exports live in subpackages.
"""
Canonical naming:

extensions.contracts.auth_v2

extensions.contracts.customers_v2.py

extensions.contracts.entity_v2

extensions.contracts.governance_v2

extensions.contracts.ledger_v2

extensions.contracts.resources_v2

extensions.contracts.sponsors_v2

extensions.contracts.logistics_v2

etc.

Public surface: only these modules + event_bus.py are “public” to slices and CLI.

Error model: all contracts raise ContractError from extensions.contracts.errors, nothing else.

DTO model: contracts return plain dicts/DTOs;
           they don’t expose SQLAlchemy models or slice internals.

Versioning rule: never mutate *_v1 once published; changes go into *_v2.
"""

pass
