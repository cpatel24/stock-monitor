"""
Celery tasks for checking stock prices and dispatching alert emails.

Fan-out architecture for scale:
  Beat fires dispatch_price_checks_task (coordinator)
    → reads all distinct user IDs (one DB query, no stock data loaded)
    → dispatches one run_price_check_task per user into the queue
    → workers pick up per-user tasks in parallel
    → each task handles ≤ max_stocks_per_user stocks (tiny, fast, isolated)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from celery_app import celery_app
from database import SessionLocal
from models import AlertLog, Stock, User
from services.polygon_client import get_prices_batch
from services.stock_checker import is_market_open
from config import settings

# How many user IDs to dispatch per chunk to avoid overwhelming the broker
# at 1M users this sends 1M messages in batches of 500 — still fast (~2s)
_DISPATCH_CHUNK = 500


@celery_app.task(
    name="tasks.price_tasks.dispatch_price_checks_task",
    bind=True,
    soft_time_limit=120,
    time_limit=150,
)
def dispatch_price_checks_task(self) -> dict:
    """
    Coordinator task fired by Beat every 15 minutes.
    Reads only user IDs, then fans out one per-user task per user.
    Never loads stock rows itself — keeps memory near zero regardless of scale.
    """
    if not is_market_open():
        logger.info("[dispatch] Market closed — skipping")
        return {"dispatched": 0}

    db = SessionLocal()
    try:
        # SELECT DISTINCT user_id — tiny result even at 1M users
        user_ids: list[int] = [
            row[0]
            for row in db.query(Stock.user_id)
            .filter(Stock.is_active == True)
            .distinct()
            .all()
        ]
    finally:
        db.close()

    if not user_ids:
        logger.info("[dispatch] No active stocks found")
        return {"dispatched": 0}

    # Fan out: one lightweight task per user
    for i in range(0, len(user_ids), _DISPATCH_CHUNK):
        chunk = user_ids[i : i + _DISPATCH_CHUNK]
        for uid in chunk:
            run_price_check_task.delay(user_id=uid)

    logger.info(f"[dispatch] Dispatched price-check tasks for {len(user_ids)} users")
    return {"dispatched": len(user_ids)}


@celery_app.task(
    name="tasks.price_tasks.run_price_check_task",
    bind=True,
    soft_time_limit=60,   # one user's ≤5 stocks should finish well under 60s
    time_limit=90,
)
def run_price_check_task(self, user_id: int | None = None) -> dict:
    """
    Fetch prices for all active stocks (or a single user's stocks) and dispatch
    alert emails via Celery when thresholds are breached.
    """
    if not is_market_open() and user_id is None:
        logger.info("[price_check] Market closed — skipping scheduled run")
        return {"checked": 0, "alerts_sent": 0}

    db = SessionLocal()
    try:
        query = db.query(Stock).filter(Stock.is_active == True)
        if user_id is not None:
            query = query.filter(Stock.user_id == user_id)
        stocks: list[Stock] = query.all()

        if not stocks:
            return {"checked": 0, "alerts_sent": 0}

        unique_tickers = list({s.ticker for s in stocks})
        prices = get_prices_batch(unique_tickers)
        logger.info(f"[price_check] Fetched prices for {len(prices)}/{len(unique_tickers)} tickers")

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        alerts_sent = 0

        for stock in stocks:
            price = prices.get(stock.ticker)
            if price is None:
                continue

            stock.last_price = price
            stock.last_checked = now_utc

            alerts_sent += _evaluate_and_dispatch(db, stock, price, now_utc)

        db.commit()
        logger.info(f"[price_check] Checked {len(stocks)} stocks, sent {alerts_sent} alerts")
        return {"checked": len(stocks), "alerts_sent": alerts_sent}
    except Exception as exc:
        db.rollback()
        logger.error(f"[price_check] Error: {exc}")
        raise
    finally:
        db.close()


def _evaluate_and_dispatch(db, stock: Stock, price: float, now_utc: datetime) -> int:
    """Check thresholds, log alert, dispatch email task. Returns 1 if alert dispatched."""
    # Cooldown guard
    if stock.last_alert_at is not None:
        elapsed = now_utc - stock.last_alert_at
        if elapsed < timedelta(minutes=settings.alert_cooldown_minutes):
            return 0

    direction: str | None = None
    threshold: float | None = None

    if stock.upper_threshold is not None and price > stock.upper_threshold:
        direction = "above"
        threshold = stock.upper_threshold
    elif stock.lower_threshold is not None and price < stock.lower_threshold:
        direction = "below"
        threshold = stock.lower_threshold

    if direction is None:
        return 0

    user: User | None = db.query(User).filter(User.id == stock.user_id).first()
    if user is None:
        return 0

    # Write alert log
    log = AlertLog(
        stock_id=stock.id,
        user_id=stock.user_id,
        ticker=stock.ticker,
        price=price,
        direction=direction,
        threshold=threshold,
        alert_type="email",
        sent_at=now_utc,
        success=True,
    )
    db.add(log)
    stock.last_alert_at = now_utc

    # Dispatch email non-blocking
    if stock.alert_email:
        from tasks.email_tasks import send_alert_email_task
        send_alert_email_task.delay(
            to_email=user.email,
            user_name=user.name,
            ticker=stock.ticker,
            company_name=stock.company_name,
            price=price,
            direction=direction,
            threshold=threshold,
        )
        logger.info(f"[price_check] Dispatched email alert for {stock.ticker} ({direction} ${threshold})")

    return 1
