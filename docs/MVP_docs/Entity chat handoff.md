## VCDB v2 — Handoff Snapshot (paste me in new chat)

**Stack & boot**

- Python 3.12 · Flask · Flask-Login · Jinja2 · SQLite (dev DB at `var/app-instance/dev.db`)

- App factory: `app.create_app("config.DevConfig")`

- Blueprints registered: `auth, calendar, customers, entity, governance, inventory, resources, sponsors, transactions, web`

- CSRF enabled via `extensions.csrf`

- Login manager lives in `app/extensions/__init__.py` and is **bound** (boot sanity shows OK)

**Extensions (stable surface)**

- `db`, `csrf`, `migrate`, `logger/jsonl`, `ulid()`

- `event_bus.emit(...)` wired to Transactions slice sink

- `policy.get(...)` with governance seed support

- Helpers added:
  
  - `allowed_role_codes()` → defaults `("customer","resource","sponsor","staff","admin")`, overridable by `policy["entity.allowed_roles"]`
  
  - `US_STATE_CHOICES` tuple
  
  - Validation/normalizers (email/phone/state) are used in services

**Transactions ledger**

- Hash-chain verified OK (`scripts/verify_ledger_chain.py`) after repair (`scripts/repair_ledger_links.py --commit`)

- Services enforce **non-empty `request_id`** (system events may use scoped prefix)

- Guardrail migrations planned: partial index on `request_id` + trigger to reject empty values (SQLite batch/SQL)

**Entity slice (new paradigm)**

- Models: `Entity` (kind=`person|org`), `Person`, `Org`, `Role` (UX: `ux_entity_role`), `Address`

- Services: `ensure_role(...)` (idempotent, emits only on change), normalization/validation on email/phone/state/EIN

- Routes:
  
  - `GET /entity/create` renders form with dropdowns (states, roles)
  
  - `POST /entity/create` creates person/org (+ optional address) and can attach a role
  
  - `GET /entity/list` lists people

- Templates:
  
  - `app/templates/_forms.html` macros (text/select/radios)
  
  - `entity/create.html` (HTML5 patterns + light JS for EIN/phone)
  
  - `layout/base.html` + `web/index.html` (hero landing) already in place

**Smoke & tooling**

- `scripts/smoke_slices.sh` (login, hello routes, logout w/ CSRF; now green)

- `scripts/verify_chain.sh` wrapper calls verify_ledger_chain

- `scripts/print_ledger.py`, `dev_emit.py` (auth role assign/remove), `show_roles.py`

- Boot sanity prints routes, extensions, login manager, and schema diffs

**Known schema state (dev)**

- Legacy `customers` table still present (to be retired after full Entity migration)

- Alembic initialized; last good autogen: `"entity core"` pending

- Use `render_as_batch=True`; **don’t drop** `ux_users_email` or `ux_ledger_request_id`

**Next actions (short)**

1. Generate & apply **Entity core** migration (SQLite-safe; create entity_*, role uniq, EIN partial index).

2. Point Customers/Resources/Sponsors to **Entity + Role** (start with reads; writes follow).

3. Governance: seed `policy["entity.allowed_roles"]` if you want to change defaults.

4. Optional guardrail migration for ledger: partial index + trigger.

5. Keep using smoke + verify scripts after each change.

**Common commands**

```bash
# run app 
python manage_vcdb.py  
# create tables for current models (dev only) 
PYTHONPATH=. python scripts/db_create_all.py  
# alembic (SQLite batch configured in env.py)
flask db revision --autogenerate -m "entity core"
flask db upgrade  
# sanity 
bash scripts/smoke_slices.sh 
PYTHONPATH=. python scripts/verify_ledger_chain.py 
sqlite3 var/app-instance/dev.db "PRAGMA integrity_check;"`
```

here’s a **SQLite-safe Alembic migration skeleton** for the **Entity core**. Drop this into `migrations/versions/<stamp>_entity_core.py`, adjust `down_revision`, then `flask db upgrade`.

```python
"""entity core (Entity/Person/Org/Role/Address)

Revision ID: 20250925_entity_core
Revises: <put_previous_revision_here>
Create Date: 2025-09-25 10:00:00
"""
from alembic import op
import sqlalchemy as sa

# --- Alembic identifiers ---
revision = "20250925_entity_core"
down_revision = "<put_previous_revision_here>"
branch_labels = None
depends_on = None


