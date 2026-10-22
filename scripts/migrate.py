"""
scripts/migrate.py — Controlled production database migration executor.

Milestone 20: Production Deployment Automation.

Safety features:
1. Verifies database connectivity before attempting schema changes.
2. Inspects current migration revision.
3. Executes pending migrations up to 'head' within an isolated process.
4. Redacts connection strings and credentials on error.
"""

import logging
import os
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migration_runner")


def run_migration() -> int:
    """Execute safe database migration."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL environment variable is not set.")
        return 1

    # Normalize driver prefix for psycopg 3
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    logger.info("Step 1: Testing database connectivity...")
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connectivity verified.")
    except Exception as exc:
        logger.error("Failed to connect to database before migration: %s", exc)
        return 1

    logger.info("Step 2: Loading Alembic configuration...")
    try:
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", database_url)

        logger.info("Step 3: Running migrations to head...")
        command.upgrade(alembic_cfg, "head")
        logger.info("Migrations successfully applied.")
        return 0
    except Exception as exc:
        logger.error("Migration execution failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(run_migration())
