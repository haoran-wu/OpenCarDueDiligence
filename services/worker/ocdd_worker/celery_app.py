from __future__ import annotations

import os

from celery import Celery


redis_url = os.getenv("OCDD_REDIS_URL", "redis://localhost:6379/0")
app = Celery(
    "ocdd_worker",
    broker=redis_url,
    backend=redis_url,
    include=["ocdd_worker.tasks"],
)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=300,
    worker_hijack_root_logger=False,
    beat_schedule={
        "purge-transient-artifacts-every-10-minutes": {
            "task": "ocdd.purge_transient_artifacts",
            "schedule": 600.0,
        }
    },
)
