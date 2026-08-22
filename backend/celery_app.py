"""
AI Trading System — Celery Background Task Queue
Redis broker, four queues: ai_desk, kronos, portfolio, default
"""

import os

from celery import Celery
from dotenv import load_dotenv

# Load env
for env_path in ["infrastructure/.env", ".env", "../infrastructure/.env"]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

CELERY_BROKER_URL      = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND  = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

celery_app = Celery(
    "trading_system",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "backend.tasks.ai_desk_tasks",
        "backend.tasks.kronos_tasks",
        "backend.tasks.portfolio_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "backend.tasks.ai_desk_tasks.*":    {"queue": "ai_desk"},
        "backend.tasks.kronos_tasks.*":     {"queue": "kronos"},
        "backend.tasks.portfolio_tasks.*":  {"queue": "portfolio"},
    },
    task_track_started=True,
    result_expires=3600,  # 1 hour TTL on results
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)
