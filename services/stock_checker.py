"""
Minimal market-hours utility + Celery Beat status helper.
Price-check logic lives in tasks/price_tasks.py.
"""

from __future__ import annotations

from datetime import datetime

import pytz
import redis

from config import settings

EASTERN = pytz.timezone("US/Eastern")


def is_market_open() -> bool:
    now_et = datetime.now(EASTERN)
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et < market_close


def scheduler_status() -> dict:
    """Return status dict reflecting Celery Beat + Redis health."""
    try:
        r = redis.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    return {
        "running": redis_ok,
        "market_open": is_market_open(),
        "scheduler": "celery-beat",
        "redis_connected": redis_ok,
    }
