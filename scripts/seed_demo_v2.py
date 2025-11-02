# scripts/seed_demo_v2.py (skeleton)

#!/usr/bin/env python3
from __future__ import annotations
import json, os, random
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

SKU_EXAMPLES = ROOT / "exports" / "sku_examples.json" # copy your examples here
POLICY_DST = ROOT / "app" / "slices" / "governance" / "data" / "policy_issuance.json"

def main():
 # 1) Copy policy example if missing
 if not POLICY_DST.exists():
 POLICY_DST.parent.mkdir(parents=True, exist_ok=True)
 POLICY_DST.write_text(json.dumps({
 "version": 1,
 "spending_staff_cap_cents": 20000,
 "rules": [],
 "defaults": {"cadence": {"max_per_period": 1, "period_days": 365, "label": "per_year"}}
 }, indent=2))
 # 2) Load/seed SKUs via Logistics provider (left to slice implementation)
 print("[seed] policy + sku examples staged. Implement slice seeders next.")

if __name__ == "__main__":
 main()
