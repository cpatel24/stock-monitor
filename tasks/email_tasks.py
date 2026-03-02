from celery_app import celery_app
from services.email_service import send_alert_email


@celery_app.task(
    name="tasks.email_tasks.send_alert_email_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def send_alert_email_task(
    self,
    to_email: str,
    user_name: str,
    ticker: str,
    company_name: str,
    price: float,
    direction: str,
    threshold: float,
) -> bool:
    return send_alert_email(to_email, user_name, ticker, company_name, price, direction, threshold)
