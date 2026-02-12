# VCDB v2 – Migration Protocol (SQLite + Alembic)

## 0) Ground Rules / Invariants

- **Never** mutate or delete rows in `transactions_ledger`; only append and repair links/hashes.

- **Every write** must have a non-empty `request_id` (system tasks may use a scoped prefix like `sys-...`).

- **Emit events** for schema-affecting data migrations (e.g., backfills that change business state).

- Keep **slice models isolated**; register blueprints first, import models **inside** app factory after blueprints to avoid circulars.

- SQLite: use **batch mode** for altering tables; raw `ALTER CONSTRAINT` is not supported.

---

## 1) Before You Start

- Freeze working state:
  
  ```bash
  zip -r ~/archives/vcdb-$(date +%F_%H%M).zip .
  pip freeze > snippets/pip.freeze.$(date +%F).txt
  ```

- Sanity & schema diff:
  
  ```bash
  python manage_vcdb.py  # boot sanity prints
  PYTHONPATH=. python scripts/verify_ledger_chain.py
  ```

- Confirm **models import cleanly**:
  
  ```bash
  PYTHONPATH=. python - <<'PY'
  ```

from app import create_app  
app = create_app("config.DevConfig")  
with app.app_context():  
print("OK app_context")  
PY

```
---

## 2) Alembic Basics

### 2.1 Init (first time only)
```bash
flask db init
```

### 2.2 Configure Alembic env (once)

In `migrations/env.py`, ensure:

- App context is used to load models

- **Render as batch** in SQLite:

```python
from alembic import context
from sqlalchemy import engine_from_config, pool
from logging.config import fileConfig
from app import create_app
from app.extensions import db

config = context.config
fileConfig(config.config_file_name)

def run_migrations_online():
    app = create_app("config.DevConfig")
    with app.app_context():
        connectable = db.engine
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=db.metadata,
                render_as_batch=True,  # <-- important for SQLite
                compare_type=True,
                compare_server_default=True,
            )
            with context.begin_transaction():
                context.run_migrations()
run_migrations_online()
```

---

## 3) Baseline vs. Change Revisions

### 3.1 Create a **baseline** (first tracked schema)

> Do this when Alembic is introduced, not on a live-prod delta.

```bash
flask db revision -m "baseline schema"
# Manually edit: NO destructive ops; just create current tables (if needed).
flask db upgrade
```

### 3.2 Make a change revision

- Update your models (e.g., add `entity_*` tables).

- Autogenerate:
  
  ```bash
  flask db revision --autogenerate -m "entity core"
  ```

- **Review and fix** (SQLite needs batch context):

Example (good pattern):

```python
def upgrade():
    with op.batch_alter_table("entity_entity", schema=None) as batch:
        # add columns / constraints here
        pass

    # Partial unique indexes or check constraints: raw SQL
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_entity_org_ein_notnull "
        "ON entity_org(ein) WHERE ein IS NOT NULL"
    )

def downgrade():
    op.execute("DROP INDEX IF EXISTS ux_entity_org_ein_notnull")
    with op.batch_alter_table("entity_entity", schema=None) as batch:
        pass
