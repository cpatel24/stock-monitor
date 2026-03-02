"""
Polygon.io REST client with Redis price caching and tenacity retries.

Free-tier endpoints used:
  - /v2/aggs/ticker/{ticker}/range/1/minute/{from}/{to}  (price)
  - /v2/aggs/ticker/{ticker}/prev                        (fallback price)
  - /v3/reference/tickers/{ticker}                       (validate)
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import redis
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings

_redis_client: redis.Redis | None = None

POLYGON_BASE = "https://api.polygon.io"
PRICE_CACHE_TTL = 60     # seconds
COMPANY_CACHE_TTL = 3600  # 1 hour — company names don't change often


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
def _http_get(url: str, params: dict) -> dict:
    params = {**params, "apiKey": settings.polygon_api_key}
    with httpx.Client(timeout=10) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def get_price(ticker: str) -> float | None:
    """Return latest price for ticker. Checks Redis cache first (TTL=60s)."""
    cache_key = f"price:{ticker.upper()}"
    r = _get_redis()

    cached = r.get(cache_key)
    if cached is not None:
        return float(cached)

    price = _fetch_price_from_polygon(ticker.upper())
    if price is not None:
        r.setex(cache_key, PRICE_CACHE_TTL, str(price))
    return price


def _fetch_price_from_polygon(ticker: str) -> float | None:
    today = date.today()
    from_date = (today - timedelta(days=5)).isoformat()
    to_date = today.isoformat()

    try:
        data = _http_get(
            f"{POLYGON_BASE}/v2/aggs/ticker/{ticker}/range/1/minute/{from_date}/{to_date}",
            {"sort": "desc", "limit": 1},
        )
        results = data.get("results") or []
        if results:
            return float(results[0]["c"])
    except Exception as exc:
        logger.warning(f"[polygon] minute-agg failed for {ticker}: {exc}, trying prev")

    # Fallback: previous day close
    try:
        data = _http_get(f"{POLYGON_BASE}/v2/aggs/ticker/{ticker}/prev", {})
        results = data.get("results") or []
        if results:
            return float(results[0]["c"])
    except Exception as exc:
        logger.error(f"[polygon] prev-agg also failed for {ticker}: {exc}")

    return None


def get_prices_batch(tickers: list[str]) -> dict[str, float]:
    """Return {ticker: price} for all given tickers. Cache makes repeated calls cheap."""
    prices: dict[str, float] = {}
    for ticker in tickers:
        price = get_price(ticker)
        if price is not None:
            prices[ticker] = price
    return prices


def validate_ticker(ticker: str) -> dict | None:
    """Return {ticker, company_name, price, valid} or None if ticker is invalid."""
    ticker = ticker.upper()
    r = _get_redis()
    company_cache_key = f"company:{ticker}"

    # Check Redis cache for company name first to avoid redundant reference calls
    company_name = r.get(company_cache_key)

    if company_name is None:
        try:
            data = _http_get(f"{POLYGON_BASE}/v3/reference/tickers/{ticker}", {})
            result = data.get("results")
            if not result:
                return None
            company_name = result.get("name") or ticker
            r.setex(company_cache_key, COMPANY_CACHE_TTL, company_name)
        except Exception as exc:
            logger.warning(f"[polygon] validate_ticker({ticker}) reference failed: {exc}")
            return None

    price = get_price(ticker)
    if price is None:
        return None

    return {
        "ticker": ticker,
        "company_name": company_name,
        "price": price,
        "valid": True,
    }
