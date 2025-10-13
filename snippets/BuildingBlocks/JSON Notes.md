# JSON Notes

- keys and string values use **double quotes** only

- arrays use `[ ... ]`, objects use `{ ... }`

- **no trailing commas** after the last item

- JSON doesn’t allow comments

A list of values and schemas 

---

Strict Schema example

`{ "roles": ["customer", "resource", "sponsor", "governor"] }`

```json
{
"$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["roles"],
  "properties": {
    "roles": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": ["customer", "resource", "sponsor", "governor"]
      },
      "minItems": 1,
      "uniqueItems": true
    }
  }
}
```

When unpacked, this creates a key : value pair for each enumerated item inside square brackets. (i.e. roles:customer, roles:resource, roles:sponsor, ...)

---

Schema-only example

`{ "locale": ["Lakeport", "Upper Lake", "Nice", "Lucerne", "Oaks", "Clearlake", "Lower Lake", "Middletown", "Cobb", "Blue Lakes", "Scotts Valley"] }`
```json
{
"$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["locale"],
  "properties": {
    "locale": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 },
      "minItems": 1,
      "uniqueItems": true
    }
  }
}
```
---

Strict Schema format

`{ "bos": ["USA", "USMC", "USN", "USAF", "USCG", "USSF"] }`
```json
{
"$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["bos"],
  "properties": {
    "bos": {
      "type": "array",
      "items": { "type": "string", "enum": "USA", "USMC", "USN", "USAF", "USCG", "USSF"] },,
      "minItems": 1,
      "uniqueItems": true
    }
  }
}
```

---

`{ "era": ["korea", "vietnam", "coldwar", "lebanon-grenada-panama", "bosnia-herz", "persian-gulf", "iraq", "afghanistan", "africa"] }`
```json
{
"$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["era"],
  "properties": {
    "era": {
      "type": "array",
      "items": { "type": "string", "enum": ["korea", "vietnam", "coldwar", "lebanon-grenada-panama", "bosnia-herz", "persian-gulf", "iraq", "afghanistan", "africa"] },
      "minItems": 1,
      "uniqueItems": true
    }
  }
}
```
---

Draft strict schema
```json
{
"$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["<key>"],
  "properties": {
    "<key>": {
      "type": "array",
      "items": { "type": "string", "enum": [/* canonical entries here */] },
      "minItems": 1,
      "uniqueItems": true
    }
  }
}
```
where <key> is the list name and <canonical entries here> are formatted inside square brackets in double quotes comma separated as in:

["value 1", "value 2", Value 3", VALUE Four"]

What's inside the quotes doesn't matter so long as it matches the declared type.

---

Draft schema-only 

```json
{
"$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["<key>"],
  "properties": {
    "<key>": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 },
      "minItems": 1,
      "uniqueItems": true
    }
  }
}
```

where `<key>` is the list name

## Notes on `jsonutil.py`

- stable_dumps / canonical_hash: ledger events, hashing, caches.

- pretty_dumps: logs, debug, exports for humans.

- safe_loads: user input or optional config blobs—don’t crash on bad JSON.

- json_merge_patch: small “update” payloads on top of stored JSON.

- NDJSON helpers: export/import logs or streaming reports.
