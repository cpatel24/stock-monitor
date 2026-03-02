================================================================
  STOCK MONITOR — Production-Ready Stock Price Alert System
================================================================

A full-stack web application that monitors stock prices and sends
email alerts when user-defined price thresholds are crossed.

----------------------------------------------------------------
  ARCHITECTURE
----------------------------------------------------------------

  Browser (Vanilla JS SPA)
      └── FastAPI (multi-worker, Gunicorn/Uvicorn)
               ├── PostgreSQL  (user data, stocks, alert logs)
               └── Redis  ←── Celery Beat (scheduler)
                               │
                          Celery Workers
                            ├── dispatch_price_checks_task (fan-out coordinator)
                            ├── run_price_check_task       (per-user price check)
                            └── send_alert_email_task      (SMTP email delivery)

  Price data:  Polygon.io REST API (free tier) with Redis caching
  Auth:        JWT (python-jose) + bcrypt password hashing
  Rate limit:  slowapi — 60 req/min general, 5/min on auth endpoints

----------------------------------------------------------------
  REQUIREMENTS
----------------------------------------------------------------

  Runtime:
    - Python 3.11+
    - PostgreSQL 14+
    - Redis 6+

  External accounts (free):
    - Polygon.io API key  →  https://polygon.io/dashboard/signup
    - Gmail App Password  →  https://myaccount.google.com/apppasswords
      (needed only if you want email alerts)

----------------------------------------------------------------
  INSTALLATION
----------------------------------------------------------------

  1. Clone the repository:
       git clone https://github.com/patelchirag24/stock-monitor.git
       cd stock-monitor

  2. Create and activate a Python virtual environment:
       python3 -m venv .venv
       source .venv/bin/activate

  3. Install dependencies:
       pip install -r requirements.txt

  4. Start PostgreSQL and Redis (macOS with Homebrew):
       brew services start postgresql@16
       brew services start redis

  5. Create the database and user:
       psql postgres -c "CREATE USER stockuser WITH PASSWORD 'stockpass';"
       psql postgres -c "CREATE DATABASE stock_monitor OWNER stockuser;"
       psql postgres -c "GRANT ALL PRIVILEGES ON DATABASE stock_monitor TO stockuser;"
       psql -d stock_monitor -U stockuser -c "GRANT ALL ON SCHEMA public TO stockuser;"

  6. Copy .env.example to .env and fill in your values:
       cp .env.example .env
       # Edit .env — see ENVIRONMENT VARIABLES section below

  7. Create database tables:
       python -c "from database import init_db; init_db()"

----------------------------------------------------------------
  ENVIRONMENT VARIABLES  (.env)
----------------------------------------------------------------

  DATABASE_URL=postgresql://stockuser:stockpass@localhost:5432/stock_monitor
  REDIS_URL=redis://localhost:6379/0

  # Polygon.io — get free key at polygon.io
  POLYGON_API_KEY=your_polygon_api_key_here

  # JWT — generate with: python -c "import secrets; print(secrets.token_hex(32))"
  SECRET_KEY=replace-with-64-char-random-hex
  ACCESS_TOKEN_EXPIRE_MINUTES=1440

  # Gmail SMTP — use an App Password, not your login password
  SMTP_HOST=smtp.gmail.com
  SMTP_PORT=587
  SMTP_USER=your_gmail@gmail.com
  SMTP_PASSWORD=your_16char_app_password

  # Optional overrides
  ALERT_COOLDOWN_MINUTES=30
  MAX_STOCKS_PER_USER=5

----------------------------------------------------------------
  RUNNING THE APPLICATION
----------------------------------------------------------------

  You need three terminal windows:

  Terminal 1 — FastAPI server:
    uvicorn main:app --reload --port 8000
    (or for production: gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker)

  Terminal 2 — Celery worker (price checks + email sends):
    celery -A celery_app worker --loglevel=info --concurrency=4

  Terminal 3 — Celery Beat scheduler (fires every 15 min, market hours):
    celery -A celery_app beat --loglevel=info

  Open browser:  http://localhost:8000

----------------------------------------------------------------
  API ENDPOINTS
----------------------------------------------------------------

  Health
    GET  /health             Liveness probe — always returns {"status":"ok"}
    GET  /health/ready       Readiness probe — checks DB + Redis

  Auth
    POST /api/auth/register  Create account  {name, email, password}
    POST /api/auth/login     Sign in         {email, password}
                             → returns {access_token, user_id, name, email}

  Stocks  (all require Authorization: Bearer <token>)
    GET    /api/users/{id}/stocks           List watchlist
    POST   /api/users/{id}/stocks           Add stock  {ticker, upper_threshold, lower_threshold}
    PUT    /api/stocks/{id}                 Update thresholds
    DELETE /api/stocks/{id}                 Remove from watchlist

  Ticker
    GET  /api/ticker/{ticker}/validate      Validate ticker + get live price

  Price check
    POST /api/check-now                     Trigger immediate price check (async)

  Alerts
    GET  /api/users/{id}/alerts             Recent alert history

----------------------------------------------------------------
  HOW PRICE CHECKING WORKS (SCALING)
----------------------------------------------------------------

  Celery Beat fires dispatch_price_checks_task every 15 minutes
  (Mon–Fri, 09:00–16:00 US Eastern).

  Fan-out pattern for scalability:
    1. Coordinator reads only user IDs (tiny query regardless of user count)
    2. Enqueues one run_price_check_task per active user into Redis
    3. Worker pool drains the queue in parallel
    4. Each per-user task handles ≤5 stocks — fast and isolated

  This means:
    - Adding users doesn't slow down any single worker
    - One user's failure is isolated — doesn't affect others
    - Horizontal scaling: add more worker machines to reduce wall-clock time

  Price data flow:
    Polygon.io API → Redis cache (60s TTL per ticker) → PostgreSQL (last_price)
    Company names are cached separately in Redis with 1-hour TTL.

  Alert flow:
    Threshold breached → AlertLog written to DB → send_alert_email_task.delay()
    Email is sent asynchronously by a worker, not in the price-check loop.
    Cooldown: 30 minutes between repeated alerts for the same stock.

----------------------------------------------------------------
  PROJECT STRUCTURE
----------------------------------------------------------------

  stock-monitor/
  ├── main.py                   FastAPI app, all routes
  ├── config.py                 Pydantic settings (reads .env)
  ├── auth.py                   JWT + bcrypt helpers, get_current_user dep
  ├── database.py               SQLAlchemy engine + session (PostgreSQL)
  ├── models.py                 ORM models: User, Stock, AlertLog
  ├── schemas.py                Pydantic request/response schemas
  ├── celery_app.py             Celery app config + Beat schedule
  ├── tasks/
  │   ├── price_tasks.py        dispatch + run_price_check Celery tasks
  │   └── email_tasks.py        send_alert_email Celery task
  ├── services/
  │   ├── polygon_client.py     Polygon.io REST client + Redis cache
  │   ├── email_service.py      SMTP email sender
  │   └── stock_checker.py      is_market_open() utility
  ├── static/
  │   └── index.html            Single-page app (vanilla JS + Bootstrap 5)
  ├── requirements.txt
  ├── .env.example              Template — copy to .env and fill secrets
  └── README.txt                This file

================================================================
