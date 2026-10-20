"""
app/worker/__init__.py — Worker module re-exporting celery_app.

Allows launching the Celery worker using either:
  celery -A app.worker.celery_app worker ...
  celery -A app.worker worker ...
  celery -A app.celery_app.celery_app worker ...
"""

from app.celery_app import celery_app

__all__ = ["celery_app"]
