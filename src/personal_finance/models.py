"""Persistence models for the personal-finance MVP."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """Return an aware UTC timestamp for audit fields."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base shared by all local persistence models."""


class UserProfileModel(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    default_currency: Mapped[str] = mapped_column(String(3), default="KRW")
    monthly_fixed_expenses: Mapped[int] = mapped_column(Integer, default=0)
    monthly_variable_budget: Mapped[int] = mapped_column(Integer, default=0)
    emergency_fund_target_months: Mapped[int] = mapped_column(Integer, default=3)
    current_emergency_fund: Mapped[int] = mapped_column(Integer, default=0)
    current_cash: Mapped[int] = mapped_column(Integer, default=0)
    monthly_debt_payment: Mapped[int] = mapped_column(Integer, default=0)
    risk_profile: Mapped[str] = mapped_column(String(20), default="balanced")
    investment_horizon_years: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class IncomeModel(Base):
    __tablename__ = "incomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(100))
    occurred_at: Mapped[date] = mapped_column(Date)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExpenseModel(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(30))
    merchant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    occurred_at: Mapped[date] = mapped_column(Date)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    spending_context: Mapped[str] = mapped_column(String(10), default="NORMAL", nullable=False)
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("trips.id"), nullable=True)
    original_amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0"), nullable=False)
    original_currency: Mapped[str] = mapped_column(String(3), default="KRW", nullable=False)
    estimated_amount_krw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    settled_amount_krw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(24, 10), nullable=True)
    exchange_rate_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exchange_rate_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    exchange_rate_unit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversion_status: Mapped[str] = mapped_column(String(20), default="COMPLETED", nullable=False)
    settlement_status: Mapped[str] = mapped_column(String(20), default="SETTLED", nullable=False)
    occurred_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class TripModel(Base):
    """A planned or active journey for the one local profile."""

    __tablename__ = "trips"
    __table_args__ = (
        Index("ix_trips_one_active", "status", unique=True, sqlite_where=text("status = 'ACTIVE'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    destination_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    destination_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    local_currency: Mapped[str] = mapped_column(String(3), default="KRW")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Seoul")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="PLANNED")
    budget_mode: Mapped[str] = mapped_column(String(20), default="RELAXED")
    planned_budget_krw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reserved_cash_krw: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ExchangeRateCacheModel(Base):
    """Persisted, reproducible exchange-rate quotes used for travel expenses."""

    __tablename__ = "exchange_rate_cache"
    __table_args__ = (
        Index(
            "uq_exchange_rate_cache_quote",
            "provider",
            "source_currency",
            "target_currency",
            "rate_date",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50))
    source_currency: Mapped[str] = mapped_column(String(3))
    target_currency: Mapped[str] = mapped_column(String(3), default="KRW")
    rate_date: Mapped[date] = mapped_column(Date)
    rate_per_source_unit: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    quoted_unit: Mapped[int] = mapped_column(Integer, default=1)
    is_estimated: Mapped[bool] = mapped_column(default=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExpenseLocationModel(Base):
    """Optional user-confirmed location metadata for one expense."""

    __tablename__ = "expense_locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expenses.id"), unique=True)
    place_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7))
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7))
    provider: Mapped[str] = mapped_column(String(50), default="manual")
    provider_place_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location_confidence: Mapped[str] = mapped_column(String(30), default="user_confirmed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MonthlyFinancialPlanModel(Base):
    __tablename__ = "monthly_financial_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    income: Mapped[int] = mapped_column(Integer)
    fixed_expenses: Mapped[int] = mapped_column(Integer)
    variable_budget: Mapped[int] = mapped_column(Integer)
    debt_payment: Mapped[int] = mapped_column(Integer)
    emergency_fund_contribution: Mapped[int] = mapped_column(Integer)
    investable_amount: Mapped[int] = mapped_column(Integer)
    asset_allocation: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    reasons: Mapped[list[str]] = mapped_column(JSON)
    calculation_policy_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
