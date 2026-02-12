# SKU Standardization

A simple, durable SKU format

**Format: 15–18 chars (illistrated w/ hyphens for readability):**  
`CAT-SUB-SRC-SZ-COL-CND-SEQ`

- **CAT** (2): category
  
  - UW = undergarments
  - OW = outerwear
  - CW = cold-weather
  - FW =footwear
  - CG = camping
  - AC = accouterments
  - FD = foodstuffs
  - DG = Durable Goods

- **SUB** (2–3): subcategory
  
  - TP = top
  - BT = bottom
  - SK = socks
  - GL = gloves
  - HT = hats
  - BG = bags
  - SL = sleep
  - SH = shelter
  - KT = kit

- **SRC** (2): source
  
  - DR = DRMO/Defense surplus
  - LC = local commercial

- **SZ** (2–3): size
  
  - XS, S, M, L, XL, 2X, 3X, numeric (e.g., 70, 75, 110, 115 for footwear)

- **COL** (2–3): color/pattern
  
  - BK = black
  - BL = blue
  - LB = light blue
  - BR = brown
  - TN = tan
  - GN = green
  - RD = red
  - OR = orange
  - YL = yellow
  - WT = white
  - OD = olive drab
  - CY = coyote
  - FG = foliage
  - MC = multicam
  - MX = mixed/assorted

- **CND** (1): classification for issuance (internal, Customer-dependent factor)
  
  - V = veteran only
  - H = homeless only
  - D = durable goods, returned after use
  - U = unclassified

- **SEQ** (3): unique base-36 counter per subfamily (000–ZZZ)

Store without hyphens in your system if you want compact codes; print with hyphens for humans.

---

# The plan (clean + boring)

1. **Keep “SKU format.md” as the canon.** Your `sku.py` already matches it — great.

2. **Split policy concerns:**
   
   - **Issuance policy** (who/when can receive) → `policy_issuance.json`
   
   - **SKU construction constraints** (what a SKU is allowed to be) → `policy_sku_constraints.json` (new)

3. **Schema-first.** Validate both files on load; fail fast with clear errors.

4. **Evaluator order** in `governance.services.decide_issue(...)` (no shims):
   
   1. **SKU constraints check (construction)** — deny if SKU violates constraints
   
   2. **Rule match** (classification or SKU) — deny if no matching rule
   
   3. **Qualifiers** (customer snapshot flags) — deny if not met
   
   4. **Calendar** (blackout/funding) — deny if blocked
   
   5. **Cadence** (with scope = classification or sku) — deny if limit hit

5. **Admin kindness:** presets for cadence, predictable match keys, and a CLI that shows coverage.

---

## A) New: SKU constraints policy (construction rules)

**`app/slices/governance/data/policy_sku_constraints.json`**

```json
{
  "version": 1,
  "rules": [
    {
      "if": { "source": "DR" },
      "then": { "issuance_class": "V" },
      "why": "All DRMO items are veteran-only"
    },
    {
      "if": { "category": "CG", "subcategory": "SL", "source": "LC" },
      "then": { "issuance_class": "H" },
      "why": "Commercial sleeping gear reserved for homeless issuance"
    }
  ]
}
```

