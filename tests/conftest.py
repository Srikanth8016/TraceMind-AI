"""
tests/conftest.py — Shared pytest fixtures for Milestone 3.

Testing strategy
----------------
We override FastAPI's ``get_db`` dependency with a version that uses an
**in-process SQLite database** (SQLite is part of Python's stdlib — no
external server required).

Why SQLite for tests?
    - No PostgreSQL server needed → tests run anywhere (CI, dev laptop, Docker)
    - Faster than spinning up a real DB per test
    - SQLAlchemy's ORM is largely dialect-agnostic for basic CRUD

Caveats
    - SQLite does not have gen_random_uuid() so we generate the UUID in Python
      (see app/routers/events.py — id=uuid.uuid4() is set there before INSERT).
    - PostgreSQL-specific UUID column type falls back to TEXT in SQLite
      automatically via SQLAlchemy.
    - created_at uses a Python-side default=func.now() in the model so SQLite
      also populates it automatically.

If you have a real PostgreSQL and want to run tests against it:
    Set TEST_DATABASE_URL in .env and point SQLITE_URL to it below.
"""

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.user import User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Test database — in-memory SQLite
# ---------------------------------------------------------------------------

import sqlite3
sqlite3.register_adapter(uuid.UUID, lambda u: str(u))

SQLITE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    SQLITE_URL,
    connect_args={"check_same_thread": False},
    # StaticPool ensures the same in-memory database is shared across all
    # connections within the test process (important for TestClient's thread).
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

DEFAULT_TEST_USER_ID = uuid.UUID("a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")
DEFAULT_TEST_USER_EMAIL = "testuser@example.com"
DEFAULT_AUTH_TOKEN = create_access_token(data={"sub": str(DEFAULT_TEST_USER_ID), "email": DEFAULT_TEST_USER_EMAIL})

# ---------------------------------------------------------------------------
# Table setup — once per test SESSION
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def create_test_tables():
    """
    Create all ORM-defined tables in the in-memory SQLite DB once.

    ``Base.metadata.create_all()`` is acceptable here because this is a
    *throwaway* test DB, not production schema management.
    """
    Base.metadata.create_all(bind=test_engine)
    with TestingSessionLocal() as session:
        user = session.get(User, DEFAULT_TEST_USER_ID)
        if not user:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            user = User(
                id=DEFAULT_TEST_USER_ID,
                email=DEFAULT_TEST_USER_EMAIL,
                hashed_password=hash_password("TestPassword123!"),
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            session.commit()
    yield
    Base.metadata.drop_all(bind=test_engine)


# ---------------------------------------------------------------------------
# Dependency override — replaces ``get_db`` for ALL tests
# ---------------------------------------------------------------------------

def override_get_db() -> Generator[Session, None, None]:
    """Replacement for app.database.get_db used during tests."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Register the override globally so it is active for every test module.
app.dependency_overrides[get_db] = override_get_db


# ---------------------------------------------------------------------------
# Authentication test configuration (Milestone 5 & 14)
# ---------------------------------------------------------------------------

TEST_API_KEY = "test-secret-key-12345"
import os
os.environ["TRACEMIND_API_KEY"] = TEST_API_KEY
os.environ["LLM_PROVIDER"] = "mock"
os.environ["EMBEDDING_PROVIDER"] = "mock"
os.environ["ENVIRONMENT"] = "testing"

# ---------------------------------------------------------------------------
# Celery eager mode & SessionLocal binding for worker tasks (Milestone 6)
# ---------------------------------------------------------------------------
# Configure SessionLocal to use test_engine so background tasks execute
# against the in-memory SQLite database during tests without touching PostgreSQL.
from app.database import SessionLocal
SessionLocal.configure(bind=test_engine)

from app.celery_app import celery_app
celery_app.conf.update(
    task_always_eager=True,
    task_eager_propagates=True,
)



# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    """
    HTTP test client backed by the SQLite override and authenticated
    with the default test API key header (X-API-Key) and Bearer token.

    ``scope="module"`` — one client per test file. Data written by one
    test is visible to subsequent tests in the same module.
    """
    headers = {
        "X-API-Key": TEST_API_KEY,
        "Authorization": f"Bearer {DEFAULT_AUTH_TOKEN}",
    }
    with TestClient(app, headers=headers) as c:
        yield c


@pytest.fixture
def unauthenticated_client() -> Generator[TestClient, None, None]:
    """
    HTTP test client without any authentication headers.

    Used by auth tests to verify missing-header and custom-header behavior.
    """
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

VALID_PAYLOAD: dict = {
    "service_name": "payment-service",
    "environment": "production",
    "level": "ERROR",
    "message": "NullPointerException in PaymentProcessor.charge()",
    "timestamp": "2024-06-15T14:30:00+00:00",
}
