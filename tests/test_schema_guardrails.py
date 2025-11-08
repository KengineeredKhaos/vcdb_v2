# tests/test_schema_guardrails.py
from sqlalchemy import inspect

def test_models_tables_exist(app):
    from app.extensions import db
    insp = inspect(db.engine)

    # Gather tables declared by SQLAlchemy models
    model_tables = set(db.metadata.tables.keys())
    db_tables    = set(insp.get_table_names())

    # Ignore alembic version table if present
    db_tables.discard("alembic_version")

    # Every model table must exist in the DB
    missing = sorted(model_tables - db_tables)
    assert not missing, f"Tables missing from DB (migrations out of date): {missing}"

def test_iso_timestamps_pairs_present(app):
    """Any table with created_at_utc must also have updated_at_utc."""
    from app.extensions import db
    insp = inspect(db.engine)

    for t in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns(t)}
        if "created_at_utc" in cols:
            assert "updated_at_utc" in cols, f"{t} missing updated_at_utc"
