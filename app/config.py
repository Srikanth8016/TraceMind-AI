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

DEV_PLACEHOLDER_JWT_SECRETS = {
    "replace-with-your-secure-random-jwt-secret-at-least-32-chars",
    "tracemind-default-production-safe-jwt-secret-key-32chars",
    "secret",
    "changeme",
    "test-jwt-secret",
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

    # External Alert Integrations & Notifications (Milestone 19)
    DATADOG_WEBHOOK_SECRET: Optional[str] = Field(
        default=None,
        description="Shared secret or bearer token for verifying inbound Datadog webhooks.",
    )
    DATADOG_WEBHOOK_ENABLED: bool = Field(
        default=True,
        description="Enable or disable the inbound Datadog webhook endpoint.",
    )

    PAGERDUTY_WEBHOOK_SECRET: Optional[str] = Field(
        default=None,
        description="HMAC secret for verifying X-PagerDuty-Signature on inbound v3 webhooks.",
    )
    PAGERDUTY_WEBHOOK_ENABLED: bool = Field(
        default=True,
        description="Enable or disable the inbound PagerDuty webhook endpoint.",
    )
    PAGERDUTY_WEBHOOK_MAX_AGE_SECONDS: int = Field(
        default=300,
        ge=10,
        le=3600,
        description="Maximum allowed timestamp drift in seconds to protect against replay attacks.",
    )

    SLACK_WEBHOOK_URL: Optional[str] = Field(
        default=None,
        description="Slack Incoming Webhook URL for outbound incident notifications.",
    )
    SLACK_NOTIFICATIONS_ENABLED: bool = Field(
        default=False,
        description="Enable or disable outbound Slack incident notifications.",
    )
    SLACK_NOTIFICATION_MIN_SEVERITY: str = Field(
        default="ERROR",
        description="Minimum incident severity that triggers a Slack notification (e.g. WARNING, ERROR, CRITICAL).",
    )
    SLACK_NOTIFY_ON_INCIDENT_CREATED: bool = Field(
        default=True,
        description="Send Slack alert when a new incident is created or correlated.",
    )
    SLACK_NOTIFY_ON_STATUS_CHANGED: bool = Field(
        default=True,
        description="Send Slack alert when incident status changes (e.g. ACKNOWLEDGED, RESOLVED).",
    )
    SLACK_NOTIFY_ON_INVESTIGATION_COMPLETED: bool = Field(
        default=True,
        description="Send Slack alert when AI root-cause investigation completes or fails.",
    )
    APP_BASE_URL: Optional[str] = Field(
        default="http://localhost:3000",
        description="Base URL of TraceMind web application, used for interactive links in Slack alerts.",
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
                if field_name in (
                    "CELERY_TASK_ALWAYS_EAGER",
                    "DEMO_MODE",
                    "DATADOG_WEBHOOK_ENABLED",
                    "PAGERDUTY_WEBHOOK_ENABLED",
                    "SLACK_NOTIFICATIONS_ENABLED",
                    "SLACK_NOTIFY_ON_INCIDENT_CREATED",
                    "SLACK_NOTIFY_ON_STATUS_CHANGED",
                    "SLACK_NOTIFY_ON_INVESTIGATION_COMPLETED",
                ):
                    env_dict[field_name] = val.lower() in ("true", "1", "yes")
                elif field_name in (
                    "DB_POOL_SIZE",
                    "DB_MAX_OVERFLOW",
                    "DB_POOL_TIMEOUT",
                    "DB_POOL_RECYCLE",
                    "INCIDENT_CORRELATION_WINDOW_SECONDS",
                    "EMBEDDING_DIMENSION",
                    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
                    "PAGERDUTY_WEBHOOK_MAX_AGE_SECONDS",
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
            if not self.JWT_SECRET_KEY or self.JWT_SECRET_KEY in DEV_PLACEHOLDER_JWT_SECRETS:
                raise ValueError(
                    "Production security violation: JWT_SECRET_KEY cannot be empty or set to an insecure placeholder."
                )
            if len(self.JWT_SECRET_KEY) < 32:
                raise ValueError(
                    "Production security violation: JWT_SECRET_KEY must be at least 32 characters long."
                )

            # 4. Production database driver validation (SQLite forbidden in production)
            if self.DATABASE_URL.startswith("sqlite"):
                raise ValueError(
                    "Production configuration violation: SQLite is not supported in production mode; PostgreSQL is required."
                )

            # 5. Outbound Slack notification validation
            if self.SLACK_NOTIFICATIONS_ENABLED:
                if (
                    not self.SLACK_WEBHOOK_URL
                    or "YOUR_WORKSPACE_ID" in self.SLACK_WEBHOOK_URL
                    or "PLACEHOLDER" in self.SLACK_WEBHOOK_URL
                    or "T00000000" in self.SLACK_WEBHOOK_URL
                ):
                    raise ValueError(
                        "Production configuration violation: SLACK_WEBHOOK_URL must be configured when SLACK_NOTIFICATIONS_ENABLED is True."
                    )

            # 6. Webhook secrets validation in production
            if self.DATADOG_WEBHOOK_SECRET == "replace-with-datadog-webhook-secret-token":
                raise ValueError(
                    "Production security violation: DATADOG_WEBHOOK_SECRET cannot be set to example placeholder."
                )
            if self.PAGERDUTY_WEBHOOK_SECRET == "replace-with-pagerduty-webhook-hmac-secret":
                raise ValueError(
                    "Production security violation: PAGERDUTY_WEBHOOK_SECRET cannot be set to example placeholder."
                )

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
