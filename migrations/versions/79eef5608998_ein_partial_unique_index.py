"""EIN partial unique index

Revision ID: 79eef5608998
Revises: 0735607b935c
Create Date: 2025-09-25 20:02:13.149302

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "79eef5608998"
down_revision = "0735607b935c"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_entity_org_ein_notnull ON entity_org(ein) WHERE ein IS NOT NULL"
    )


def downgrade():
    pass
