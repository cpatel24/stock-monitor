from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_email", "email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    stocks: Mapped[list["Stock"]] = relationship(
        "Stock", back_populates="user", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["AlertLog"]] = relationship("AlertLog", back_populates="user")


class Stock(Base):
    __tablename__ = "stocks"
    __table_args__ = (
        Index("ix_stocks_user_id", "user_id"),
        Index("ix_stocks_ticker", "ticker"),
        Index("ix_stocks_user_active", "user_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    upper_threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lower_threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    alert_email: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_checked: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_alert_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="stocks")
    alerts: Mapped[list["AlertLog"]] = relationship("AlertLog", back_populates="stock")


class AlertLog(Base):
    __tablename__ = "alert_logs"
    __table_args__ = (
        Index("ix_alertlog_user_id", "user_id"),
        Index("ix_alertlog_user_sent", "user_id", "sent_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    stock_id: Mapped[int] = mapped_column(Integer, ForeignKey("stocks.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # "above" | "below"
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    success: Mapped[bool] = mapped_column(Boolean, default=True)

    stock: Mapped["Stock"] = relationship("Stock", back_populates="alerts")
    user: Mapped["User"] = relationship("User", back_populates="alerts")
