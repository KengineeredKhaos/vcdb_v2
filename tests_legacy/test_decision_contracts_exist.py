# tests/test_decision_contracts_exist.py
 
import importlib
import yaml
from pathlib import Path

CATALOG_PATHS = [
    Path("docs/decision_catalog.yaml"),               # preferred
    Path("scaffolding_docs/decision_catalog.yaml"),   # fallback
]
def _load_catalog():
    for p in CATALOG_PATHS:
        if p.exists():
            return yaml.safe_load(p.read_text())
    # inline minimal fallback consistent with the canvas doc
    return [
        {"requires": ["customers_v2.get_profile"]},
        {"requires": ["resources_v2.get_profile"]},
        {"requires": ["sponsors_v2.get_policy"]},
        {"requires": ["governance_v2.get_spending_limits", "governance_v2.get_constraints"]},
        {"requires": ["calendar_v2.blackout_ok"]},
        {"requires": ["logistics_v2.get_sku_cadence"]},
    ]

def test_decisions_reference_existing_gets():
    catalog = _load_catalog()
    for d in catalog:
        for ref in d.get("requires", []):
            mod_name, fn_name = (ref.split(":") if ":" in ref else ref.rsplit(".", 1))
            mod = importlib.import_module(f"app.extensions.contracts.{mod_name}")
            assert hasattr(mod, fn_name), f"Missing {mod_name}.{fn_name}"
            # optional: if module exposes __schema__, sanity check key presence
            if hasattr(mod, "__schema__"):
                assert fn_name in mod.__schema__, f"{mod_name}.__schema__ missing {fn_name}"
