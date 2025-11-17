# app/extensions/contracts/entity/v1.py
from typing import Dict, List

from app.extensions.contracts.types import ContractEnvelope


def list_entity_roles(env: ContractEnvelope, entity_ulid: str) -> List[str]:
    ...


def add_entity_role(
    env: ContractEnvelope, entity_ulid: str, role: str
) -> Dict:
    """If env.dry_run, return would-change info; else persist and return {ok: True, ledger: LedgerDTO}."""
    ...


def remove_entity_role(
    env: ContractEnvelope, entity_ulid: str, role: str
) -> Dict:
    ...