def upgrade():
    # entity_entity
    op.create_table(
        "entity_entity",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),  # 'person' | 'org'
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind in ('person','org')", name="ck_entity_kind"),
    )
    op.create_index("ix_entity_entity_kind", "entity_entity", ["kind"])

    # entity_person (1:1 with entity_entity)
    op.create_table(
        "entity_person",
        sa.Column(
            "entity_id",
            sa.String(length=26),
            sa.ForeignKey("entity_entity.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("first_name", sa.String(length=80), nullable=False),
        sa.Column("last_name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=255)),
        sa.Column("phone", sa.String(length=32)),
    )
    op.create_index("ix_entity_person_last_name", "entity_person", ["last_name"])
    op.create_index("ix_entity_person_email", "entity_person", ["email"])

    # entity_org (1:1 with entity_entity)
    op.create_table(
        "entity_org",
        sa.Column(
            "entity_id",
            sa.String(length=26),
            sa.ForeignKey("entity_entity.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("legal_name", sa.String(length=200), nullable=False),
        sa.Column("doing_business_as", sa.String(length=200)),
        # Store EIN normalized as 9 digits (no dash). Partial unique index below.
        sa.Column("ein", sa.String(length=9)),
    )
    op.create_index("ix_entity_org_legal_name", "entity_org", ["legal_name"])

    # entity_role (N:1 to entity_entity)
    op.create_table(
        "entity_role",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column(
            "entity_id",
            sa.String(length=26),
            sa.ForeignKey("entity_entity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role_code", sa.String(length=32), nullable=False),
    )
    # DB-level uniqueness to prevent duplicates even under race
    op.create_unique_constraint("ux_entity_role", "entity_role", ["entity_id", "role_code"])
    op.create_index("ix_entity_role_code", "entity_role", ["role_code"])
    op.create_index("ix_entity_role_entity", "entity_role", ["entity_id"])

    # entity_address (N:1 to entity_entity)
    op.create_table(
        "entity_address",
        sa.Column("id", sa.String(length=26), primary_key=True),
        sa.Column(
            "entity_id",
            sa.String(length=26),
            sa.ForeignKey("entity_entity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=16), nullable=False),  # 'physical'|'mailing'|'pickup'...
        sa.Column("address1", sa.String(length=120)),
        sa.Column("address2", sa.String(length=120)),
        sa.Column("city", sa.String(length=80)),
        sa.Column("state", sa.String(length=2)),
        sa.Column("postal", sa.String(length=12)),
        sa.Column("country", sa.String(length=2), server_default=sa.text("'US'"), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_entity_address_entity", "entity_address", ["entity_id"])
    op.create_index("ix_entity_address_purpose", "entity_address", ["purpose"])

    # --- Partial unique index for EIN (SQLite) ---
    # Enforce uniqueness only when ein IS NOT NULL (SQLite requires raw SQL)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_entity_org_ein_notnull "
        "ON entity_org(ein) WHERE ein IS NOT NULL"
    )


def downgrade():
    # Drop partial unique EIN index
    op.execute("DROP INDEX IF EXISTS ux_entity_org_ein_notnull")

    # Drop child tables first (respect FKs)
    op.drop_index("ix_entity_address_purpose", table_name="entity_address")
    op.drop_index("ix_entity_address_entity", table_name="entity_address")
    op.drop_table("entity_address")

    op.drop_index("ix_entity_role_entity", table_name="entity_role")
    op.drop_index("ix_entity_role_code", table_name="entity_role")
    op.drop_constraint("ux_entity_role", "entity_role", type_="unique")
    op.drop_table("entity_role")

    op.drop_index("ix_entity_org_legal_name", table_name="entity_org")
    op.drop_table("entity_org")

    op.drop_index("ix_entity_person_email", table_name="entity_person")
    op.drop_index("ix_entity_person_last_name", table_name="entity_person")
    op.drop_table("entity_person")

    op.drop_index("ix_entity_entity_kind", table_name="entity_entity")
    op.drop_table("entity_entity")
```

### How to use

1. Ensure your `migrations/env.py` configures:
   
   - `render_as_batch=True`
   
   - `target_metadata=db.metadata`
   
   - Runs inside `create_app("config.DevConfig")` app context

2. Put this file in `migrations/versions/` with a proper filename:
   
   ```
   migrations/versions/20250925_entity_core.py
   ```
   
   Replace `down_revision` with your previous revision ID.

3. Apply:
   
   ```bash
   flask db upgrade
   ```

4. Sanity:
   
   ```bash
   python manage_vcdb.py
   PYTHONPATH=. python scripts/verify_ledger_chain.py
   bash scripts/smoke_slices.sh
   ```
























