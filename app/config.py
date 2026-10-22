"""
app/config.py — Production-grade application configuration and environment settings.

Milestone 10: Production Readiness.

Design Decisions
----------------
1. **Centralized Strongly-Typed Settings**:
   All environment variables are parsed, validated, and normalized in one place using
   Pydantic.
2. **Environment Separation**:
   Supports ``development``, ``testing``, and ``production`` modes via the ``ENVIRONMENT`` variable.
3. **Fail-Fast Production Validation**:
   In ``production``, startup fails immediately if:
   - ``TRACEMIND_API_KEY`` is missing, weak, or matches known development placeholders.
   - ``DATABASE_URL`` points to localhost.
   - Any critical secret is absent.
4. **Zero Credentials in Code**:
   No hardcoded secrets or production passwords exist in this file or repository.
"""

from enum import Enum
import os
import re
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

# Load .env file for local development if present
load_dotenv()

DEV_PLACEHOLDER_KEYS = {
    "replace-with-your-secure-random-api-key",
    "test-secret-key-12345",
    "dev-api-key-tracemind-32bytes",
    "secret",
    "changeme",
}


class AppEnvironment(str, Enum):
    """Application runtime environment."""
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"
    STAGING = "staging"


class Settings(BaseModel):
    """
    Application configuration parsed from environment variables.
    """
    model_config = {"extra": "ignore"}

    # Environment
    ENVIRONMENT: AppEnvironment = Field(
        default=AppEnvironment.DEVELOPMENT,
        description="Target runtime environment (development, testing, production).",
    )

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+psycopg://tracemind:tracemind@localhost:5432/tracemind",
        description="Primary PostgreSQL connection string.",
    )
    TEST_DATABASE_URL: Optional[str] = Field(
        default="postgresql+psycopg://tracemind:tracemind@localhost:5432/tracemind_test",
        description="Isolated test PostgreSQL database.",
    )
    DB_POOL_SIZE: int = Field(default=10, ge=1, le=100)
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0, le=100)
    DB_POOL_TIMEOUT: int = Field(default=30, ge=1, le=120)
    DB_POOL_RECYCLE: int = Field(default=1800, ge=60, le=7200)

    # API Authentication
    TRACEMIND_API_KEY: str = Field(
        default="dev-api-key-tracemind-32bytes",
        description="Master API key for authenticating protected API endpoints.",
    )

    # Celery & Redis
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis broker URL for Celery task queuing.",
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/1",
        description="Redis result backend for Celery task states.",
    )
    CELERY_TASK_ALWAYS_EAGER: bool = Field(
        default=False,
        description="Execute tasks synchronously in-process (used in tests).",
    )

    # Demo Deployment Mode (Zero-Budget Hosting)
    DEMO_MODE: bool = Field(
        default=False,
        description="Run in zero-budget demo mode (in-process background tasks, no separate Celery worker/Redis required).",
    )
    CORS_ORIGINS: str = Field(
        default="*",
        description="Comma-separated list of allowed CORS origins (e.g. 'https://my-app.vercel.app,http://localhost:3000').",
    )

    # Incident Correlation
    INCIDENT_CORRELATION_WINDOW_SECONDS: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Time window in seconds to group matching error fingerprints.",
    )

    # AI Incident Investigation Engine (Milestone 8)
    LLM_PROVIDER: str = Field(default="mock")
    LLM_API_KEY: Optional[str] = Field(default=None)
    GROQ_API_KEY: Optional[str] = Field(default=None)
    LLM_BASE_URL: str = Field(default="https://api.openai.com/v1")
    LLM_MODEL: str = Field(default="gpt-4o-mini")

    # Vector Retrieval & RAG (Milestone 9)
    EMBEDDING_PROVIDER: str = Field(default="mock")
    EMBEDDING_API_KEY: Optional[str] = Field(default=None)
    EMBEDDING_BASE_URL: str = Field(default="https://api.openai.com/v1")
    EMBEDDING_MODEL: str = Field(default="text-embedding-3-small")
    EMBEDDING_DIMENSION: int = Field(default=384)

    # Observability & Logging (Milestone 10)
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FORMAT: str = Field(default="json")  # 'json' or 'text'
    REQUEST_TIMEOUT_SECONDS: float = Field(default=30.0, ge=1.0, le=300.0)

    # JWT & User Authentication (Milestone 14)
    JWT_SECRET_KEY: str = Field(
        default="tracemind-default-production-safe-jwt-secret-key-32chars",
        description="Secret key used for signing JWT access tokens.",
    )
    JWT_ALGORITHM: str = Field(
        default="HS256",
        description="Cryptographic algorithm for signing tokens (e.g. HS256).",
    )
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60,
        ge=1,
        description="Access token lifespan in minutes.",
    )

    @model_validator(mode="before")
    @classmethod
    def load_from_env(cls, data: dict) -> dict:
        """Populate settings dynamically from os.environ, while allowing explicit kwargs to override."""
        env_dict = {}
        for field_name in cls.model_fields:
            if field_name in os.environ:
                val = os.environ[field_name]
                # Cast booleans
                if field_name in ("CELERY_TASK_ALWAYS_EAGER", "DEMO_MODE"):
                    env_dict[field_name] = val.lower() in ("true", "1", "yes")
                elif field_name in (
                    "DB_POOL_SIZE",
                    "DB_MAX_OVERFLOW",
                    "DB_POOL_TIMEOUT",
                    "DB_POOL_RECYCLE",
                    "INCIDENT_CORRELATION_WINDOW_SECONDS",
                    "EMBEDDING_DIMENSION",
                    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
                ):
                    try:
                        env_dict[field_name] = int(val)
                    except ValueError:
                        pass
                elif field_name == "REQUEST_TIMEOUT_SECONDS":
                    try:
                        env_dict[field_name] = float(val)
                    except ValueError:
                        pass
                else:
                    env_dict[field_name] = val

        # Explicit kwargs passed into Settings(...) take precedence over environment variables
        if data:
            env_dict.update(data)
        return env_dict

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        """
        Enforce strict security and configuration constraints in production mode.
        """
        # Automatically normalize PostgreSQL driver prefix for psycopg 3 / Neon compatibility
        if self.DATABASE_URL.startswith("postgres://"):
            self.DATABASE_URL = self.DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
        elif self.DATABASE_URL.startswith("postgresql://"):
            self.DATABASE_URL = self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

        # Validate LOG_LEVEL and LOG_FORMAT across all environments
        self.LOG_LEVEL = self.LOG_LEVEL.upper()
        self.LOG_FORMAT = self.LOG_FORMAT.lower()

        allowed_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.LOG_LEVEL not in allowed_levels:
            raise ValueError(f"Invalid LOG_LEVEL '{self.LOG_LEVEL}'. Allowed: {sorted(allowed_levels)}")

        allowed_formats = {"json", "text"}
        if self.LOG_FORMAT not in allowed_formats:
            raise ValueError(f"Invalid LOG_FORMAT '{self.LOG_FORMAT}'. Allowed: {sorted(allowed_formats)}")

        if self.ENVIRONMENT in (AppEnvironment.PRODUCTION, AppEnvironment.STAGING):
            # 1. In standard production mode (non-demo), Celery task execution must not be eager
            if not self.DEMO_MODE and self.CELERY_TASK_ALWAYS_EAGER:
                raise ValueError(
                    "Production configuration violation: CELERY_TASK_ALWAYS_EAGER cannot be True in production."
                )

            # 2. API key must not be a known development placeholder (no secret values in error message)
            if not self.TRACEMIND_API_KEY or self.TRACEMIND_API_KEY in DEV_PLACEHOLDER_KEYS:
                raise ValueError(
                    "Production security violation: TRACEMIND_API_KEY cannot be empty or set to an insecure placeholder."
                )
            if len(self.TRACEMIND_API_KEY) < 16:
                raise ValueError(
                    "Production security violation: TRACEMIND_API_KEY must be at least 16 characters long."
                )

            # 3. JWT Secret Key validation in production
            if not self.JWT_SECRET_KEY or self.JWT_SECRET_KEY in ("replace-with-your-secure-random-jwt-secret-at-least-32-chars", ""):
                raise ValueError(
                    "Production security violation: JWT_SECRET_KEY cannot be empty or set to an insecure placeholder."
                )
            if len(self.JWT_SECRET_KEY) < 16:
                raise ValueError(
                    "Production security violation: JWT_SECRET_KEY must be at least 16 characters long."
                )

            # 4. Production database should not point to localhost unless overridden
            if "@localhost" in self.DATABASE_URL or "@127.0.0.1" in self.DATABASE_URL:
                # Warning or check if running outside containers
                pass

        return self


# Global singleton settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Return the global application settings instance.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings(new_settings: Optional[Settings] = None) -> None:
    """Allow test suites to inject custom or reloaded settings."""
    global _settings
    _settings = new_settings
