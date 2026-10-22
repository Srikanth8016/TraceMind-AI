"""
tests/test_deployment.py — Automated test suite for Milestone 20 deployment automation.

Covers:
1. Production safety configuration validation (fail-fast on insecure keys, default secrets, SQLite).
2. Health and readiness probe behavior under production constraints.
3. Alembic migration chain validation (valid linear ancestry, no broken heads).
4. CI/CD workflow syntax and configuration structure validation (.github/workflows/ci.yml and deploy.yml).
5. Docker Compose and Render Blueprint specification validation.
6. Secret redaction under deployment logging formats.
"""

from pathlib import Path
import re
import pytest
import yaml
from fastapi.testclient import TestClient

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.config import AppEnvironment, Settings, get_settings
from app.logging_config import redact_sensitive_text
from app.main import app

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def client():
    return TestClient(app)


# ===========================================================================
# 1. Production Safety & Configuration Validation Tests
# ===========================================================================

class TestProductionConfigurationValidation:
    """Tests 1-6: Enforce fail-fast security constraints in production."""

    def test_01_production_mode_rejects_insecure_default_api_key(self):
        with pytest.raises(ValueError, match="Production security violation: TRACEMIND_API_KEY"):
            Settings(
                ENVIRONMENT=AppEnvironment.PRODUCTION,
                DEMO_MODE=False,
                CELERY_TASK_ALWAYS_EAGER=False,
                TRACEMIND_API_KEY="dev-api-key-tracemind-32bytes",
                JWT_SECRET_KEY="a-very-strong-production-jwt-secret-key-at-least-32chars",
                DATABASE_URL="postgresql+psycopg://user:pass@db.prod.internal:5432/tracemind",
            )

    def test_02_production_mode_rejects_short_api_key(self):
        with pytest.raises(ValueError, match="at least 16 characters long"):
            Settings(
                ENVIRONMENT=AppEnvironment.PRODUCTION,
                DEMO_MODE=False,
                CELERY_TASK_ALWAYS_EAGER=False,
                TRACEMIND_API_KEY="short-key",
                JWT_SECRET_KEY="a-very-strong-production-jwt-secret-key-at-least-32chars",
                DATABASE_URL="postgresql+psycopg://user:pass@db.prod.internal:5432/tracemind",
            )

    def test_03_production_mode_rejects_insecure_default_jwt_secret(self):
        with pytest.raises(ValueError, match="Production security violation: JWT_SECRET_KEY"):
            Settings(
                ENVIRONMENT=AppEnvironment.PRODUCTION,
                DEMO_MODE=False,
                CELERY_TASK_ALWAYS_EAGER=False,
                TRACEMIND_API_KEY="a-strong-custom-production-api-key-12345",
                JWT_SECRET_KEY="tracemind-default-production-safe-jwt-secret-key-32chars",
                DATABASE_URL="postgresql+psycopg://user:pass@db.prod.internal:5432/tracemind",
            )

    def test_04_production_mode_rejects_sqlite_database(self):
        with pytest.raises(ValueError, match="SQLite is not supported in production mode"):
            Settings(
                ENVIRONMENT=AppEnvironment.PRODUCTION,
                DEMO_MODE=False,
                CELERY_TASK_ALWAYS_EAGER=False,
                TRACEMIND_API_KEY="a-strong-custom-production-api-key-12345",
                JWT_SECRET_KEY="a-very-strong-production-jwt-secret-key-at-least-32chars",
                DATABASE_URL="sqlite:///production.db",
            )

    def test_05_production_mode_rejects_eager_celery_when_not_demo(self):
        with pytest.raises(ValueError, match="CELERY_TASK_ALWAYS_EAGER cannot be True in production"):
            Settings(
                ENVIRONMENT=AppEnvironment.PRODUCTION,
                DEMO_MODE=False,
                CELERY_TASK_ALWAYS_EAGER=True,
                TRACEMIND_API_KEY="a-strong-custom-production-api-key-12345",
                JWT_SECRET_KEY="a-very-strong-production-jwt-secret-key-at-least-32chars",
                DATABASE_URL="postgresql+psycopg://user:pass@db.prod.internal:5432/tracemind",
            )

    def test_06_production_mode_validates_slack_webhook_url_when_enabled(self):
        with pytest.raises(ValueError, match="SLACK_WEBHOOK_URL must be configured"):
            Settings(
                ENVIRONMENT=AppEnvironment.PRODUCTION,
                DEMO_MODE=False,
                CELERY_TASK_ALWAYS_EAGER=False,
                SLACK_NOTIFICATIONS_ENABLED=True,
                SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR_WORKSPACE_ID/YOUR_CHANNEL_ID/YOUR_SECRET_TOKEN",
                TRACEMIND_API_KEY="a-strong-custom-production-api-key-12345",
                JWT_SECRET_KEY="a-very-strong-production-jwt-secret-key-at-least-32chars",
                DATABASE_URL="postgresql+psycopg://user:pass@db.prod.internal:5432/tracemind",
            )

    def test_07_valid_production_settings_pass(self):
        settings = Settings(
            ENVIRONMENT=AppEnvironment.PRODUCTION,
            DEMO_MODE=False,
            CELERY_TASK_ALWAYS_EAGER=False,
            TRACEMIND_API_KEY="a-strong-custom-production-api-key-12345",
            JWT_SECRET_KEY="a-very-strong-production-jwt-secret-key-at-least-32chars",
            DATABASE_URL="postgresql+psycopg://user:pass@db.prod.internal:5432/tracemind",
            LOG_LEVEL="INFO",
            LOG_FORMAT="json",
        )
        assert settings.ENVIRONMENT == AppEnvironment.PRODUCTION
        assert settings.LOG_FORMAT == "json"


