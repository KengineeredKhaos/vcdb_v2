# vcdb-v2/tasks.py — Pythonic task runner for VCDB v2
# Usage examples:
#   inv -l                               # list tasks
#   inv policy-lint                      # validate all policies
#   inv policies-fix                     # validate + pretty-print policies
#   inv seed-canonical                   # seed canonical logistics stock
#   inv decide-issue --sku AC-GL-...     # run decision logic for a SKU
#   inv bootstrap                        # end-to-end: lint → seed → validate → demo

import os

from invoke import task

# ---- knobs (override at call: inv policy-lint --base=... --schemas=...) ----
FLASK = os.environ.get("VCDB_FLASK", "bin/flask")
DEFAULT_BASE = "app/slices/governance/data"
DEFAULT_SCHEMAS = f"{DEFAULT_BASE}/schemas"


# ---- shell helpers ----------------------------------------------------------
def _run(c, cmd: str):
    # pty=True for nicer output (colors, cursor control)
    return c.run(cmd, pty=True)


# ---- CLI wrappers (call your Click/Flask commands as-is) --------------------
@task(
    help={
        "base": "Policies directory containing JSON files",
        "schemas": "Directory containing *.schema.json files",
        "fix": "Pretty-print JSON on success",
        "print_paths": "Echo resolved paths before validation",
    }
)
def policy_lint(
    c,
    base=DEFAULT_BASE,
    schemas=DEFAULT_SCHEMAS,
    fix=False,
    print_paths=False,
):
    """Validate all governance policies against their schemas."""
    flags = []
    if fix:
        flags.append("--fix")
    if print_paths:
        flags.append("--print-paths")
    _run(
        c,
        f"{FLASK} dev policy-lint --which all --base {base} --schema-base {schemas} {' '.join(flags)}",
    )


@task(help={"base": "Policies directory", "schemas": "Schemas directory"})
def policies_fix(c, base=DEFAULT_BASE, schemas=DEFAULT_SCHEMAS):
    """Validate + pretty-print governance policies."""
    _run(
        c,
        f"{FLASK} dev policy-lint --which all --base {base} --schema-base {schemas} --fix",
    )


@task
def seed_canonical(c):
    """Seed a clean, predictable canonical set of logistics SKUs at LOC-MAIN."""
    _run(c, f"{FLASK} dev seed-logistics-canonical")


@task
def validate_skus(c):
    """Validate SKUs found in catalog + issues."""
    _run(c, f"{FLASK} dev validate-skus")


@task(help={"location": "Stock location code (e.g., LOC-MAIN)"})
def list_stock(c, location="LOC-MAIN"):
    """Show on-hand inventory at a location."""
    _run(c, f"{FLASK} dev list-stock --location {location}")


@task
def demo_issue(c):
    """Run the happy-path issuance (random pick from stock)."""
    _run(c, f"{FLASK} dev demo-issue")


@task(
    help={
        "sku": "SKU code (e.g., AC-GL-LC-L-LB-U-00B)",
        "customer": "Customer ULID (default TEST-CUST)",
        "force_blackout": "Trip the blackout enforcer (true/false)",
    }
)
def decide_issue(c, sku, customer="TEST-CUST", force_blackout=False):
    """Evaluate issuance policy for a SKU; does not persist."""
    fb = (
        "--force-blackout"
        if str(force_blackout).lower() in ("1", "true", "yes", "y")
        else ""
    )
    _run(c, f"{FLASK} dev decide-issue {sku} --customer {customer} {fb}")


@task(help={"sku": "SKU code to trace"})
def issuance_debug(c, sku):
    """Print gate-by-gate decision trace for one SKU."""
    _run(c, f"{FLASK} dev issuance-debug --sku {sku}")


@task
def issuance_tripwires(c):
    """Exercise each issuance rule with synthetic SKUs to verify tripwires."""
    _run(c, f"{FLASK} dev issuance-tripwires")


@task
def purge_seed_items(c):
    """Remove legacy logistics rows named 'Seed Item' (safe cleanup)."""
    _run(c, f"{FLASK} dev purge-seed-items")


@task
def whoami(c):
    """Dump minimal context useful during local dev."""
    _run(c, f"{FLASK} dev whoami")


# ---- Playbooks (compose multiple steps with simple flow control) ------------
@task
def bootstrap(c):
    """End-to-end: policy lint → seed canonical → validate SKUs → demo issue."""
    policy_lint(c, print_paths=True)  # fail-fast if invalid
    seed_canonical(c)
    validate_skus(c)
    demo_issue(c)
