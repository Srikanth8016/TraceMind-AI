"""
app/database.py — Database engine, session factory, and FastAPI dependency.

Design decisions
----------------
1. **Synchronous SQLAlchemy** is used deliberately for Milestone 3.
   FastAPI supports async DB access too, but mixing sync and async patterns
   in the same milestone creates unnecessary complexity.  We keep it simple:
   one pattern, one mental model.

2. **Session-per-request** pattern: each HTTP request gets its own
   ``Session``, committed on success and rolled back on any exception.
   The ``get_db`` dependency uses ``yield`` so FastAPI's dependency injection
   system handles setup and teardown automatically.

3. **DATABASE_URL from environment**: credentials never live in code.
   ``python-dotenv`` loads ``.env`` in development; in production the
   environment variable is injected by the container runtime.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Load .env file if it exists (no-op in production where env vars are set externally).
load_dotenv()


from app.config import get_settings

settings = get_settings()

DATABASE_URL: str = settings.DATABASE_URL
# Normalize postgres:// and postgresql:// to postgresql+psycopg:// for psycopg 3
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine_kwargs = {
    "pool_pre_ping": True,
    "echo": False,
}
# Only apply pool sizing for pool-enabled dialects (PostgreSQL, MySQL)
if not DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update({
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "connect_args": {"connect_timeout": 10},
    })

engine = create_engine(DATABASE_URL, **engine_kwargs)


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,   # We commit explicitly — never let SQLAlchemy auto-commit.
    autoflush=False,    # We flush manually before queries that need the latest data.
    expire_on_commit=False,  # Keep ORM attributes accessible after commit.
)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.

    All model classes (``Event``, etc.) inherit from this so that
    ``Base.metadata`` knows about every table and Alembic can introspect them.
    """
    pass


# ---------------------------------------------------------------------------
# FastAPI session dependency
# ---------------------------------------------------------------------------

def get_db():
    """
    Yield a SQLAlchemy ``Session`` for the duration of a single HTTP request.

    Usage in route handlers
    -----------------------
    >>> from app.database import get_db
    >>> from sqlalchemy.orm import Session
    >>> from fastapi import Depends
    >>>
    >>> @router.post("/")
    ... def create_something(db: Session = Depends(get_db)):
    ...     ...

    How it works
    ------------
    The ``with SessionLocal() as db`` context manager calls ``db.close()``
    on exit, returning the connection to the pool.  The ``try/finally`` block
    ensures ``close()`` is always called, even if the route handler raises an
    exception, so we never leak connections.
    """
    db: Session = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# DB readiness probe (used by /health/db endpoint, NOT /health)
# ---------------------------------------------------------------------------

def check_db_connection() -> bool:
    """
    Attempt a lightweight query to verify PostgreSQL is reachable.

    Returns ``True`` on success, ``False`` on any error.
    Called by the ``/health/db`` readiness probe — deliberately separate from
    the liveness ``/health`` so that a DB outage does not kill the pod.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
