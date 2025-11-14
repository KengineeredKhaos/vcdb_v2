"""ledger immutable triggers add

Revision ID: 7d3d0d020708
Revises: 742d25a45d89
Create Date: 2025-11-12 08:39:19.183900

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7d3d0d020708'
down_revision = '742d25a45d89'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("""
        CREATE TRIGGER IF NOT EXISTS ledger_event_no_update
        BEFORE UPDATE ON ledger_event
        BEGIN
          SELECT RAISE(ABORT,'ledger_event rows are immutable');
        END;
        """)
        op.execute("""
        CREATE TRIGGER IF NOT EXISTS ledger_event_no_delete
        BEFORE DELETE ON ledger_event
        BEGIN
          SELECT RAISE(ABORT,'ledger_event rows are immutable');
        END;
        """)


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS ledger_event_no_update;")
        op.execute("DROP TRIGGER IF EXISTS ledger_event_no_delete;")
