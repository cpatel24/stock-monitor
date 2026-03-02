# Stock Monitor — Architecture Diagram

Paste the diagram below into https://mermaid.live to render it interactively.

```mermaid
flowchart TD

    %% ── External actors ──────────────────────────────────────────
    USER(["👤 User\n(Browser)"])

    subgraph EXTERNAL["External Services"]
        POLYGON["🌐 Polygon.io\nREST API\n(price data)"]
        SMTP["📧 Gmail\nSMTP\n(alerts)"]
    end

    %% ── Frontend ─────────────────────────────────────────────────
    subgraph FRONTEND["Frontend"]
        SPA["Vanilla JS SPA\nBootstrap 5\nJWT stored in localStorage"]
    end

    %% ── API Layer ────────────────────────────────────────────────
    subgraph API["FastAPI  (Uvicorn / Gunicorn)"]
        LIMITER["🛡️ Rate Limiter\nslowapi\n5 req/min → auth endpoints\n60 req/min → validate endpoint"]
        AUTH["🔐 Auth Routes\nPOST /api/auth/register\nPOST /api/auth/login\nbcrypt + JWT"]
        ROUTES["📡 API Routes\nGET/POST /api/users/id/stocks\nGET /api/ticker/validate\nPOST /api/check-now\nGET /api/users/id/alerts"]
        HEALTH["💚 Health Checks\nGET /health  →  liveness\nGET /health/ready  →  DB + Redis"]
        MW["📝 Middleware\nRequest logger\nmethod · path · status · ms"]
    end

    %% ── Storage ──────────────────────────────────────────────────
    subgraph STORAGE["PostgreSQL  (persistent storage)"]
        USERS[("users\nid · name · email\nhashed_password")]
        STOCKS[("stocks\nticker · thresholds\nlast_price · is_active")]
        ALERTS[("alert_logs\nticker · price · direction\nthreshold · sent_at")]
    end

    %% ── Redis ────────────────────────────────────────────────────
    subgraph REDIS["Redis  (3 separate roles)"]
        BROKER["📬 Task Queue\nCelery broker\n_kombu.binding.celery"]
        RESULTS["📋 Task Results\nCelery backend\ncelery-task-meta-uuid\nTTL 1 hour"]
        PCACHE["⚡ Price Cache\nprice:AAPL → 263.55\nTTL 60 seconds"]
        CCACHE["🏢 Company Cache\ncompany:AAPL → Apple Inc.\nTTL 1 hour"]
    end

    %% ── Celery ───────────────────────────────────────────────────
    subgraph CELERY["Celery"]
        BEAT["⏰ Beat Scheduler\nevery 15 min\nMon–Fri 09:00–16:00 ET"]
        DISPATCH["📦 dispatch_price_checks_task\nCoordinator\nReads user IDs only\nFan-out: 1 task per user"]
        PRICE["🔍 run_price_check_task\nPer-user  ·  ≤5 stocks\nFetch price → check threshold\n→ write DB → dispatch email"]
        EMAIL["✉️ send_alert_email_task\nauto-retry 3×\nexponential backoff"]
    end

    %% ── Request flow ─────────────────────────────────────────────
    USER        -->|"HTTPS"| SPA
    SPA         -->|"REST + Authorization: Bearer JWT"| LIMITER
    LIMITER     --> AUTH
    LIMITER     --> ROUTES
    LIMITER     --> HEALTH

    AUTH        -->|"read / write user"| USERS
    ROUTES      -->|"read / write"| STOCKS
    ROUTES      -->|"read"| ALERTS
    ROUTES      -->|"task.delay(user_id)"| BROKER

    HEALTH      -->|"SELECT 1"| USERS
    HEALTH      -->|"PING"| PCACHE

    %% ── Scheduler flow ───────────────────────────────────────────
    BEAT        -->|"dispatch_price_checks_task.delay()"| BROKER
    BROKER      -->|"BRPOP"| DISPATCH
    DISPATCH    -->|"fan-out\nrun_price_check_task.delay(uid)\nfor each active user"| BROKER
    BROKER      -->|"BRPOP"| PRICE
    BROKER      -->|"BRPOP"| EMAIL

    %% ── Price check flow ─────────────────────────────────────────
    PRICE       -->|"cache HIT → return instantly"| PCACHE
    PRICE       -->|"cache MISS → HTTP GET"| POLYGON
    POLYGON     -->|"price response"| PCACHE
    PCACHE      -.->|"float"| PRICE

    PRICE       -->|"validate ticker\ncompany name lookup"| CCACHE
    CCACHE      -.->|"cache HIT"| PRICE
    PRICE       -->|"cache MISS"| POLYGON

    PRICE       -->|"UPDATE last_price\nlast_checked"| STOCKS
    PRICE       -->|"threshold breached?\nINSERT AlertLog"| ALERTS
    PRICE       -->|"send_alert_email_task.delay()"| BROKER

    %% ── Email flow ───────────────────────────────────────────────
    EMAIL       -->|"SMTP TLS"| SMTP
    EMAIL       -->|"write result"| RESULTS

    %% ── Styling ──────────────────────────────────────────────────
    classDef external  fill:#f0e6ff,stroke:#9b59b6,color:#000
    classDef api       fill:#dff0ff,stroke:#2980b9,color:#000
    classDef storage   fill:#d5f5e3,stroke:#27ae60,color:#000
    classDef redis     fill:#ffe6e6,stroke:#e74c3c,color:#000
    classDef celery    fill:#fef9e7,stroke:#f39c12,color:#000
    classDef user      fill:#eaf2ff,stroke:#2980b9,color:#000

    class POLYGON,SMTP external
    class LIMITER,AUTH,ROUTES,HEALTH,MW api
    class USERS,STOCKS,ALERTS storage
    class BROKER,RESULTS,PCACHE,CCACHE redis
    class BEAT,DISPATCH,PRICE,EMAIL celery
    class USER,SPA user
```

