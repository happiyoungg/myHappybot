"""Validated inputs and serializable outputs for finance services and MCP tools."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RiskProfile(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    GROWTH = "growth"


class ExpenseCategory(str, Enum):
    FOOD = "식비"
    CAFE = "카페"
    TRANSPORT = "교통"
    SHOPPING = "쇼핑"
    HOUSING = "주거"
    COMMUNICATION = "통신"
    SUBSCRIPTION = "구독"
    CULTURE = "문화"
    TRAVEL = "여행"
    MEDICAL = "의료"
    OTHER = "기타"


class SpendingContext(str, Enum):
    NORMAL = "NORMAL"
    TRAVEL = "TRAVEL"


class TripStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TripBudgetMode(str, Enum):
    NONE = "NONE"
    RELAXED = "RELAXED"
    STRICT = "STRICT"


class ConversionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    PENDING = "PENDING"


class SettlementStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    SETTLED = "SETTLED"


class ProfileCreate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    name: str = Field(min_length=1, max_length=100)
    default_currency: str = Field(default="KRW", pattern="^KRW$")
    monthly_fixed_expenses: int = Field(default=0, ge=0)
    monthly_variable_budget: int = Field(default=0, ge=0)
    emergency_fund_target_months: int = Field(default=3, ge=1, le=24)
    current_emergency_fund: int = Field(default=0, ge=0)
    current_cash: int = Field(default=0, ge=0)
    monthly_debt_payment: int = Field(default=0, ge=0)
    risk_profile: RiskProfile = RiskProfile.BALANCED
    investment_horizon_years: int = Field(default=0, ge=0, le=100)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    default_currency: str | None = Field(default=None, pattern="^KRW$")
    monthly_fixed_expenses: int | None = Field(default=None, ge=0)
    monthly_variable_budget: int | None = Field(default=None, ge=0)
    emergency_fund_target_months: int | None = Field(default=None, ge=1, le=24)
    current_emergency_fund: int | None = Field(default=None, ge=0)
    current_cash: int | None = Field(default=None, ge=0)
    monthly_debt_payment: int | None = Field(default=None, ge=0)
    risk_profile: RiskProfile | None = None
    investment_horizon_years: int | None = Field(default=None, ge=0, le=100)


class IncomeCreate(BaseModel):
    amount: int = Field(gt=0)
    source: str = Field(min_length=1, max_length=100)
    occurred_at: date
    memo: str | None = Field(default=None, max_length=1000)


class IncomeUpdate(BaseModel):
    amount: int | None = Field(default=None, gt=0)
    source: str | None = Field(default=None, min_length=1, max_length=100)
    occurred_at: date | None = None
    memo: str | None = Field(default=None, max_length=1000)


class ExpenseCreate(BaseModel):
    amount: int = Field(gt=0)
    category: ExpenseCategory | None = None
    merchant: str | None = Field(default=None, max_length=100)
    occurred_at: date
    memo: str | None = Field(default=None, max_length=1000)
    spending_context: SpendingContext | None = None


class ExpenseUpdate(BaseModel):
    amount: int | None = Field(default=None, gt=0)
    category: ExpenseCategory | None = None
    merchant: str | None = Field(default=None, max_length=100)
    occurred_at: date | None = None
    memo: str | None = Field(default=None, max_length=1000)


class RecordModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ExpenseRecord(RecordModel):
    amount: int
    category: ExpenseCategory
    merchant: str | None
    occurred_at: date
    memo: str | None
    updated_at: datetime
    spending_context: SpendingContext
    trip_id: int | None
    original_amount: Decimal
    original_currency: str
    estimated_amount_krw: int | None
    settled_amount_krw: int | None
    exchange_rate: Decimal | None
    exchange_rate_date: date | None
    exchange_rate_provider: str | None
    exchange_rate_unit: int | None
    conversion_status: ConversionStatus
    settlement_status: SettlementStatus
    occurred_at_utc: datetime | None


class IncomeRecord(RecordModel):
    amount: int
    source: str
    occurred_at: date
    memo: str | None


class ProfileRecord(RecordModel):
    name: str
    default_currency: str
    monthly_fixed_expenses: int
    monthly_variable_budget: int
    emergency_fund_target_months: int
    current_emergency_fund: int
    current_cash: int
    monthly_debt_payment: int
    risk_profile: RiskProfile
    investment_horizon_years: int
    updated_at: datetime


class AllocationItem(BaseModel):
    asset_class: str
    amount: int = Field(ge=0)
    percentage: int = Field(ge=0, le=100)


class PlanRecord(RecordModel):
    year: int
    month: int
    income: int
    fixed_expenses: int
    variable_budget: int
    debt_payment: int
    emergency_fund_contribution: int
    investable_amount: int
    asset_allocation: list[AllocationItem]
    input_snapshot: dict[str, Any]
    reasons: list[str]
    calculation_policy_version: str


def normalize_category(category: ExpenseCategory | None) -> ExpenseCategory:
    """Use the safe fallback when the agent cannot classify a transaction."""
    return category or ExpenseCategory.OTHER


class TripCreate(BaseModel):
    """Validated input for a local trip."""

    model_config = ConfigDict(use_enum_values=True)

    name: str = Field(min_length=1, max_length=100)
    destination_country: str | None = Field(default=None, max_length=100)
    destination_city: str | None = Field(default=None, max_length=100)
    local_currency: str = Field(default="KRW", min_length=3, max_length=3)
    timezone: str = Field(default="Asia/Seoul", min_length=1, max_length=64)
    start_date: date
    end_date: date
    budget_mode: TripBudgetMode = TripBudgetMode.RELAXED
    planned_budget_krw: int | None = Field(default=None, gt=0)
    reserved_cash_krw: int = Field(default=0, ge=0)

    @field_validator("local_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        """Normalize three-letter currency codes."""
        normalized = value.upper()
        if not normalized.isalpha():
            raise ValueError("local_currency must use alphabetic ISO currency letters.")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Require an IANA timezone name."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("timezone must be a valid IANA timezone.") from error
        return value

    @model_validator(mode="after")
    def validate_trip_rules(self) -> "TripCreate":
        """Check date and strict-budget invariants."""
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date.")
        if self.budget_mode == TripBudgetMode.STRICT.value and self.planned_budget_krw is None:
            raise ValueError("STRICT budget mode requires planned_budget_krw.")
        return self


class TripUpdate(BaseModel):
    """Partial editable trip fields; status transitions use dedicated service calls."""

    model_config = ConfigDict(use_enum_values=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    destination_country: str | None = Field(default=None, max_length=100)
    destination_city: str | None = Field(default=None, max_length=100)
    local_currency: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    budget_mode: TripBudgetMode | None = None
    planned_budget_krw: int | None = Field(default=None, gt=0)
    reserved_cash_krw: int | None = Field(default=None, ge=0)

    @field_validator("local_currency")
    @classmethod
    def normalize_optional_currency(cls, value: str | None) -> str | None:
        """Normalize optional currency updates."""
        return TripCreate.normalize_currency(value) if value is not None else None

    @field_validator("timezone")
    @classmethod
    def validate_optional_timezone(cls, value: str | None) -> str | None:
        """Validate optional timezone updates."""
        return TripCreate.validate_timezone(value) if value is not None else None


class TripRecord(RecordModel):
    """Serializable persisted trip."""

    name: str
    destination_country: str | None
    destination_city: str | None
    local_currency: str
    timezone: str
    start_date: date
    end_date: date
    status: TripStatus
    budget_mode: TripBudgetMode
    planned_budget_krw: int | None
    reserved_cash_krw: int
    updated_at: datetime


class TravelExpenseCreate(BaseModel):
    """Validated input for an expense that belongs to an active trip."""

    model_config = ConfigDict(use_enum_values=True)

    original_amount: Decimal = Field(gt=Decimal("0"), max_digits=20, decimal_places=6)
    original_currency: str = Field(min_length=3, max_length=3)
    category: ExpenseCategory | None = None
    merchant: str | None = Field(default=None, max_length=100)
    occurred_at: datetime | None = None
    memo: str | None = Field(default=None, max_length=1000)
    trip_id: int | None = Field(default=None, gt=0)
    place_name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=1000)
    latitude: Decimal | None = Field(default=None, ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal | None = Field(default=None, ge=Decimal("-180"), le=Decimal("180"))

    @field_validator("original_currency")
    @classmethod
    def normalize_original_currency(cls, value: str) -> str:
        """Normalize a transaction currency code."""
        return TripCreate.normalize_currency(value)

    @model_validator(mode="after")
    def validate_location_pair(self) -> "TravelExpenseCreate":
        """Require a complete manual coordinate pair."""
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together.")
        return self


class ExpenseLocationUpsert(BaseModel):
    """User-confirmed optional location input."""

    place_name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=1000)
    latitude: Decimal = Field(ge=Decimal("-90"), le=Decimal("90"))
    longitude: Decimal = Field(ge=Decimal("-180"), le=Decimal("180"))


class ExchangeRateQuote(BaseModel):
    """Normalized exchange quote expressed as KRW per one source unit."""

    model_config = ConfigDict(use_enum_values=True)

    provider: str
    source_currency: str
    target_currency: str = "KRW"
    rate_date: date
    rate_per_source_unit: Decimal
    quoted_unit: int = Field(ge=1)
    is_estimated: bool = False
