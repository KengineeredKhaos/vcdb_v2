# Timestamps and lib_chrono_py Deployment

Great question. Those three helpers give you one simple superpower: **timestamps that are always in one, consistent, lossless, machine-sortable format**—no matter where they came from. That’s especially important with SQLite, which has no native `TIMESTAMP WITH TIME ZONE` type.

Here’s what each does and why you want it:

## What they produce

* `utc_now() -> str`
  Returns the **current time in UTC**, formatted as an **ISO-8601 string with a `Z` suffix** and **millisecond** precision, e.g.:
  `2025-10-06T14:23:45.123Z`
  (It truncates microseconds to milliseconds for stable comparisons and pretty output.)

* `to_iso8601(dt: datetime) -> str`
  Takes **any** `datetime` (naive or tz-aware), converts it to **UTC**, and emits the **same canonical string** format as above. If it’s naive, we (safely) force UTC so you don’t leak local times downstream.

* `parse_iso8601(s: str) -> datetime`
  Takes one of those strings (or any ISO string with `Z` or an offset), and returns an **aware UTC `datetime`**. If the input is naive, it raises—preventing silent bugs.

## Why this matters for SQLite (and your app)

* **SQLite stores times as TEXT/REAL/INTEGER**, not true time types. Canonical ISO-8601 UTC strings:
  
  * sort correctly as plain strings,
  * round-trip across JSON / HTTP / storage without ambiguity,
  * avoid time zone drift and DST nightmares.

* **Deterministic ledger hashing & audits**
  A stable representation (UTC + ms) keeps event hashes reproducible. “Same moment, same bytes.”

* **Contracts & DTOs**
  Boundary layers between slices always speak the same timestamp dialect. Your forms, APIs, and templates don’t have to guess.

* **Indexing & querying**
  ISO strings let you do range queries easily in SQLite:
  `WHERE happened_at BETWEEN '2025-01-01T00:00:00.000Z' AND '2025-12-31T23:59:59.999Z'`
  and they stay lexicographically ordered.

## When to use which

* **Write now:** `utc_now()`
  Stamp new rows/events (`created_at`, `happened_at`, request IDs, etc.).

* **Normalize before save/emit:** `to_iso8601(dt)`
  Any `datetime` coming from Python, a form, or a library gets normalized to canonical UTC string before you store it or put it on the wire.

* **Read/compute:** `parse_iso8601(s)`
  When you need to do arithmetic or comparisons in Python, parse the stored string back to an aware UTC `datetime`.

## Tiny examples

```python
# Create a ledger event
event = {
    "id": new_ulid(),
    "happened_at": utc_now(),
    "actor_id": actor_ulid,
    "operation": "policy.update",
}

# Normalize an incoming user-specified deadline
deadline = to_iso8601(user_supplied_dt)

# Load from DB and compute
dt = parse_iso8601(row["happened_at"])
if utc_now() > to_iso8601(dt + timedelta(days=30)):
    ...
```

## Practical tips

* **Columns**: store as `TEXT` with a CHECK, e.g. `CHECK (happened_at LIKE '____-__-__T__:__:__.___%Z')` (lightweight guard).
* **Precision**: milliseconds are a good compromise—human readable and stable; if you truly need micros, adjust both formatter and parser together.
* **Display**: keep DTOs/contracts in UTC; convert to local time **only in the UI**.
* **Migrations**: for old rows, run a one-off normalizer: parse → `to_iso8601` → update.

In short: these three functions give you a **single canonical time format** end-to-end—exactly what you want for SQLite, contracts, and a cryptographically chained ledger.
