"""EIN partial unique index

Revision ID: ce437fd10a7f
Revises: 79eef5608998
Create Date: 2025-09-25 22:17:20.683294

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "ce437fd10a7f"
down_revision = "79eef5608998"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_entity_org_ein_notnull ON entity_org(ein) WHERE ein IS NOT NULL"
    )


def downgrade():
    pass
