from celery import Celery

from app.config import settings

celery_app = Celery(
    "garmin_app",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.garmin.tasks"],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "poll-all-garmin-users": {
            "task": "app.garmin.tasks.poll_all_users_task",
            "schedule": settings.GARMIN_POLL_INTERVAL,
        },
    },
)
