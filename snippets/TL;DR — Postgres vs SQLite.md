# TL;DR — Postgres vs SQLite for *your* app

## What you gain with Postgres

- **Real concurrency.** Multiple writers don’t block the world. Row–/MVCC-based isolation, predictable under load.

- **Stronger durability.** Crash-safe WAL, fsync discipline, point-in-time recovery, streaming replicas, backups that aren’t just “copy a file.”

- **Richer SQL.** Partial indexes, expression indexes, robust JSONB, window functions, CTEs, `ON CONFLICT … DO UPDATE`, strict FK & check constraints that scale.

- **Access control.** True roles/privileges. Easy “read-only on GET” via a RO DB user or transaction-level `SET default_transaction_read_only = on`.

- **Better tooling.** pgAdmin, `EXPLAIN (ANALYZE)`, extensions (pg_trgm, btree_gin), observability.

## What you lose (or add) vs SQLite

- **Operational simplicity.** SQLite is one file; Postgres is a server. You’ll need to operate it (service, users, backups, disk).

- **Zero-config dev story.** Devs need Postgres running (Docker recommended) and a DSN; SQLite “just works.”

- **Some behavior differences.** Locking, types (true booleans, timestamps with/without TZ), case sensitivity, autoincrement semantics, DDL online behavior—all *better* in PG, but different.

## Why SQLite can still be great (for you)

- **Dev & CI speed.** In-memory or temp-file DBs are lightning fast and trivial to reset.

- **Single-user / kiosk / offline.** Your “LAN kiosks” vision fits SQLite well.

- **Simple packaging.** No extra service to manage during early bring-up.

## Where SQLite bites this project

- **Write concurrency.** Your issuance/ledger flows will hit “database is locked” at modest concurrency.

- **Connection-scoped PRAGMAs.** We just danced around `PRAGMA query_only`/pooling in tests; that class of problem goes away in PG.

- **Backups & durability.** You *can* do WAL+hot backup in SQLite, but it’s fiddly and limited vs PG.

---

# Practical call

- **Dev & CI:** keep **SQLite** (fast, disposable), with the request-middleware we outlined so behavior is consistent.

- **Prod:** plan for **Postgres** once you go multi-user and care about uptime, durability, and reporting.

That gives you the best of both worlds: fast local loops, robust prod.

---

# If/when you switch prod to Postgres — exact deltas

**Dependencies**

- Add `psycopg[binary]` (or `psycopg2-binary`) to your venv.

**Config**

- `SQLALCHEMY_DATABASE_URI = "postgresql+psycopg://vcdb:***@db:5432/vcdb"`

- Kill SQLite-only PRAGMAs in prod; keep the *idea* of read-only on GET by:
  
  - Using a **read-only role** for GET traffic, or
  
  - `before_request` → `db.session.execute("SET LOCAL default_transaction_read_only = on")` for safe verbs.

**Engine/session hooks**

- Remove the SQLite `foreign_keys=ON` hook (PG enforces FKs always).

- Keep request teardown (`rollback()` + `remove()`) exactly as we discussed.

**Migrations**

- `flask db upgrade` against PG; review autogen diffs (types may change):
  
  - Use `TIMESTAMP WITH TIME ZONE` (`timestamptz`) for your `*_at_utc`.
  
  - Consider explicit `server_default=text("now() AT TIME ZONE 'utc'")` for created/updated.

**Model nits**

- `String(n)` limits matter in PG for index bloat; set sane lengths on indexed text.

- If you use JSON, switch to `JSONB` via SQLAlchemy’s `JSON` type (PG dialect maps to JSONB).

**Ops**

- Turn on WAL archiving & periodic base backups (pgBackRest, WAL-G, or simple `pg_dump` + WAL).

- Use a small connection pool (gunicorn/mod_wsgi workers × few conns) via SQLAlchemy.

---

# Decision cheat sheet

- **Single laptop / kiosk demos:** SQLite only.

- **Small office, a few concurrent users:** Postgres (prod) + SQLite (dev/CI).

- **You want reliable backups, PITR, future analytics:** Postgres.

If that fits, we can paste the **read-only request middleware** right now (SQLite+PG compatible) and you’ll be set no matter which backend you point at.
