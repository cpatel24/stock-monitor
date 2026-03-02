from celery import Celery
from celery.schedules import crontab
from config import settings

celery_app = Celery(
    "stock_monitor",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["tasks.price_tasks", "tasks.email_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="US/Eastern",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
)

celery_app.conf.beat_schedule = {
    "price-check-every-15min": {
        "task": "tasks.price_tasks.dispatch_price_checks_task",
        "schedule": crontab(minute="*/15", hour="9-15", day_of_week="mon-fri"),
    },
}
