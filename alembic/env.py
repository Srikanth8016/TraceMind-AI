"""
alembic/env.py — Alembic migration environment.

Key customisations vs. the generated default
---------------------------------------------
1. ``DATABASE_URL`` is read from the environment (via python-dotenv) so that
   credentials are never baked into alembic.ini or source code.
2. We import ``Base`` from ``app.database`` and all model modules from
   ``app.models`` so that ``target_metadata`` contains every table definition.
   This enables Alembic's ``--autogenerate`` to diff the current schema against
   our ORM models automatically.
3. ``include_schemas=True`` is not needed for a single-schema setup, so we
   keep the default.
"""

import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from alembic import context

# Load .env so DATABASE_URL is available when running migrations locally.
load_dotenv()

# ---------------------------------------------------------------------------
# Alembic Config object (wraps alembic.ini)
# ---------------------------------------------------------------------------
config = context.config

# Inject the real DATABASE_URL from the environment, overriding the
# placeholder in alembic.ini.  This way alembic.ini never contains secrets.
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging if it has a [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Import all models so Base.metadata knows about every table.
# ---------------------------------------------------------------------------
# This is the critical step for autogenerate: Alembic compares
# ``target_metadata`` (our ORM definitions) against the live DB schema.

from app.database import Base   # noqa: E402  — must be after load_dotenv
import app.models               # noqa: E402, F401  — side-effect: registers all models

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Run migrations
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This generates SQL scripts without a live database connection.
    Useful for reviewing changes or applying migrations in environments
    where direct DB access is restricted.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode (the normal path).

    Creates a real SQLAlchemy engine connection and applies migrations
    inside a transaction.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # No pooling for migration runs — one-shot connection.
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