---

## ASCII Quick Reference

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           BROWSER (SPA)                                 │
│              Vanilla JS · Bootstrap 5 · JWT in localStorage             │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │  HTTPS · Authorization: Bearer <JWT>
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    FASTAPI  (Uvicorn / Gunicorn)                        │
│                                                                         │
│  ┌──────────────┐  ┌────────────────────┐  ┌────────────────────────┐  │
│  │ Rate Limiter │  │   Auth Routes      │  │   API Routes           │  │
│  │  (slowapi)   │  │ /api/auth/register │  │ /api/users/*/stocks    │  │
│  │  5/min auth  │  │ /api/auth/login    │  │ /api/ticker/validate   │  │
│  │ 60/min valid │  │ bcrypt + JWT       │  │ /api/check-now         │  │
│  └──────────────┘  └────────────────────┘  └────────────────────────┘  │
│                                                                         │
│  ┌─────────────────────────────┐  ┌─────────────────────────────────┐  │
│  │ Health Checks               │  │ Request Logger (middleware)      │  │
│  │ /health      → liveness     │  │ method · path · status · ms     │  │
│  │ /health/ready→ DB + Redis   │  └─────────────────────────────────┘  │
│  └─────────────────────────────┘                                        │
└──────────┬───────────────────────────────────┬──────────────────────────┘
           │ read/write                        │ task.delay(user_id)
           ▼                                   ▼
┌──────────────────────┐            ┌──────────────────────────────────────┐
│  POSTGRESQL          │            │  REDIS                               │
│                      │            │                                      │
│  ┌────────────────┐  │            │  ┌─────────────────┐                 │
│  │ users          │  │            │  │  Task Queue     │ ← Celery broker │
│  │ id,name,email  │  │            │  │  (LPUSH/BRPOP)  │                 │
│  │ hashed_pass    │  │            │  └────────┬────────┘                 │
│  ├────────────────┤  │            │           │                          │
│  │ stocks         │  │            │  ┌────────▼────────┐                 │
│  │ ticker         │  │            │  │  Task Results   │ ← Celery backend│
│  │ thresholds     │◄─┼────────────┼──│  TTL 1 hour     │                 │
│  │ last_price     │  │            │  └─────────────────┘                 │
│  ├────────────────┤  │            │                                      │
│  │ alert_logs     │  │            │  ┌─────────────────┐                 │
│  │ price,direction│  │            │  │  Price Cache    │ TTL 60 seconds  │
│  │ threshold      │  │            │  │  price:AAPL     │                 │
│  └────────────────┘  │            │  ├─────────────────┤                 │
└──────────────────────┘            │  │  Company Cache  │ TTL 1 hour      │
                                    │  │  company:AAPL   │                 │
                                    │  └─────────────────┘                 │
                                    └──────────┬───────────────────────────┘
                                               │ BRPOP (workers pull tasks)
┌──────────────────────────────────────────────▼───────────────────────────┐
│  CELERY                                                                  │
│                                                                          │
│  ┌───────────────────┐    fires every 15min    ┌──────────────────────┐  │
│  │  Beat Scheduler   │ ──── Mon–Fri 9–4 ET ──► │  dispatch task       │  │
│  │                   │                         │  reads user IDs only │  │
│  └───────────────────┘                         │  fan-out 1 task/user │  │
│                                                └──────────┬───────────┘  │
│                      ┌─────────────────────────────────────┘             │
│                      ▼  (one task per active user)                       │
│          ┌─────────────────────────┐                                     │
│          │  run_price_check_task   │                                     │
│          │  ≤ 5 stocks per user    │                                     │
│          │  1. get price           │──── cache miss ──►  Polygon.io API  │
│          │     (Redis cache first) │◄─── price data ──── (HTTP GET)      │
│          │  2. check thresholds    │                                     │
│          │  3. update DB           │──────────────────►  PostgreSQL      │
│          │  4. breach? → email     │                                     │
│          └───────────┬─────────────┘                                     │
│                      │ send_alert_email_task.delay()                     │
│                      ▼                                                   │
│          ┌─────────────────────────┐                                     │
│          │  send_alert_email_task  │──────────────────►  Gmail SMTP      │
│          │  auto-retry 3×          │                     (TLS port 587)  │
│          │  exponential backoff    │                                     │
│          └─────────────────────────┘                                     │
└──────────────────────────────────────────────────────────────────────────┘
```