**Schema (optional but recommended):**  
`app/slices/governance/data/schemas/policy_sku_constraints.schema.json`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "VCDB SKU Construction Constraints",
  "type": "object",
  "required": ["version", "rules"],
  "properties": {
    "version": { "type": "integer", "minimum": 1 },
    "rules": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["if", "then"],
        "properties": {
          "if": {
            "type": "object",
            "properties": {
              "category": { "type": "string" },
              "subcategory": { "type": "string" },
              "source": { "type": "string" },
              "size": { "type": "string" },
              "color": { "type": "string" },
              "issuance_class": { "type": "string" }
            },
            "additionalProperties": false
          },
          "then": {
            "type": "object",
            "properties": {
              "issuance_class": { "type": "string", "enum": ["V","H","D","F","U"] }
            },
            "required": ["issuance_class"],
            "additionalProperties": false
          },
          "why": { "type": "string" }
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

---

## B) Issuance policy: add **cadence scope** and **SKU matching**

### 1) Schema additions (so you can express “per SKU” cadence and match by SKU)

**`app/slices/governance/data/schemas/policy_issuance.schema.json`**  
(Add two things: `cadence.scope` and `match.sku`/`match.sku_parts`.)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "VCDB Issuance Policy",
  "type": "object",
  "required": ["rules"],
  "properties": {
    "spending_staff_cap_cents": { "type": "integer", "minimum": 0 },
    "defaults": {
      "type": "object",
      "properties": {
        "cadence": {
          "type": "object",
          "required": ["max_per_period", "period_days"],
          "additionalProperties": false,
          "properties": {
            "max_per_period": { "type": "integer", "minimum": 1 },
            "period_days": { "type": "integer", "minimum": 1 },
            "label": { "type": "string" },
            "scope": { "type": "string", "enum": ["classification","sku"], "default": "classification" }
          }
        }
      },
      "additionalProperties": false
    },
    "rules": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["match"],
        "properties": {
          "match": {
            "type": "object",
            "properties": {
              "classification_key": { "type": "string" },
              "sku": { "type": "string", "description": "Exact SKU or glob-like with * segments, e.g., CG-SL-LC-*-*-H-*" },
              "sku_parts": {
                "type": "object",
                "properties": {
                  "category": { "type": "string" },
                  "subcategory": { "type": "string" },
                  "source": { "type": "string" },
                  "size": { "type": "string" },
                  "color": { "type": "string" },
                  "issuance_class": { "type": "string" }
                },
                "additionalProperties": false
              }
            },
            "additionalProperties": false
          },
          "qualifiers": {
            "type": "object",
            "properties": {
              "veteran_required": { "type": "boolean" },
              "homeless_required": { "type": "boolean" }
            },
            "additionalProperties": false
          },
          "cadence": {
            "type": "object",
            "required": ["max_per_period", "period_days"],
            "additionalProperties": false,
            "properties": {
              "max_per_period": { "type": "integer", "minimum": 1 },
              "period_days": { "type": "integer", "minimum": 1 },
              "label": { "type": "string" },
              "scope": { "type": "string", "enum": ["classification","sku"], "default": "classification" }
            }
          },
          "cadence_preset": { "type": "string", "enum": ["annual","semiannual","quarterly"] }
        },
        "additionalProperties": false,
        "allOf": [
          { "if": { "required": ["cadence_preset"] },
            "then": { "not": { "required": ["cadence"] } } }
        ]
      }
    }
  },
  "additionalProperties": false
}
```

**Presets mapping (in code):**

- `annual` → `{period_days: 365, max_per_period: 1}`

- `semiannual` → `{period_days: 182, max_per_period: 1}`

- `quarterly` → `{period_days: 90, max_per_period: 1}`

### 2) Policy example (per-SKU cadence and a WHK rule)

**`app/slices/governance/data/policy_issuance.json`**

```json
{
  "spending_staff_cap_cents": 20000,
  "defaults": {
    "cadence": { "max_per_period": 1, "period_days": 365, "label": "per_year", "scope": "classification" }
  },
  "rules": [
    {
      "match": { "classification_key": "basic_needs.clothing.top" },
      "qualifiers": { "veteran_required": true },
      "cadence_preset": "annual"
    },
    {
      "match": { "classification_key": "housing.sleeping_gear.bag" },
      "qualifiers": { "veteran_required": false },
      "cadence_preset": "quarterly"
    },
    {
      "match": { "sku_parts": { "category": "CG", "subcategory": "SL", "source": "LC" } },
      "qualifiers": { "homeless_required": true },
      "cadence": { "period_days": 90, "max_per_period": 1, "scope": "sku", "label": "bag-per-90d" }
    },
    {
      "match": { "classification_key": "welcome_home.kit" },
      "qualifiers": { "veteran_required": true },
      "cadence": { "period_days": 90, "max_per_period": 1, "scope": "classification", "label": "WHK-per-90d" }
    }
  ]
}
```

> Note: we’ve moved away from `per_sku` boolean (which your schema rejected) to a clean `cadence.scope`.

---

## C) Enforce constraints in one place (construction & evaluation)

### 1) On item create (Logistics) — fail fast if SKU violates constraints

In `app/slices/logistics/services.py`, inside `ensure_item(...)` **after** you parse the SKU (`parts = parse_sku(sku)` or build from `sku_parts`), add:

```python
# Enforce construction constraints (raises ValueError if violated)
from app.extensions.policy_semantics import assert_sku_constraints_ok
assert_sku_constraints_ok(parts)  # parts keys: category, subcategory, source, size, color, issuance_class
```

### 2) At decision time (Governance) — double-check

In `governance/services.decide_issue(...)`, **before** qualifiers/cadence:

```python
from app.slices.logistics.sku import parse_sku
from app.extensions.policy_semantics import check_sku_constraints
parts = parse_sku(ctx.sku_code)
ok, why = check_sku_constraints(parts)
if not ok:
    return IssueDecision.deny(reason="sku_constraint", detail=why)
```

### 3) Policy semantics helpers (single source)

Add to `app/extensions/policy_semantics.py`:

```python
import fnmatch
from app.extensions.policies import load_json_file, validate_json_payload  # if you have these
from app.lib.jsonutil import load_json  # or your existing util

def _load_sku_constraints() -> dict:
    path = "app/slices/governance/data/policy_sku_constraints.json"
    schema = "app/slices/governance/data/schemas/policy_sku_constraints.schema.json"
    data = load_json(path)
    # if you validate: validate_json_payload(data, schema)
    return data

