"""Alembic environment for Envelope.

Uses the application's declarative ``Base`` metadata and database URL so that
autogenerate stays in sync with ``app/models.py``.
"""

from logging.config import fileConfig

from alembic import context

from app.db import DATABASE_URL, engine

# Importing the models module registers every table on ``Base.metadata``.
from app import models  # noqa: F401
from app.db import Base

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB connection)."""

    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # batch mode is required for ALTER on SQLite.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
