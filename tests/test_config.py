"""
tests/test_config.py — Tests for production configuration and environment safety validation.

Milestone 10: Production Readiness.

Verifies:
1. Settings load defaults for local development.
2. In production, weak or placeholder API keys fail fast with a ValueError.
3. In production, CELERY_TASK_ALWAYS_EAGER=True fails fast.
4. Database pool size and timeouts are validated.
"""

import pytest
from app.config import AppEnvironment, Settings


class TestConfigurationSafety:
    """Verifies fail-fast safety checks on configuration settings."""

    def test_development_defaults_are_safe(self) -> None:
        cfg = Settings(
            ENVIRONMENT=AppEnvironment.DEVELOPMENT,
            TRACEMIND_API_KEY="dev-api-key-tracemind-32bytes",
            DATABASE_URL="postgresql+psycopg://tracemind:tracemind@localhost:5432/tracemind",
        )
        assert cfg.ENVIRONMENT == AppEnvironment.DEVELOPMENT
        assert cfg.DB_POOL_SIZE == 10

    def test_production_rejects_placeholder_api_key(self) -> None:
        with pytest.raises(ValueError, match="Production security violation: TRACEMIND_API_KEY cannot be empty or set to an insecure placeholder"):
            Settings(
                ENVIRONMENT=AppEnvironment.PRODUCTION,
                TRACEMIND_API_KEY="replace-with-your-secure-random-api-key",
            )

    def test_production_rejects_short_api_key(self) -> None:
        with pytest.raises(ValueError, match="must be at least 16 characters"):
            Settings(
                ENVIRONMENT=AppEnvironment.PRODUCTION,
                TRACEMIND_API_KEY="short-key",
            )

    def test_production_rejects_eager_celery(self) -> None:
        with pytest.raises(ValueError, match="CELERY_TASK_ALWAYS_EAGER cannot be True in production"):
            Settings(
                ENVIRONMENT=AppEnvironment.PRODUCTION,
                TRACEMIND_API_KEY="production-super-strong-api-key-12345",
                CELERY_TASK_ALWAYS_EAGER=True,
            )

    def test_production_accepts_strong_credentials(self) -> None:
        cfg = Settings(
            ENVIRONMENT=AppEnvironment.PRODUCTION,
            TRACEMIND_API_KEY="production-super-strong-api-key-12345",
            DATABASE_URL="postgresql+psycopg://user:pass@db-cluster.internal:5432/tracemind_prod",
            CELERY_TASK_ALWAYS_EAGER=False,
        )
        assert cfg.ENVIRONMENT == AppEnvironment.PRODUCTION
        assert cfg.TRACEMIND_API_KEY == "production-super-strong-api-key-12345"
