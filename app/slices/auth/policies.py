# app/slices/auth/policies.py
from pathlib import Path

from app.lib.jsonutil import read_json_file

POLICY_RBAC = Path("app/slices/auth/data/policy_rbac.json")


def load_rbac_policy() -> dict:
    data = read_json_file(POLICY_RBAC, default=None)
    if not data:
        raise FileNotFoundError(f"Missing RBAC policy: {POLICY_RBAC}")
    return data