# ===========================================================================
# 2. Container Health & Readiness Probes
# ===========================================================================

class TestContainerHealthProbes:
    """Tests 8-9: Verify liveness and readiness probes behavior."""

    def test_08_liveness_probe_returns_200(self, client: TestClient):
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ("healthy", "ok")
        assert "service" in data or "version" in data

    def test_09_readiness_probe_returns_status(self, client: TestClient):
        res = client.get("/ready")
        assert res.status_code in (200, 503)
        data = res.json()
        assert "database" in data


# ===========================================================================
# 3. Alembic Migration Chain Validation
# ===========================================================================

class TestMigrationChainIntegrity:
    """Tests 10-11: Validate Alembic migration history and dependencies."""

    def test_10_migration_ancestry_is_unbroken(self):
        alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
        script = ScriptDirectory.from_config(alembic_cfg)

        heads = script.get_heads()
        # Exactly one unified head revision must exist
        assert len(heads) == 1, f"Multiple migration heads detected: {heads}"
        head_rev = heads[0]
        assert head_rev == "0008_integrations_notifications"

    def test_11_all_versions_have_valid_down_revisions(self):
        alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
        script = ScriptDirectory.from_config(alembic_cfg)

        # Walk entire revision chain from head to base
        revisions = list(script.walk_revisions())
        assert len(revisions) == 8, f"Expected 8 revisions, found {len(revisions)}"

        rev_ids = {r.revision for r in revisions}
        for rev in revisions:
            if rev.down_revision is not None:
                assert rev.down_revision in rev_ids, (
                    f"Revision {rev.revision} references non-existent down_revision {rev.down_revision}"
                )


# ===========================================================================
# 4. CI/CD & Deployment Configuration Validation
# ===========================================================================

class TestDeploymentConfigurations:
    """Tests 12-15: Validate Docker Compose, Render Blueprint, and CI/CD workflow syntax."""

    def test_12_docker_compose_valid_structure(self):
        compose_file = REPO_ROOT / "docker-compose.yml"
        assert compose_file.exists(), "docker-compose.yml not found"

        with open(compose_file, "r", encoding="utf-8") as f:
            compose = yaml.safe_load(f)

        services = compose.get("services", {})
        assert "db" in services
        assert "redis" in services
        assert "migration" in services
        assert "api" in services
        assert "worker" in services

        # Migration service must run alembic upgrade head
        assert "alembic" in " ".join(services["migration"]["command"])

        # API must depend on migration completion
        api_depends = services["api"]["depends_on"]
        assert "migration" in api_depends

    def test_13_render_blueprint_valid_structure(self):
        render_file = REPO_ROOT / "render.yaml"
        assert render_file.exists(), "render.yaml not found"

        with open(render_file, "r", encoding="utf-8") as f:
            blueprint = yaml.safe_load(f)

        services = blueprint.get("services", [])
        assert len(services) >= 1
        web_svc = services[0]
        assert web_svc["type"] == "web"
        assert web_svc["healthCheckPath"] == "/health"

        env_keys = {e["key"] for e in web_svc.get("envVars", [])}
        assert "DATABASE_URL" in env_keys
        assert "TRACEMIND_API_KEY" in env_keys
        assert "JWT_SECRET_KEY" in env_keys

    def test_14_github_actions_ci_workflow_valid_structure(self):
        ci_file = REPO_ROOT / ".github" / "workflows" / "ci.yml"
        assert ci_file.exists(), ".github/workflows/ci.yml not found"

        with open(ci_file, "r", encoding="utf-8") as f:
            ci = yaml.safe_load(f)

        jobs = ci.get("jobs", {})
        assert "backend-tests" in jobs
        assert "frontend-build" in jobs
        assert "docker-build" in jobs

    def test_15_github_actions_deploy_workflow_valid_structure(self):
        deploy_file = REPO_ROOT / ".github" / "workflows" / "deploy.yml"
        assert deploy_file.exists(), ".github/workflows/deploy.yml not found"

        with open(deploy_file, "r", encoding="utf-8") as f:
            deploy = yaml.safe_load(f)

        jobs = deploy.get("jobs", {})
        assert "pre-deploy-validation" in jobs
        assert "deploy-and-migrate" in jobs


# ===========================================================================
# 5. Secret Redaction & Logging Safeguards
# ===========================================================================

class TestSecretRedactionSafeguards:
    """Tests 16-17: Ensure secrets never leak in deployment logs."""

    def test_16_redacts_credentials_in_logs(self):
        raw = "Error connecting to postgresql+psycopg://tracemind:superSecret123@prod-db.internal:5432/tracemind"
        clean = redact_sensitive_text(raw)
        assert "superSecret123" not in clean
        assert "***@" in clean

    def test_17_redacts_slack_and_jwt_secrets(self):
        raw = "Sending to https://hooks.slack.com/services/T_EXAMPLE/B_EXAMPLE/mock_token with Bearer mySecretToken12345"
        clean = redact_sensitive_text(raw)
        assert "mock_token" not in clean
        assert "[REDACTED_SLACK_WEBHOOK]" in clean
        assert "[REDACTED_TOKEN]" in clean
