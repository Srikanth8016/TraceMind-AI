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

import logging
import os
from celery import Celery
import redis
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

CELERY_BROKER_URL: str = settings.CELERY_BROKER_URL
CELERY_RESULT_BACKEND: str = settings.CELERY_RESULT_BACKEND
CELERY_TASK_ALWAYS_EAGER: bool = settings.CELERY_TASK_ALWAYS_EAGER

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
    worker_prefetch_multiplier=1,
    task_time_limit=300,
    task_soft_time_limit=240,
    broker_connection_retry_on_startup=True,
)


def check_redis_connection(timeout: float = 2.0) -> bool:
    """
    Verify Redis broker connectivity for readiness probes.
    Returns True if healthy, False if unreachable or errored.
    """
    # If in eager test mode without Redis configured, consider ready
    if CELERY_TASK_ALWAYS_EAGER and not os.environ.get("CELERY_BROKER_URL"):
        return True
    try:
        r = redis.Redis.from_url(CELERY_BROKER_URL, socket_timeout=timeout, socket_connect_timeout=timeout)
        return bool(r.ping())
    except Exception as exc:
        logger.warning("Redis readiness probe failed: %s", exc)
        return False