```

> **Avoid**: dropping useful indexes like `ux_users_email`, `ux_ledger_request_id`.

---

## 4) Patterns & Recipes (SQLite-safe)

### 4.1 New tables (Entity slice example)

```python
def upgrade():
    op.create_table(
        "entity_entity",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "entity_person",
        sa.Column("entity_id", sa.String(26), sa.ForeignKey("entity_entity.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("first_name", sa.String(80), nullable=False),
        sa.Column("last_name", sa.String(80), nullable=False),
    )
    op.create_table(
        "entity_org",
        sa.Column("entity_id", sa.String(26), sa.ForeignKey("entity_entity.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("legal_name", sa.String(200), nullable=False),
        sa.Column("doing_business_as", sa.String(200)),
        sa.Column("ein", sa.String(9), nullable=True),
    )
    op.create_table(
        "entity_role",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("entity_id", sa.String(26), sa.ForeignKey("entity_entity.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_code", sa.String(32), nullable=False),
    )
    op.create_index("ix_entity_role_code", "entity_role", ["role_code"])
    op.create_unique_constraint("ux_entity_role", "entity_role", ["entity_id", "role_code"])

    # Partial unique EIN index (only when not null)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_entity_org_ein_notnull "
        "ON entity_org(ein) WHERE ein IS NOT NULL"
    )
```

### 4.2 Add column to existing table

```python
with op.batch_alter_table("entity_org") as batch:
    batch.add_column(sa.Column("ein", sa.String(9), nullable=True))
op.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_entity_org_ein_notnull "
    "ON entity_org(ein) WHERE ein IS NOT NULL"
)
```

### 4.3 Add check constraint (use trigger if SQLite blocks ALTER)

Prefer **application-level** validation; for DB-level in SQLite use triggers or new-table-copy pattern. Example trigger to block empty request IDs in ledger (optional if already enforced in code):

```python
op.execute("""
CREATE TRIGGER IF NOT EXISTS trg_ledger_request_id_nonempty
BEFORE INSERT ON transactions_ledger
FOR EACH ROW
BEGIN
  SELECT CASE
    WHEN NEW.request_id IS NULL OR length(trim(NEW.request_id)) = 0
    THEN RAISE(ABORT, 'request_id must be non-empty')
  END;
END;
""")
```

---

## 5) Data Migrations (online & safe)

### 5.1 Use idempotent scripts under `scripts/sql/` or `scripts/python/`

- **Read-only first**, then **append-only** changes with ledger emits.

- Example: backfill EIN formatting; do **NOT** rewrite ledger content—emit `entity.org.updated`.

### 5.2 Run backfills in app context if SQLAlchemy models are used

```bash
PYTHONPATH=. python - <<'PY'
from app import create_app
from app.extensions import db
from app.slices.entity.models import Org
app = create_app("config.DevConfig")
with app.app_context():
    for org in Org.query.filter(Org.ein.isnot(None)):
        # normalize EIN if needed, emit events if you change state
        pass
PY
```

---

## 6) Upgrade / Downgrade Procedure

### 6.1 Create migration

```bash
flask db revision --autogenerate -m "entity core"
```

### 6.2 Review & adjust (batch, partial indexes, triggers, constraints)

### 6.3 Apply

```bash
flask db upgrade
```

### 6.4 Verify

```bash
python manage_vcdb.py                         # boot sanity
PYTHONPATH=. python scripts/verify_ledger_chain.py
bash scripts/smoke_slices.sh
sqlite3 var/app-instance/dev.db "PRAGMA integrity_check;"
```

### 6.5 Rollback (if needed)

```bash
flask db downgrade -1
```

> Keep a **zip archive** and `dev.db.sql` export before any destructive changes.

---

## 7) Common Gotchas

- **Circular imports**: do not import routes from models or services; import models only inside app factory after registering blueprints.

- **Alembic autogenerate drops indexes** you still want—delete those lines before upgrade.

- **SQLite ALTER**: always use `render_as_batch=True` and `batch_alter_table`.

- **Ledger hash chain**: if you must re-link historic rows, use the approved scripts:
  
  - `scripts/repair_ledger_links.py --commit`
  
  - `scripts/verify_ledger_chain.py`

- **Uniqueness**: enforce at both app layer **and** DB layer (unique constraints / partial indexes).

- **Policy-driven choices** (like role codes): default in code, overridable via Governance; don’t hardcode in migrations.

---

## 8) Quick-start: Entity Core Migration (cheat sheet)

1. Update/confirm models under `app/slices/entity/models.py`.

2. Create migration:
   
   ```bash
   flask db revision --autogenerate -m "entity core"
   ```

3. Edit migration:
   
   - wrap alters with `batch_alter_table`
   
   - add partial unique index SQL for EIN (if present)

4. Upgrade:
   
   ```bash
   flask db upgrade
   ```

5. Seed minimal data (optional) with **emits**:
   
   ```bash
   PYTHONPATH=. python scripts/dev_seed_entity.py
   ```

6. Verify:
   
   ```bash
   python manage_vcdb.py
   PYTHONPATH=. python scripts/verify_ledger_chain.py
   bash scripts/smoke_slices.sh
   ```

---

## 9) Template for a New Migration (SQLite-safe)

```python
"""meaningful title

Revision ID: 20250925_entity_core
Revises: <prev>
Create Date: 2025-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "20250925_entity_core"
down_revision = "<prev>"
branch_labels = None
depends_on = None

def upgrade():
    # create/alter in batch, add raw SQL for partial indexes or triggers
    with op.batch_alter_table("some_table", schema=None) as batch:
        # batch.add_column(...)
        # batch.create_unique_constraint(...)
        pass

    # Example partial index / trigger:
    # op.execute("CREATE UNIQUE INDEX ... WHERE ...")
    # op.execute("""CREATE TRIGGER ...""")

def downgrade():
    # reverse raw SQL
    # op.execute("DROP INDEX IF EXISTS ...")
    with op.batch_alter_table("some_table", schema=None) as batch:
        # batch.drop_constraint(...)
        # batch.drop_column(...)
        pass
```

---

## 10) Post-Deploy Checklist

- App starts cleanly (boot sanity OK).

- `smoke_slices.sh` passes.

- Ledger chain verified OK.

- Policy keys snapshot captured (Governance → JSON export if you’ve wired it).

- Archive:
  
  ```bash
  sqlite3 var/app-instance/dev.db ".backup 'var/app-instance/dev.$(date +%F_%H%M).db'"
  zip -r ~/archives/vcdb-after-migration-$(date +%F_%H%M).zip .
  ```

---

This outline should keep migrations predictable, boring, and audit-friendly. If you want, I can also scaffold the **first Entity core revision** file using your current models so you can `flask db upgrade` immediately.
