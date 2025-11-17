# tests/test_foundation_decision_catalog.py
import importlib
from pathlib import Path

import pytest
import yaml

CAT_PATH = Path("docs/decision_catalog.yaml")

@pytest.mark.readonly
def test_catalog_file_present():
    assert CAT_PATH.exists(), "docs/decision_catalog.yaml must exist for guardrails"

@pytest.mark.readonly
def test_decisions_reference_existing_gets(app):
    catalog = yaml.safe_load(CAT_PATH.read_text())
    for d in catalog:
        for ref in d.get("requires", []):
            # accepts "customers_v2.get_profile" etc.
            mod_name, fn_name = ref.rsplit(".", 1)
            mod = importlib.import_module(f"app.extensions.contracts.{mod_name}")
            assert hasattr(mod, fn_name), f"Missing contract GET: {ref}"

@pytest.mark.readonly
def test_contracts_expose_expected_keys(app):
    """Use each contract module's optional __schema__ (if provided)
       to assert DTO keys exist. Modules without __schema__ are skipped.
    """
    catalog = yaml.safe_load(CAT_PATH.read_text())
    seen = set()
    for d in catalog:
        for ref in d.get("requires", []):
            mod_name, fn_name = ref.rsplit(".", 1)
            if mod_name in seen:
                continue
            seen.add(mod_name)
            mod = importlib.import_module(f"app.extensions.contracts.{mod_name}")
            schema = getattr(mod, "__schema__", None)
            if not schema:
                continue
            for fn, meta in schema.items():
                if "returns_keys" in meta:
                    # call with stub args where needed
                    from tests._ulid import make_ulid
                    try:
                        res = getattr(mod, fn)(
                            **{k: make_ulid() for k in meta.get("requires", [])}
                        ) if meta.get("requires") else getattr(mod, fn)()
                    except TypeError:
                        # contract may accept fewer args; best-effort smoke
                        res = getattr(mod, fn)()
                    assert isinstance(res, dict)
                    missing = set(meta["returns_keys"]) - set(res.keys())
                    assert not missing, f"{mod_name}.{fn} missing keys: {missing}"
