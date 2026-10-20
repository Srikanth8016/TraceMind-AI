"""
app/celery_app.py — Celery application instance and configuration.

Milestone 6: Asynchronous task queue backed by Redis.

Design Decisions
----------------
1. **Config from Environment**:
   - ``CELERY_BROKER_URL``: Redis instance and DB used for message transport.
   - ``CELERY_RESULT_BACKEND``: Redis instance and DB used for task state/results.
   - ``CELERY_TASK_ALWAYS_EAGER``: Set to True in tests to execute tasks
     synchronously in-process without requiring a live Redis server.
2. **Production Reliability**:
   - ``task_acks_late = True``: Worker only acknowledges after task execution finishes.
   - ``task_reject_on_worker_lost = True``: If a worker process is killed midway,
     the task is re-queued for another worker.
   - JSON serialization is strictly enforced.
"""

import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CELERY_BROKER_URL: str = os.environ.get(
    "CELERY_BROKER_URL", "redis://localhost:6379/0"
)

CELERY_RESULT_BACKEND: str = os.environ.get(
    "CELERY_RESULT_BACKEND", "redis://localhost:6379/1"
)

CELERY_TASK_ALWAYS_EAGER: bool = os.environ.get(
    "CELERY_TASK_ALWAYS_EAGER", "False"
).lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# Celery Application
# ---------------------------------------------------------------------------

celery_app = Celery(
    "tracemind",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_always_eager=CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)
