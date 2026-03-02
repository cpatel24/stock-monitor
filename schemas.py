from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    phone: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    name: str
    email: str


# ── User ────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Stock ────────────────────────────────────────────────────────────────────

class StockCreate(BaseModel):
    ticker: str = Field(..., max_length=16)
    company_name: str = ""
    upper_threshold: Optional[float] = None
    lower_threshold: Optional[float] = None
    alert_email: bool = True

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("upper_threshold", "lower_threshold")
    @classmethod
    def positive_threshold(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("Threshold must be positive")
        return v


class StockUpdate(BaseModel):
    upper_threshold: Optional[float] = None
    lower_threshold: Optional[float] = None
    alert_email: Optional[bool] = None
    is_active: Optional[bool] = None


class StockOut(BaseModel):
    id: int
    user_id: int
    ticker: str
    company_name: str
    upper_threshold: Optional[float]
    lower_threshold: Optional[float]
    alert_email: bool
    is_active: bool
    last_price: Optional[float]
    last_checked: Optional[datetime]
    last_alert_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── AlertLog ─────────────────────────────────────────────────────────────────

class AlertLogOut(BaseModel):
    id: int
    stock_id: int
    user_id: int
    ticker: str
    price: float
    direction: str
    threshold: float
    alert_type: str
    sent_at: datetime
    success: bool

    model_config = {"from_attributes": True}


# ── Misc ─────────────────────────────────────────────────────────────────────

class TickerValidateOut(BaseModel):
    ticker: str
    company_name: str
    price: float
    valid: bool


class CheckNowRequest(BaseModel):
    user_id: Optional[int] = None  # None = check all active stocks


class CheckNowResponse(BaseModel):
    checked: int
    alerts_sent: int
    message: str
