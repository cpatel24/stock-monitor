import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import create_access_token, get_current_user, hash_password, verify_password
from config import settings
from database import get_db, init_db
from models import AlertLog, Stock, User
from schemas import (
    AlertLogOut,
    CheckNowRequest,
    CheckNowResponse,
    LoginRequest,
    RegisterRequest,
    StockCreate,
    StockOut,
    StockUpdate,
    TickerValidateOut,
    TokenResponse,
    UserOut,
    UserUpdate,
)
from services.polygon_client import validate_ticker
from services.stock_checker import scheduler_status

STATIC_DIR = Path(__file__).parent / "static"

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Stock Monitor started — scheduler runs via Celery Beat")
    yield
    logger.info("Stock Monitor shutting down")


app = FastAPI(title="Stock Monitor", version="2.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Request logging middleware ─────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        f"{request.method} {request.url.path} → {response.status_code} ({duration_ms:.1f}ms)"
    )
    return response


# ── Serve SPA ─────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def health_readiness(db: Session = Depends(get_db)):
    import redis as redis_lib
    errors = []

    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"
        errors.append("db")

    try:
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        redis_status = "ok"
    except Exception as exc:
        redis_status = f"error: {exc}"
        errors.append("redis")

    if errors:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": db_status, "redis": redis_status},
        )
    return {"status": "ok", "db": db_status, "redis": redis_status}


# ── Scheduler status ──────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    return scheduler_status()


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/api/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, payload: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id)
    logger.info(f"[auth] New user registered: {user.email} (id={user.id})")
    return TokenResponse(
        access_token=token, user_id=user.id, name=user.name, email=user.email
    )


@app.post("/api/auth/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user.id)
    logger.info(f"[auth] Login: {user.email} (id={user.id})")
    return TokenResponse(
        access_token=token, user_id=user.id, name=user.name, email=user.email
    )


# ── Users ─────────────────────────────────────────────────────────────────────

@app.put("/api/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    user = _get_user_or_404(db, user_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@app.delete("/api/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    user = _get_user_or_404(db, user_id)
    db.delete(user)
    db.commit()


# ── Stocks ────────────────────────────────────────────────────────────────────

@app.get("/api/users/{user_id}/stocks", response_model=list[StockOut])
def list_stocks(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    _get_user_or_404(db, user_id)
    return db.query(Stock).filter(Stock.user_id == user_id).all()


@app.post(
    "/api/users/{user_id}/stocks",
    response_model=StockOut,
    status_code=status.HTTP_201_CREATED,
)
def add_stock(
    user_id: int,
    payload: StockCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    _get_user_or_404(db, user_id)
    count = db.query(Stock).filter(Stock.user_id == user_id).count()
    if count >= settings.max_stocks_per_user:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {settings.max_stocks_per_user} stocks per user",
        )

    company_name = payload.company_name
    if not company_name:
        info = validate_ticker(payload.ticker)
        company_name = info["company_name"] if info else payload.ticker

    stock = Stock(
        user_id=user_id,
        ticker=payload.ticker,
        company_name=company_name,
        upper_threshold=payload.upper_threshold,
        lower_threshold=payload.lower_threshold,
        alert_email=payload.alert_email,
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    return stock


@app.put("/api/stocks/{stock_id}", response_model=StockOut)
def update_stock(
    stock_id: int,
    payload: StockUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stock = _get_stock_or_404(db, stock_id)
    if stock.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(stock, field, value)
    db.commit()
    db.refresh(stock)
    return stock


@app.delete("/api/stocks/{stock_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stock(
    stock_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stock = _get_stock_or_404(db, stock_id)
    if stock.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    db.delete(stock)
    db.commit()


# ── Ticker validation ──────────────────────────────────────────────────────────

@app.get("/api/ticker/{ticker}/validate", response_model=TickerValidateOut)
@limiter.limit("60/minute")
def validate_ticker_endpoint(
    request: Request,
    ticker: str,
    current_user: User = Depends(get_current_user),
):
    result = validate_ticker(ticker)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")
    return result


# ── Manual check ──────────────────────────────────────────────────────────────

@app.post("/api/check-now", response_model=CheckNowResponse)
def check_now(
    payload: CheckNowRequest = CheckNowRequest(),
    current_user: User = Depends(get_current_user),
):
    from tasks.price_tasks import run_price_check_task

    # Force the check for the current user's stocks only
    user_id = current_user.id
    task = run_price_check_task.delay(user_id=user_id)
    logger.info(f"[check-now] Dispatched price check task {task.id} for user {user_id}")
    return CheckNowResponse(
        checked=0,
        alerts_sent=0,
        message=f"Price check dispatched (task {task.id}) — refresh in a moment",
    )


# ── Alert log ──────────────────────────────────────────────────────────────────

@app.get("/api/users/{user_id}/alerts", response_model=list[AlertLogOut])
def list_user_alerts(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    _get_user_or_404(db, user_id)
    return (
        db.query(AlertLog)
        .filter(AlertLog.user_id == user_id)
        .order_by(AlertLog.sent_at.desc())
        .limit(50)
        .all()
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _get_stock_or_404(db: Session, stock_id: int) -> Stock:
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")
    return stock
