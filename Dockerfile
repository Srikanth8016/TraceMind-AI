# ---------------------------------------------------------------------------
# TraceMind AI — Production Dockerfile
#
# Multi-purpose image for running both the FastAPI web service and Celery worker.
# Follows security best practices:
# - Minimal Debian-slim base image
# - Reproducible dependency installation
# - Runs as an unprivileged non-root user (uid: 10001)
# - No secrets baked into image layers
# ---------------------------------------------------------------------------

FROM python:3.12-slim

# Prevent Python from writing .pyc bytecode and force unbuffered standard I/O
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/app/.local/bin:$PATH"

WORKDIR /app

# Install minimal OS dependencies for network health checks and building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user and group
RUN groupadd -r -g 10001 tracemind && \
    useradd -r -u 10001 -g tracemind -m -d /app tracemind

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code and Alembic migrations with non-root ownership
COPY --chown=tracemind:tracemind alembic/ /app/alembic/
COPY --chown=tracemind:tracemind alembic.ini /app/
COPY --chown=tracemind:tracemind app/ /app/app/
COPY --chown=tracemind:tracemind scripts/ /app/scripts/

# Switch to unprivileged user
USER tracemind

# Expose web service port
EXPOSE 8000

# Container liveness health check
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command: start Uvicorn web server
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
