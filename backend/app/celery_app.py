from celery import Celery

from app.config import get_settings

settings = get_settings()
celery_app = Celery(
    "flight_match_simulator",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.task_always_eager = settings.task_always_eager
celery_app.conf.task_track_started = True
celery_app.conf.timezone = settings.timezone