def check_sku_constraints(parts: dict) -> tuple[bool, str | None]:
    """Return (ok, why) for SKU construction policy."""
    pol = _load_sku_constraints()
    for r in pol.get("rules", []):
        cond = r.get("if", {})
        # all provided keys must match exactly
        if all(parts.get(k) == v for k, v in cond.items()):
            expected = (r.get("then") or {}).get("issuance_class")
            if expected and parts.get("issuance_class") != expected:
                why = r.get("why") or f"requires issuance_class={expected}"
                return (False, why)
    return (True, None)

def assert_sku_constraints_ok(parts: dict) -> None:
    ok, why = check_sku_constraints(parts)
    if not ok:
        raise ValueError(f"SKU violates constraints: {why}")
```

---

## D) Governance evaluator small tweaks

In `governance/services.py`:

- **Presets → cadence object**:

```python
def _cadence_from(rule: dict) -> dict:
    preset = rule.get("cadence_preset")
    if preset:
        mapping = {
            "annual":      {"period_days": 365, "max_per_period": 1, "label": "annual"},
            "semiannual":  {"period_days": 182, "max_per_period": 1, "label": "semiannual"},
            "quarterly":   {"period_days": 90,  "max_per_period": 1, "label": "quarterly"},
        }
        c = dict(mapping[preset])
    else:
        c = dict(rule.get("cadence", {}))
    # inherit defaults, then override
    c.setdefault("period_days", defaults["cadence"]["period_days"])
    c.setdefault("max_per_period", defaults["cadence"]["max_per_period"])
    c.setdefault("label", defaults["cadence"].get("label"))
    c.setdefault("scope", defaults["cadence"].get("scope", "classification"))
    return c
```

- **Rule matching** (support `match.sku` and `match.sku_parts`):

```python
def _rule_matches(rule: dict, ctx) -> bool:
    m = rule.get("match", {}) or {}
    ck = m.get("classification_key")
    if ck and ck != ctx.classification_key and ck != "*":
        return False
    sku_pat = m.get("sku")
    if sku_pat:
        if not _sku_glob_match(ctx.sku_code, sku_pat):
            return False
    sp = m.get("sku_parts") or {}
    if sp:
        parts = parse_sku(ctx.sku_code)
        for k, v in sp.items():
            if parts.get(_map_part_key(k)) != v:  # _map_part_key maps policy names to parser names if needed
                return False
    return True

def _sku_glob_match(code: str, pattern: str) -> bool:
    # pattern like "CG-SL-LC-*-*-H-*"
    import fnmatch
    return fnmatch.fnmatch(code, pattern)
```

- **Cadence scope** (classification vs sku) — you already saw the shape:

```python
cad = _cadence_from(rule)
scope = cad.get("scope", "classification")
count = logistics_v2.count_issues_in_window(
    customer_ulid=ctx.customer_ulid,
    classification_key=ctx.classification_key if scope == "classification" else None,
    sku_code=ctx.sku_code if scope == "sku" else None,
    window_start_iso=window_start_iso,
    window_end_iso=window_end_iso,
)
```

- **Qualifiers** minimal set: `veteran_required`, `homeless_required` checked against your snapshot fields (`is_veteran_verified`, `is_homeless_flag`, etc.). Keep this tiny and documented.

---

## E) Admin kindness: one helper CLI

Generate a **starter issuance rules file** for any set of SKUs you select, prefilled with per-SKU cadence presets and placeholders for qualifiers:

```python
@dev_group.command("issuance-template-for-skus")
@with_appcontext
@click.option("--sku-like", required=True, help="fnmatch pattern, e.g. CG-SL-LC-*-*-*-*")
@click.option("--preset", default="quarterly", type=click.Choice(["annual","semiannual","quarterly"]))
def dev_issuance_template_for_skus(sku_like: str, preset: str):
    from sqlalchemy import select
    from app.extensions.db import db
    from app.slices.logistics.models import InventoryItem
    rows = db.session.execute(select(InventoryItem.sku, InventoryItem.category)).all()
    import fnmatch, json
    matches = [{"sku": s, "classification": c} for s, c in rows if fnmatch.fnmatch(s, sku_like)]
    rules = [{
        "match": { "sku": m["sku"] },
        "qualifiers": { "veteran_required": false },
        "cadence_preset": preset
    } for m in matches]
    click.echo(json.dumps({"rules": rules}, indent=2))
```

This lets the next Admin/Dev bootstrap sane rules quickly.

---

## F) Run checklist (once)

1. Save the new JSON files & schemas.

2. Wire `policy_semantics` helpers + evaluator changes.

3. In `logistics.ensure_item` add `assert_sku_constraints_ok(parts)` so bad SKUs can’t enter.

4. `flask dev policy-health` (should show both policies OK).

5. `flask dev issuance-coverage` (WHK no longer “uncovered”).

6. `flask dev eligible-explain <cust> --match-class welcome_home.kit` → now you’ll see allow/deny for clear reasons.

---

This gets you: one canonical SKU spec, strict construction constraints, clean per-SKU cadence, and a small qualifiers set that you can expand later — all validated up front and enforced in exactly two places (on write, and at decision time).
