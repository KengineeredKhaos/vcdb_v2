# migrations/env.py
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from flask import current_app
from sqlalchemy import engine_from_config, pool

# --- Alembic Config ---
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Hand metadata to Alembic (via Flask-Migrate's db) ---
target_metadata = current_app.extensions[
    "migrate"
].db.metadata  # MetaData object


# (Optional) control what autogenerate includes
def include_object(obj, name, type_, reflected, compare_to):
    # For a fresh rebuild, include everything:
    return True
    # If you want to scope to new tables only, use:
    # return type_ != "table" or name == "alembic_version" or name.startswith("entity_")


# --- Offline mode ---
def run_migrations_offline():
    url = str(current_app.config["SQLALCHEMY_DATABASE_URI"])
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        render_as_batch=True,  # SQLite-friendly
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# --- Online mode ---
def run_migrations_online():
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = str(
        current_app.config["SQLALCHEMY_DATABASE_URI"]
    )

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",  # NOTE: dot, not percent sign
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            render_as_batch=True,  # SQLite-friendly
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


# --- Entrypoint ---
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
