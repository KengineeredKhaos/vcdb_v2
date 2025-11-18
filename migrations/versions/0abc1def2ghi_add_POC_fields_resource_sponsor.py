"""add POC linkage to Resources & Sponsors (create-or-alter)

Revision ID: 0abc1def2ghi
Revises: 7d3d0d020708
Create Date: 2025-11-17 00:00:00.000000
"""
from __future__ import annotations
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0abc1def2ghi"
down_revision = "7d3d0d020708"
branch_labels = None
depends_on = None

# ---- Common column specs (SQLite friendly) ----
ULID = sa.String(length=26)
NOW = sa.text("CURRENT_TIMESTAMP")  # optional if you don’t want DB defaults

NEW_COLS = [
    sa.Column("rank", sa.Integer(), nullable=True, server_default="0"),
    sa.Column("scope", sa.String(length=24), nullable=True),
    sa.Column("org_role", sa.String(length=64), nullable=True),
    sa.Column("valid_from_utc", sa.DateTime(), nullable=True),
    sa.Column("valid_to_utc", sa.DateTime(), nullable=True),
    sa.Column(
        "is_primary",
        sa.Boolean(),
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column(
        "active", sa.Boolean(), nullable=False, server_default=sa.text("1")
    ),
]

IDX_SPECS = [
    # Fast “primary POC for scope X?”
    ("org_sc_rel_primary", ["org_ulid", "relation", "scope", "is_primary"]),
    # Ordered lists filtered by active+scope
    ("org_active_rank", ["org_ulid", "active", "relation", "scope", "rank"]),
]

# Optional uniqueness to avoid duplicate links for a scope
UNQ_NAME = "uq_{table}_org_person_rel_scope"
UNQ_COLS = ["org_ulid", "person_entity_ulid", "relation", "scope"]


def _inspector():
    bind = op.get_bind()
    return sa.inspect(bind)


def _has_table(name: str) -> bool:
    return _inspector().has_table(name)


def _get_columns(name: str) -> set[str]:
    insp = _inspector()
    if not insp.has_table(name):
        return set()
    return {c["name"] for c in insp.get_columns(name)}


def _create_poc_table(table: str):
    """Create brand new *poc table with full column set, FKs, indexes."""
    op.create_table(
        table,
        sa.Column("ulid", ULID, primary_key=True),
        # book-keeping timestamps — keep nullables to avoid DB default fights
        sa.Column("created_at_utc", sa.DateTime(), nullable=True),
        sa.Column("updated_at_utc", sa.DateTime(), nullable=True),
        # FKs to Entity slice (CASCADE org; RESTRICT person)
        sa.Column(
            "org_ulid",
            ULID,
            sa.ForeignKey("entity_org.entity_ulid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "person_entity_ulid",
            ULID,
            sa.ForeignKey("entity_person.entity_ulid", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "relation",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'poc'"),
        ),
        # POC metadata (same as NEW_COLS)
        sa.Column("rank", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("scope", sa.String(length=24), nullable=True),
        sa.Column("org_role", sa.String(length=64), nullable=True),
        sa.Column("valid_from_utc", sa.DateTime(), nullable=True),
        sa.Column("valid_to_utc", sa.DateTime(), nullable=True),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        # optional uniqueness across (org, person, relation, scope)
        sa.UniqueConstraint(*UNQ_COLS, name=UNQ_NAME.format(table=table)),
    )

    # Indexes
    for suffix, cols in IDX_SPECS:
        op.create_index(f"ix_{table}_{suffix}", table, cols, unique=False)


def _add_cols_and_indexes(table: str):
    existing_cols = _get_columns(table)

    with op.batch_alter_table(table) as b:
        # add any missing new columns (idempotent by inspection)
        for col in NEW_COLS:
            if col.name not in existing_cols:
                b.add_column(col.copy())

        # ensure relation column exists and has sensible default
        if "relation" not in existing_cols:
            b.add_column(
                sa.Column(
                    "relation",
                    sa.String(length=16),
                    nullable=False,
                    server_default=sa.text("'poc'"),
                )
            )

        # add optional uniqueness if not already present
        # (SQLite reports constraints via PRAGMA; Alembic inspector can be sparse.
        # If you prefer, skip this and let the service enforce uniqueness.)
        # b.create_unique_constraint(UNQ_NAME.format(table=table), UNQ_COLS)

    # indexes (safe to attempt create; but we avoid duplicates by naming convention)
    for suffix, cols in IDX_SPECS:
        op.create_index(f"ix_{table}_{suffix}", table, cols, unique=False)


def _drop_cols_and_indexes(table: str):
    # Drop indexes first
    for suffix, _cols in IDX_SPECS:
        op.drop_index(f"ix_{table}_{suffix}", table_name=table)

    cols = _get_columns(table)
    # Then drop columns we added (only if present)
    with op.batch_alter_table(table) as b:
        for name in [
            "active",
            "is_primary",
            "valid_to_utc",
            "valid_from_utc",
            "org_role",
            "scope",
            "rank",
        ]:
            if name in cols:
                b.drop_column(name)
        if "relation" in cols:
            b.drop_column("relation")


def _drop_table(table: str):
    op.drop_table(table)


def upgrade():
    for table in ("resource_poc", "sponsor_poc"):
        if not _has_table(table):
            _create_poc_table(table)
        else:
            _add_cols_and_indexes(table)


def downgrade():
    # If we created the table here, drop it; otherwise, revert added cols/indexes.
    for table in ("sponsor_poc", "resource_poc"):
        if not _has_table(table):
            continue
        cols = _get_columns(table)
        # Heuristic: if table has *only* legacy columns, we didn’t create it.
        # If it has the full POC set (incl. relation/rank/scope/is_primary/active), we can drop the table.
        poc_markers = {"relation", "rank", "scope", "is_primary", "active"}
        if poc_markers.issubset(cols) and "ulid" in cols:
            _drop_table(table)
        else:
            _drop_cols_and_indexes(table)
