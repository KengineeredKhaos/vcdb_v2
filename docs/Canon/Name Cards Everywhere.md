# Name Cards Everywhere

Perfect — now you’ve got a solid pattern you can reuse everywhere.

Here’s the “formula” I’d standardize for **any slice that needs a safe display  
name** (Customers included), without leaking PII and without coupling slices.

---

## The Name Card Formula (canonical)

### 1) One cross-slice contract for “who is this ULID?”

**Always** use the Entity contract:

- `entity_v2.get_entity_name_card(entity_ulid) -> EntityNameCardDTO`

- `entity_v2.get_entity_name_cards([...]) -> list[EntityNameCardDTO]`

That’s the *only* path slices use to turn ULIDs into display strings.

### 2) Keep “gymnastics” inside Entity slice

Because your root `Entity` table doesn’t store names, the Entity slice must:

- validate ULID

- read `entity_entity.kind`

- map synonyms / infer from facet existence

- format `display_name` / `short_label`

- cache per-request

No other slice should replicate any of that.

### 3) In every slice: route → passes `entity_card` (or `cards_by_ulid`)

Then templates render a consistent include.

---

## How to apply to Customers

### A) Customer “header card” (wizard + dashboard + detail)

In the Customer routes that render pages keyed by `customer.entity_ulid`:

```python
from app.extensions.contracts import entity_v2
from app.extensions.errors import ContractError

def _try_entity_card(entity_ulid: str):
    try:
        return entity_v2.get_entity_name_card(entity_ulid)
    except ContractError:
        return None

# when rendering:
return render_template(
    "customers/whatever.html",
    entity_ulid=entity_ulid,
    entity_card=_try_entity_card(entity_ulid),
    ...
)
```

Template header:

```jinja2
{% include "customers/_entity_card.html" %}
```

And create `customers/_entity_card.html` exactly like Sponsors/Resources.

### B) Customer list / inbox pages (batch)

Anywhere you have a list like `customers = svc.list_customers()` with ULIDs:

```python
ulids = [c.entity_ulid for c in customers]
cards = entity_v2.get_entity_name_cards(ulids)
cards_by = {c.entity_ulid: c for c in cards}

return render_template(
    "customers/list.html",
    customers=customers,
    cards_by=cards_by,
)
```

Template cell:

```jinja2
{% set card = (cards_by or {}).get(row.entity_ulid) %}
{% if card %}
  <div>{{ card.display_name }}</div>
  <div class="help mono">{{ row.entity_ulid }}</div>
{% else %}
  <div class="mono">{{ row.entity_ulid }}</div>
{% endif %}
```

---

## One small design decision to lock down

For **Customers**, do you want the “short_label” rule to be:

- `"Last, F."` (what we have now), or

- `"Preferred"` when preferred_name exists (already does), or

- `"Last4"` (NO — disallowed, PII)

I recommend you keep it exactly as-is:

- `display_name`: `"Last, Preferred/First"`

- `short_label`: `"Last, F."`

---

## Optional (but worth it): a single shared include file

You can keep it slice-local, but if you want zero duplication, you can put one  
include in `app/templates/components/_entity_card.html` and reuse it across all  
slices. It stays PII-safe because it only consumes the DTO.

(That does not violate slice boundaries: it’s just a template component.)

---

If you tell me **where** in Customer slice you want it next (wizard header,  
customers admin inbox, customer dashboard), I’ll give you the exact 2–3 file  
patch order with the smallest diff.
