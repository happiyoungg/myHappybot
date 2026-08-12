"""Deterministic finance and travel application services."""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from .db import create_session_factory, session_scope
from .exchange_rates import (
    ExchangeRateProvider,
    ExchangeRateUnavailableError,
    KoreaEximExchangeRateProvider,
    UnsupportedCurrencyError,
    convert_to_krw,
)
from .models import ExpenseLocationModel, ExpenseModel, TripModel, UserProfileModel
from .policy import ALLOCATION_PERCENTAGES, POLICY_VERSION
from .repositories import (
    ExchangeRateCacheRepository,
    ExpenseLocationRepository,
    ExpenseRepository,
    IncomeRepository,
    NotFoundError,
    PlanRepository,
    ProfileRepository,
    TripRepository,
)
from .schemas import (
    AllocationItem,
    ConversionStatus,
    ExchangeRateQuote,
    ExpenseCategory,
    ExpenseCreate,
    ExpenseLocationUpsert,
    ExpenseRecord,
    ExpenseUpdate,
    IncomeCreate,
    IncomeRecord,
    IncomeUpdate,
    PlanRecord,
    ProfileCreate,
    ProfileRecord,
    ProfileUpdate,
    RiskProfile,
    SettlementStatus,
    SpendingContext,
    TravelExpenseCreate,
    TripBudgetMode,
    TripCreate,
    TripRecord,
    TripStatus,
    TripUpdate,
    normalize_category,
)

SEOUL = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)


class ProfileMissingError(ValueError):
    """Raised when a calculation needs the one local profile before it exists."""


class NoActiveTripError(ValueError):
    """Raised when a travel operation cannot resolve one active trip."""


class TripTransitionError(ValueError):
    """Raised when a requested trip lifecycle transition is invalid."""


class InvalidTravelBudgetError(ValueError):
    """Raised when a budget configuration conflicts with its selected mode."""


def today_in_seoul() -> date:
    """Return the local calendar date used for omitted normal transaction dates."""
    return datetime.now(SEOUL).date()


def month_bounds(year: int, month: int) -> tuple[date, date]:
    """Return inclusive bounds and validate a calendar month."""
    if year < 2000 or year > 2200:
        raise ValueError("year must be between 2000 and 2200.")
    if month < 1 or month > 12:
        raise ValueError("month must be between 1 and 12.")
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def resolve_month(year: int | None, month: int | None) -> tuple[int, int]:
    """Default an omitted year/month to the Korea application month."""
    now = datetime.now(SEOUL)
    resolved_year = year if year is not None else now.year
    resolved_month = month if month is not None else now.month
    month_bounds(resolved_year, resolved_month)
    return resolved_year, resolved_month


def _enum_value(value: Any) -> Any:
    """Return an enum's persisted string while accepting already-normalized values."""
    return getattr(value, "value", value)


def _decimal_string(value: Decimal) -> str:
    """Serialize a decimal without binary floating point or cosmetic trailing zeroes."""
    return format(value.normalize(), "f")


class TravelService:
    """Travel lifecycle, foreign exchange, and location operations independent of MCP and UI."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
        exchange_rate_provider: ExchangeRateProvider | None = None,
    ) -> None:
        self.session_factory = session_factory or create_session_factory()
        self.trips = TripRepository()
        self.expenses = ExpenseRepository()
        self.rate_cache = ExchangeRateCacheRepository()
        self.locations = ExpenseLocationRepository()
        self.exchange_rate_provider = exchange_rate_provider or KoreaEximExchangeRateProvider()

    # Trip lifecycle
    def create_trip(self, payload: TripCreate) -> TripRecord:
        """Persist a planned trip after applying its validated budget defaults."""
        data = payload.model_dump()
        data["budget_mode"] = _enum_value(payload.budget_mode)
        if data["budget_mode"] == TripBudgetMode.NONE.value:
            data["planned_budget_krw"] = None
        self._validate_budget(data["budget_mode"], data.get("planned_budget_krw"))
        with session_scope(self.session_factory) as session:
            return TripRecord.model_validate(self.trips.create(session, data))

    def get_trip(self, trip_id: int) -> TripRecord:
        """Retrieve one persisted trip."""
        self._require_positive_id(trip_id, "trip_id")
        with session_scope(self.session_factory) as session:
            return TripRecord.model_validate(self.trips.get(session, trip_id))

    def list_trips(self, *, status: TripStatus | None = None, limit: int = 100) -> list[TripRecord]:
        """List trips newest first, optionally by status."""
        self._validate_limit(limit, maximum=500)
        with session_scope(self.session_factory) as session:
            records = self.trips.list(session, status=_enum_value(status) if status else None, limit=limit)
            return [TripRecord.model_validate(record) for record in records]

    def get_active_trip(self) -> TripRecord | None:
        """Return the one active trip, if travel mode is currently active."""
        with session_scope(self.session_factory) as session:
            trip = self.trips.get_active(session)
            return TripRecord.model_validate(trip) if trip else None

    def update_trip(self, trip_id: int, payload: TripUpdate) -> TripRecord:
        """Update mutable trip details without bypassing lifecycle transitions."""
        self._require_positive_id(trip_id, "trip_id")
        changes = payload.model_dump(exclude_none=True)
        if not changes:
            raise ValueError("Provide at least one trip field to update.")
        for name in ("budget_mode",):
            if name in changes:
                changes[name] = _enum_value(changes[name])
        with session_scope(self.session_factory) as session:
            trip = self.trips.get(session, trip_id)
            if trip.status in {TripStatus.COMPLETED.value, TripStatus.CANCELLED.value}:
                raise TripTransitionError("Completed or cancelled trips cannot be edited.")
            start_date = changes.get("start_date", trip.start_date)
            end_date = changes.get("end_date", trip.end_date)
            if end_date < start_date:
                raise ValueError("end_date cannot be before start_date.")
            budget_mode = changes.get("budget_mode", trip.budget_mode)
            budget = changes.get("planned_budget_krw", trip.planned_budget_krw)
            if budget_mode == TripBudgetMode.NONE.value:
                changes["planned_budget_krw"] = None
                budget = None
            self._validate_budget(budget_mode, budget)
            return TripRecord.model_validate(self.trips.update(session, trip, changes))

    def start_trip(self, trip_id: int | None = None) -> TripRecord:
        """Activate a selected trip or the sole planned trip whose dates include local today."""
        with session_scope(self.session_factory) as session:
            if self.trips.get_active(session) is not None:
                raise TripTransitionError("A trip is already active.")
            if trip_id is not None:
                self._require_positive_id(trip_id, "trip_id")
                trip = self.trips.get(session, trip_id)
            else:
                candidates = [
                    item
                    for item in self.trips.list(session, status=TripStatus.PLANNED.value)
                    if item.start_date <= datetime.now(ZoneInfo(item.timezone)).date() <= item.end_date
                ]
                if len(candidates) != 1:
                    raise NoActiveTripError("Provide trip_id unless exactly one planned trip is currently eligible to start.")
                trip = candidates[0]
            if trip.status != TripStatus.PLANNED.value:
                raise TripTransitionError("Only planned trips can be started.")
            started = self.trips.update(session, trip, {"status": TripStatus.ACTIVE.value})
            logger.info("travel_trip_activated trip_id=%s", started.id)
            return TripRecord.model_validate(started)

    def end_trip(self, trip_id: int | None = None) -> TripRecord:
        """Complete the active trip or a specified active trip."""
        with session_scope(self.session_factory) as session:
            trip = self._resolve_active_trip(session, trip_id)
            completed = self.trips.update(session, trip, {"status": TripStatus.COMPLETED.value})
            logger.info("travel_trip_completed trip_id=%s", completed.id)
            return TripRecord.model_validate(completed)

    def cancel_trip(self, trip_id: int) -> TripRecord:
        """Cancel a planned trip without deleting its auditable record."""
        self._require_positive_id(trip_id, "trip_id")
        with session_scope(self.session_factory) as session:
            trip = self.trips.get(session, trip_id)
            if trip.status != TripStatus.PLANNED.value:
                raise TripTransitionError("Only planned trips can be cancelled.")
            return TripRecord.model_validate(self.trips.update(session, trip, {"status": TripStatus.CANCELLED.value}))

    def set_trip_budget(self, trip_id: int, budget_mode: TripBudgetMode, planned_budget_krw: int | None = None) -> TripRecord:
        """Set trip budget mode with explicit strict-mode validation."""
        payload = TripUpdate(budget_mode=budget_mode, planned_budget_krw=planned_budget_krw)
        return self.update_trip(trip_id, payload)

    def set_trip_cash_reserve(self, trip_id: int, reserved_cash_krw: int) -> TripRecord:
        """Set the explicit cash reserve used in the trip's start-month plan."""
        return self.update_trip(trip_id, TripUpdate(reserved_cash_krw=reserved_cash_krw))

    # Exchange rates
    def get_exchange_rate(self, source_currency: str, rate_date: date | None = None) -> ExchangeRateQuote:
        """Get a cached or provider quote for one source currency in KRW."""
        currency = self._normalize_currency(source_currency)
        requested_date = rate_date or today_in_seoul()
        with session_scope(self.session_factory) as session:
            return self._lookup_quote(session, currency, requested_date)

    def convert_currency(self, amount: Decimal, source_currency: str, rate_date: date | None = None) -> dict[str, Any]:
        """Convert an amount to KRW with the exact quote metadata used."""
        if amount <= 0:
            raise ValueError("amount must be positive.")
        quote = self.get_exchange_rate(source_currency, rate_date)
        converted = convert_to_krw(amount, quote.rate_per_source_unit)
        return {
            "original_amount": str(amount),
            "original_currency": quote.source_currency,
            "converted_amount": converted,
            "converted_currency": "KRW",
            "exchange_rate": str(quote.rate_per_source_unit),
            "rate_unit": quote.quoted_unit,
            "rate_date": quote.rate_date.isoformat(),
            "provider": quote.provider,
            "is_estimated": quote.is_estimated,
        }

    def get_supported_currencies(self, rate_date: date | None = None) -> list[str]:
        """List source currencies reported by the configured provider."""
        return self.exchange_rate_provider.get_supported_currencies(rate_date or today_in_seoul())

    # Travel expenses and locations
    def add_travel_expense(self, payload: TravelExpenseCreate) -> dict[str, Any]:
        """Persist one travel expense, retaining its original amount even when conversion is pending."""
        with session_scope(self.session_factory) as session:
            return self._add_travel_expense_in_session(session, payload)

    def add_travel_expenses(self, payloads: list[TravelExpenseCreate]) -> list[dict[str, Any]]:
        """Atomically persist several travel expenses while reusing cached daily quotes."""
        if not payloads:
            raise ValueError("Provide at least one travel expense.")
        with session_scope(self.session_factory) as session:
            return [self._add_travel_expense_in_session(session, payload) for payload in payloads]

    def reconcile_travel_expense(self, expense_id: int, settled_amount_krw: int) -> ExpenseRecord:
        """Replace a travel expense's accounting amount with confirmed card settlement."""
        self._require_positive_id(expense_id, "expense_id")
        if settled_amount_krw <= 0:
            raise ValueError("settled_amount_krw must be positive.")
        with session_scope(self.session_factory) as session:
            expense = self.expenses.get(session, expense_id)
            if expense.spending_context != SpendingContext.TRAVEL.value:
                raise ValueError("Only travel expenses can be reconciled.")
            updated = self.expenses.update(
                session,
                expense,
                {
                    "amount": settled_amount_krw,
                    "settled_amount_krw": settled_amount_krw,
                    "settlement_status": SettlementStatus.SETTLED.value,
                },
            )
            return ExpenseRecord.model_validate(updated)

    def refresh_pending_currency_conversions(self, limit: int = 200) -> dict[str, int]:
        """Try to convert pending foreign travel expenses without inventing rates."""
        self._validate_limit(limit)
        converted = 0
        pending = 0
        with session_scope(self.session_factory) as session:
            for expense in self.expenses.list_pending_conversions(session, limit=limit):
                try:
                    quote = self._lookup_quote(session, expense.original_currency, expense.occurred_at)
                except ExchangeRateUnavailableError:
                    pending += 1
                    continue
                converted_amount = convert_to_krw(Decimal(expense.original_amount), quote.rate_per_source_unit)
                self.expenses.update(
                    session,
                    expense,
                    {
                        "amount": converted_amount,
                        "estimated_amount_krw": converted_amount,
                        "exchange_rate": quote.rate_per_source_unit,
                        "exchange_rate_date": quote.rate_date,
                        "exchange_rate_provider": quote.provider,
                        "exchange_rate_unit": quote.quoted_unit,
                        "conversion_status": ConversionStatus.COMPLETED.value,
                        "settlement_status": SettlementStatus.ESTIMATED.value,
                    },
                )
                converted += 1
        logger.info("travel_pending_conversion_refresh converted=%s pending=%s", converted, pending)
        return {"converted": converted, "pending": pending}

    def set_expense_location(self, expense_id: int, payload: ExpenseLocationUpsert) -> dict[str, Any]:
        """Attach a manually confirmed location to a travel expense."""
        self._require_positive_id(expense_id, "expense_id")
        with session_scope(self.session_factory) as session:
            expense = self.expenses.get(session, expense_id)
            if expense.spending_context != SpendingContext.TRAVEL.value:
                raise ValueError("Locations are available only for travel expenses.")
            location = self.locations.upsert(
                session,
                expense_id,
                {**payload.model_dump(), "provider": "manual", "location_confidence": "user_confirmed"},
            )
            return self._location_dict(location)

    def delete_expense_location(self, expense_id: int) -> bool:
        """Remove optional location metadata while keeping the expense."""
        self._require_positive_id(expense_id, "expense_id")
        with session_scope(self.session_factory) as session:
            self.expenses.get(session, expense_id)
            return self.locations.delete(session, expense_id)

    # Travel read models
    def get_trip_expenses(self, trip_id: int, *, limit: int = 500) -> list[dict[str, Any]]:
        """Return detailed trip expenses and any optional location metadata."""
        self._require_positive_id(trip_id, "trip_id")
        self._validate_limit(limit, maximum=500)
        with session_scope(self.session_factory) as session:
            self.trips.get(session, trip_id)
            records = self.expenses.list(session, trip_id=trip_id, limit=limit)
            return [self._expense_dict(session, record) for record in records]

    def get_trip_spending_summary(self, trip_id: int) -> dict[str, Any]:
        """Return auditable KRW and original-currency totals for one trip."""
        self._require_positive_id(trip_id, "trip_id")
        with session_scope(self.session_factory) as session:
            trip = self.trips.get(session, trip_id)
            expenses = self.expenses.list(session, trip_id=trip_id, limit=500)
            by_currency: dict[str, Decimal] = {}
            pending_count = 0
            for expense in expenses:
                by_currency[expense.original_currency] = by_currency.get(expense.original_currency, Decimal("0")) + Decimal(
                    expense.original_amount
                )
                if expense.conversion_status == ConversionStatus.PENDING.value:
                    pending_count += 1
            total_krw = sum(expense.amount for expense in expenses)
            return {
                "trip": TripRecord.model_validate(trip).model_dump(mode="json"),
                "expense_count": len(expenses),
                "total_amount_krw": total_krw,
                "by_currency": [
                    {"currency": currency, "original_amount": _decimal_string(amount)}
                    for currency, amount in sorted(by_currency.items())
                ],
                "pending_conversion_count": pending_count,
                "budget": self._budget_status(trip, total_krw),
            }

    def get_trip_category_summary(self, trip_id: int) -> list[dict[str, Any]]:
        """Aggregate a trip's accounting amount by existing expense category."""
        self._require_positive_id(trip_id, "trip_id")
        with session_scope(self.session_factory) as session:
            self.trips.get(session, trip_id)
            totals = self.expenses.total_by_category(session, date.min, date.max, trip_id=trip_id)
            return [{"category": category, "amount_krw": amount} for category, amount in totals]

    def get_trip_daily_summary(self, trip_id: int) -> list[dict[str, Any]]:
        """Aggregate one trip's accounting spending by local accounting date."""
        self._require_positive_id(trip_id, "trip_id")
        with session_scope(self.session_factory) as session:
            self.trips.get(session, trip_id)
            expenses = self.expenses.list(session, trip_id=trip_id, limit=500)
            totals: dict[date, int] = {}
            for expense in expenses:
                totals[expense.occurred_at] = totals.get(expense.occurred_at, 0) + expense.amount
            return [{"date": day.isoformat(), "amount_krw": amount} for day, amount in sorted(totals.items())]

    def get_trip_map_data(self, trip_id: int) -> dict[str, Any]:
        """Return normalized map markers only for expenses with confirmed coordinates."""
        self._require_positive_id(trip_id, "trip_id")
        with session_scope(self.session_factory) as session:
            self.trips.get(session, trip_id)
            items: list[dict[str, Any]] = []
            for expense in self.expenses.list(session, trip_id=trip_id, limit=500):
                location = self.locations.get(session, expense.id)
                if location is None:
                    continue
                items.append(
                    {
                        "expense_id": expense.id,
                        "place_name": location.place_name or expense.merchant,
                        "latitude": float(location.latitude),
                        "longitude": float(location.longitude),
                        "category": expense.category,
                        "original_amount": _decimal_string(Decimal(expense.original_amount)),
                        "currency": expense.original_currency,
                        "amount_krw": expense.amount,
                        "occurred_at": expense.occurred_at.isoformat(),
                        "memo": expense.memo,
                    }
                )
            return {"trip_id": trip_id, "locations": items}

    def _add_travel_expense_in_session(self, session: Session, payload: TravelExpenseCreate) -> dict[str, Any]:
        trip = self._resolve_active_trip(session, payload.trip_id)
        local_time = self._trip_local_time(payload.occurred_at, trip.timezone)
        currency = self._normalize_currency(payload.original_currency)
        estimated_amount: int | None = None
        quote: ExchangeRateQuote | None = None
        conversion_status = ConversionStatus.COMPLETED.value
        settlement_status = SettlementStatus.ESTIMATED.value
        if currency == "KRW":
            estimated_amount = int(payload.original_amount)
            settlement_status = SettlementStatus.SETTLED.value
            quote = ExchangeRateQuote(
                provider="identity",
                source_currency="KRW",
                rate_date=local_time.date(),
                rate_per_source_unit=Decimal("1"),
                quoted_unit=1,
            )
        else:
            try:
                quote = self._lookup_quote(session, currency, local_time.date())
                estimated_amount = convert_to_krw(payload.original_amount, quote.rate_per_source_unit)
            except ExchangeRateUnavailableError:
                conversion_status = ConversionStatus.PENDING.value
                settlement_status = SettlementStatus.ESTIMATED.value
        data = {
            "amount": estimated_amount or 0,
            "category": _enum_value(normalize_category(payload.category)),
            "merchant": payload.merchant,
            "occurred_at": local_time.date(),
            "memo": payload.memo,
            "spending_context": SpendingContext.TRAVEL.value,
            "trip_id": trip.id,
            "original_amount": payload.original_amount,
            "original_currency": currency,
            "estimated_amount_krw": estimated_amount,
            "settled_amount_krw": None,
            "exchange_rate": quote.rate_per_source_unit if quote else None,
            "exchange_rate_date": quote.rate_date if quote else None,
            "exchange_rate_provider": quote.provider if quote else None,
            "exchange_rate_unit": quote.quoted_unit if quote else None,
            "conversion_status": conversion_status,
            "settlement_status": settlement_status,
            "occurred_at_utc": local_time.astimezone(timezone.utc),
        }
        expense = self.expenses.create(session, data)
        if payload.latitude is not None and payload.longitude is not None:
            self.locations.upsert(
                session,
                expense.id,
                {
                    "place_name": payload.place_name or payload.merchant,
                    "address": payload.address,
                    "latitude": payload.latitude,
                    "longitude": payload.longitude,
                    "provider": "manual",
                    "location_confidence": "user_confirmed",
                },
            )
        logger.info("travel_expense_saved expense_id=%s trip_id=%s currency=%s conversion=%s", expense.id, trip.id, currency, conversion_status)
        return self._expense_dict(session, expense)

    def _lookup_quote(self, session: Session, currency: str, requested_date: date) -> ExchangeRateQuote:
        if currency == "KRW":
            return ExchangeRateQuote(
                provider="identity",
                source_currency="KRW",
                rate_date=requested_date,
                rate_per_source_unit=Decimal("1"),
                quoted_unit=1,
            )
        provider_name = self.exchange_rate_provider.name
        earliest_date = requested_date - timedelta(days=7)
        cached = self.rate_cache.latest_on_or_before(
            session,
            provider=provider_name,
            source_currency=currency,
            target_currency="KRW",
            earliest_date=earliest_date,
            latest_date=requested_date,
        )
        if cached is not None:
            logger.info("exchange_rate_cache_hit currency=%s rate_date=%s", currency, cached.rate_date)
            return ExchangeRateQuote(
                provider=cached.provider,
                source_currency=cached.source_currency,
                target_currency=cached.target_currency,
                rate_date=cached.rate_date,
                rate_per_source_unit=Decimal(cached.rate_per_source_unit),
                quoted_unit=cached.quoted_unit,
                is_estimated=cached.rate_date != requested_date,
            )
        last_error: ExchangeRateUnavailableError | None = None
        for offset in range(8):
            candidate_date = requested_date - timedelta(days=offset)
            try:
                quote = self.exchange_rate_provider.get_rate(currency, candidate_date)
            except UnsupportedCurrencyError:
                raise
            except ExchangeRateUnavailableError as error:
                last_error = error
                continue
            existing = self.rate_cache.get(
                session,
                provider=quote.provider,
                source_currency=quote.source_currency,
                target_currency=quote.target_currency,
                rate_date=quote.rate_date,
            )
            if existing is None:
                self.rate_cache.create(
                    session,
                    {
                        "provider": quote.provider,
                        "source_currency": quote.source_currency,
                        "target_currency": quote.target_currency,
                        "rate_date": quote.rate_date,
                        "rate_per_source_unit": quote.rate_per_source_unit,
                        "quoted_unit": quote.quoted_unit,
                        "is_estimated": False,
                    },
                )
            logger.info("exchange_rate_retrieved currency=%s rate_date=%s", currency, quote.rate_date)
            return quote.model_copy(update={"is_estimated": candidate_date != requested_date})
        raise last_error or ExchangeRateUnavailableError("No exchange rate is available for the requested period.")

    def _resolve_active_trip(self, session: Session, trip_id: int | None) -> TripModel:
        if trip_id is not None:
            self._require_positive_id(trip_id, "trip_id")
            trip = self.trips.get(session, trip_id)
            if trip.status != TripStatus.ACTIVE.value:
                raise NoActiveTripError("The selected trip is not active.")
            return trip
        active = self.trips.get_active(session)
        if active is None:
            raise NoActiveTripError("No active trip exists.")
        return active

    @staticmethod
    def _trip_local_time(value: datetime | None, timezone_name: str) -> datetime:
        trip_timezone = ZoneInfo(timezone_name)
        if value is None:
            return datetime.now(trip_timezone)
        if value.tzinfo is None:
            return value.replace(tzinfo=trip_timezone)
        return value.astimezone(trip_timezone)

    @staticmethod
    def _normalize_currency(value: str) -> str:
        currency = value.upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("Currency must be a three-letter ISO code.")
        return currency

    @staticmethod
    def _validate_budget(budget_mode: str, planned_budget_krw: int | None) -> None:
        if budget_mode == TripBudgetMode.STRICT.value and planned_budget_krw is None:
            raise InvalidTravelBudgetError("STRICT budget mode requires planned_budget_krw.")
        if planned_budget_krw is not None and planned_budget_krw <= 0:
            raise InvalidTravelBudgetError("planned_budget_krw must be positive.")

    @staticmethod
    def _require_positive_id(record_id: int, field_name: str) -> None:
        if record_id <= 0:
            raise ValueError(f"{field_name} must be a positive integer.")

    @staticmethod
    def _validate_limit(limit: int, *, maximum: int = 500) -> None:
        if limit < 1 or limit > maximum:
            raise ValueError(f"limit must be between 1 and {maximum}.")

    @staticmethod
    def _location_dict(location: ExpenseLocationModel) -> dict[str, Any]:
        return {
            "id": location.id,
            "expense_id": location.expense_id,
            "place_name": location.place_name,
            "address": location.address,
            "latitude": str(location.latitude),
            "longitude": str(location.longitude),
            "provider": location.provider,
            "location_confidence": location.location_confidence,
        }

    def _expense_dict(self, session: Session, expense: ExpenseModel) -> dict[str, Any]:
        payload = ExpenseRecord.model_validate(expense).model_dump(mode="json")
        payload["original_amount"] = _decimal_string(Decimal(expense.original_amount))
        if expense.exchange_rate is not None:
            payload["exchange_rate"] = _decimal_string(Decimal(expense.exchange_rate))
        location = self.locations.get(session, expense.id)
        payload["location"] = self._location_dict(location) if location else None
        return payload

    @staticmethod
    def _budget_status(trip: TripModel, total_krw: int) -> dict[str, Any]:
        if trip.budget_mode == TripBudgetMode.NONE.value:
            return {"mode": trip.budget_mode, "state": "not_tracking", "planned_budget_krw": None}
        if trip.planned_budget_krw is None:
            return {"mode": trip.budget_mode, "state": "no_budget", "planned_budget_krw": None}
        percentage = total_krw * 100 / trip.planned_budget_krw
        if trip.budget_mode == TripBudgetMode.STRICT.value and percentage > 100:
            state = "exceeded"
        elif trip.budget_mode == TripBudgetMode.STRICT.value and percentage >= 80:
            state = "approaching"
        else:
            state = "informational"
        return {
            "mode": trip.budget_mode,
            "state": state,
            "planned_budget_krw": trip.planned_budget_krw,
            "remaining_budget_krw": trip.planned_budget_krw - total_krw,
            "spent_percentage": round(percentage, 2),
        }


class FinanceService(TravelService):
    """Application service coordinating finance, travel, typed schemas, and repositories."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | None = None,
        exchange_rate_provider: ExchangeRateProvider | None = None,
    ) -> None:
        super().__init__(session_factory, exchange_rate_provider)
        self.profiles = ProfileRepository()
        self.incomes = IncomeRepository()
        self.plans = PlanRepository()

    # Profile operations
    def save_profile(self, payload: ProfileCreate) -> ProfileRecord:
        """Save the single local financial profile."""
        with session_scope(self.session_factory) as session:
            if self.profiles.get(session) is not None:
                raise ValueError("A financial profile already exists. Use update_financial_profile instead.")
            return ProfileRecord.model_validate(self.profiles.create(session, payload.model_dump()))

    def get_profile(self) -> ProfileRecord | None:
        """Retrieve the local financial profile if it exists."""
        with session_scope(self.session_factory) as session:
            profile = self.profiles.get(session)
            return ProfileRecord.model_validate(profile) if profile else None

    def update_profile(self, payload: ProfileUpdate) -> ProfileRecord:
        """Update one or more saved profile fields."""
        changes = payload.model_dump(exclude_none=True)
        if not changes:
            raise ValueError("Provide at least one profile field to update.")
        with session_scope(self.session_factory) as session:
            return ProfileRecord.model_validate(self.profiles.update(session, self._require_profile(session), changes))

    # Normal and KRW travel expenses
    def add_expense(self, payload: ExpenseCreate) -> ExpenseRecord:
        """Persist a KRW expense, attaching it to an active trip unless NORMAL is explicit."""
        with session_scope(self.session_factory) as session:
            expense = self.expenses.create(session, self._normal_expense_data(session, payload))
            return ExpenseRecord.model_validate(expense)

    def add_expenses(self, payloads: list[ExpenseCreate]) -> list[ExpenseRecord]:
        """Atomically persist several KRW expenses with active-trip context resolution."""
        if not payloads:
            raise ValueError("Provide at least one expense.")
        with session_scope(self.session_factory) as session:
            return [
                ExpenseRecord.model_validate(self.expenses.create(session, self._normal_expense_data(session, payload)))
                for payload in payloads
            ]

    def get_expense(self, expense_id: int) -> ExpenseRecord:
        """Retrieve one expense by ID."""
        self._require_positive_id(expense_id, "expense_id")
        with session_scope(self.session_factory) as session:
            return ExpenseRecord.model_validate(self.expenses.get(session, expense_id))

    def update_expense(self, expense_id: int, payload: ExpenseUpdate) -> ExpenseRecord:
        """Update editable fields of one saved expense."""
        self._require_positive_id(expense_id, "expense_id")
        changes = payload.model_dump(exclude_none=True)
        if "category" in changes:
            changes["category"] = _enum_value(normalize_category(payload.category))
        if not changes:
            raise ValueError("Provide at least one expense field to update.")
        with session_scope(self.session_factory) as session:
            return ExpenseRecord.model_validate(self.expenses.update(session, self.expenses.get(session, expense_id), changes))

    def delete_expense(self, expense_id: int) -> None:
        """Delete one explicit expense record and its optional location metadata."""
        self._require_positive_id(expense_id, "expense_id")
        with session_scope(self.session_factory) as session:
            expense = self.expenses.get(session, expense_id)
            self.locations.delete(session, expense_id)
            self.expenses.delete(session, expense)

    def list_expenses(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        category: ExpenseCategory | None = None,
        spending_context: SpendingContext | None = None,
        limit: int = 200,
    ) -> list[ExpenseRecord]:
        """List persisted expenses with optional date, category, and context filters."""
        self._validate_date_range(start_date, end_date)
        self._validate_limit(limit)
        with session_scope(self.session_factory) as session:
            records = self.expenses.list(
                session,
                start_date=start_date,
                end_date=end_date,
                category=category.value if category else None,
                spending_context=_enum_value(spending_context) if spending_context else None,
                limit=limit,
            )
            return [ExpenseRecord.model_validate(record) for record in records]

    def get_monthly_expenses(self, year: int | None = None, month: int | None = None) -> list[ExpenseRecord]:
        """List all expenses for a calendar month, including travel for historical accuracy."""
        year, month = resolve_month(year, month)
        start_date, end_date = month_bounds(year, month)
        return self.list_expenses(start_date=start_date, end_date=end_date)

    def get_daily_expenses(self, occurred_at: date | None = None) -> list[ExpenseRecord]:
        """List expenses for an explicit day or the active trip's local today."""
        if occurred_at is None:
            active = self.get_active_trip()
            day = datetime.now(ZoneInfo(active.timezone)).date() if active else today_in_seoul()
        else:
            day = occurred_at
        return self.list_expenses(start_date=day, end_date=day)

    def spending_by_category(
        self, year: int | None = None, month: int | None = None, *, include_travel: bool = False
    ) -> list[dict[str, Any]]:
        """Aggregate normal spending by category, optionally including travel context."""
        year, month = resolve_month(year, month)
        start_date, end_date = month_bounds(year, month)
        with session_scope(self.session_factory) as session:
            if include_travel:
                totals = self.expenses.total_by_category(session, start_date, end_date)
            else:
                totals = self.expenses.total_by_category(
                    session, start_date, end_date, spending_context=SpendingContext.NORMAL.value
                )
            return [{"category": category, "amount": amount} for category, amount in totals]

    def monthly_spending_summary(self, year: int | None = None, month: int | None = None) -> dict[str, Any]:
        """Return normal budget analysis plus separate travel and actual-spending totals."""
        year, month = resolve_month(year, month)
        start_date, end_date = month_bounds(year, month)
        with session_scope(self.session_factory) as session:
            normal_total = self.expenses.total(session, start_date, end_date, spending_context=SpendingContext.NORMAL.value)
            travel_total = self.expenses.total(session, start_date, end_date, spending_context=SpendingContext.TRAVEL.value)
            profile = self.profiles.get(session)
            variable_budget = profile.monthly_variable_budget if profile else None
            category_totals = self.expenses.total_by_category(
                session, start_date, end_date, spending_context=SpendingContext.NORMAL.value
            )
        return {
            "year": year,
            "month": month,
            "total_spending": normal_total + travel_total,
            "normal_spending": normal_total,
            "travel_spending": travel_total,
            "variable_budget": variable_budget,
            "budget_difference": variable_budget - normal_total if variable_budget is not None else None,
            "is_over_budget": normal_total > variable_budget if variable_budget is not None else None,
            "by_category": [{"category": category, "amount": amount} for category, amount in category_totals],
        }

    # Income operations
    def record_income(self, payload: IncomeCreate) -> IncomeRecord:
        """Persist one positive KRW income event."""
        with session_scope(self.session_factory) as session:
            return IncomeRecord.model_validate(self.incomes.create(session, payload.model_dump()))

    def get_income(self, income_id: int) -> IncomeRecord:
        """Retrieve one income event."""
        self._require_positive_id(income_id, "income_id")
        with session_scope(self.session_factory) as session:
            return IncomeRecord.model_validate(self.incomes.get(session, income_id))

    def update_income(self, income_id: int, payload: IncomeUpdate) -> IncomeRecord:
        """Update one saved income event."""
        self._require_positive_id(income_id, "income_id")
        changes = payload.model_dump(exclude_none=True)
        if not changes:
            raise ValueError("Provide at least one income field to update.")
        with session_scope(self.session_factory) as session:
            return IncomeRecord.model_validate(self.incomes.update(session, self.incomes.get(session, income_id), changes))

    def delete_income(self, income_id: int) -> None:
        """Delete one saved income event."""
        self._require_positive_id(income_id, "income_id")
        with session_scope(self.session_factory) as session:
            self.incomes.delete(session, self.incomes.get(session, income_id))

    def list_income(
        self, *, start_date: date | None = None, end_date: date | None = None, limit: int = 200
    ) -> list[IncomeRecord]:
        """List persisted income events with optional inclusive dates."""
        self._validate_date_range(start_date, end_date)
        self._validate_limit(limit)
        with session_scope(self.session_factory) as session:
            return [
                IncomeRecord.model_validate(record)
                for record in self.incomes.list(session, start_date=start_date, end_date=end_date, limit=limit)
            ]

    def monthly_income(self, year: int | None = None, month: int | None = None) -> dict[str, Any]:
        """Calculate monthly income from every persisted event."""
        year, month = resolve_month(year, month)
        start_date, end_date = month_bounds(year, month)
        with session_scope(self.session_factory) as session:
            total = self.incomes.total(session, start_date, end_date)
            records = self.incomes.list(session, start_date=start_date, end_date=end_date)
        return {
            "year": year,
            "month": month,
            "total_income": total,
            "income_events": [IncomeRecord.model_validate(record).model_dump(mode="json") for record in records],
        }

    # Deterministic monthly calculation and plan persistence
    def calculate_monthly_cashflow(self, year: int | None = None, month: int | None = None) -> dict[str, Any]:
        """Calculate cashflow with travel-only actual-spending and planned-reserve deductions."""
        year, month = resolve_month(year, month)
        with session_scope(self.session_factory) as session:
            profile = self._require_profile(session)
            start_date, end_date = month_bounds(year, month)
            income = self.incomes.total(session, start_date, end_date)
            travel_spending = self.expenses.total(
                session, start_date, end_date, spending_context=SpendingContext.TRAVEL.value
            )
            planned_trip_reserves = sum(
                trip.reserved_cash_krw for trip in self.trips.planned_starting_in_month(session, start_date, end_date)
            )
            return self._cashflow_dict(profile, income, year, month, travel_spending, planned_trip_reserves)

    def calculate_investable_amount(self, year: int | None = None, month: int | None = None) -> dict[str, Any]:
        """Return the investment-relevant fields from deterministic monthly cashflow."""
        calculation = self.calculate_monthly_cashflow(year, month)
        return {
            key: calculation[key]
            for key in (
                "year",
                "month",
                "income",
                "travel_spending",
                "planned_trip_reserves",
                "available_cash",
                "shortfall",
                "emergency_fund_target",
                "emergency_fund_gap",
                "emergency_fund_contribution",
                "investable_amount",
                "reasons",
            )
        }

    def calculate_asset_allocation(self, year: int | None = None, month: int | None = None) -> dict[str, Any]:
        """Allocate the deterministic investment amount using the existing policy."""
        calculation = self.calculate_monthly_cashflow(year, month)
        risk_profile = RiskProfile(calculation["risk_profile"])
        allocations = self._allocate(calculation["investable_amount"], risk_profile)
        reasons = list(calculation["reasons"])
        if calculation["emergency_fund_gap"] > 0:
            reasons.append("Emergency-fund funding remains ahead of investment allocation.")
        elif calculation["investable_amount"] > 0:
            reasons.append(f"Applied {POLICY_VERSION} for the saved risk profile.")
        else:
            reasons.append("No investable amount remains after required cash commitments.")
        return {
            **calculation,
            "allocations": [allocation.model_dump() for allocation in allocations],
            "policy_version": POLICY_VERSION,
            "reasons": reasons,
        }

    def create_monthly_financial_plan(self, year: int | None = None, month: int | None = None) -> PlanRecord:
        """Persist an immutable plan snapshot including travel-related input facts."""
        allocation_result = self.calculate_asset_allocation(year, month)
        with session_scope(self.session_factory) as session:
            plan = self.plans.create(
                session,
                {
                    "year": allocation_result["year"],
                    "month": allocation_result["month"],
                    "income": allocation_result["income"],
                    "fixed_expenses": allocation_result["fixed_expenses"],
                    "variable_budget": allocation_result["variable_budget"],
                    "debt_payment": allocation_result["debt_payment"],
                    "emergency_fund_contribution": allocation_result["emergency_fund_contribution"],
                    "investable_amount": allocation_result["investable_amount"],
                    "asset_allocation": allocation_result["allocations"],
                    "input_snapshot": {
                        key: allocation_result[key]
                        for key in (
                            "income",
                            "fixed_expenses",
                            "variable_budget",
                            "debt_payment",
                            "current_emergency_fund",
                            "emergency_fund_target",
                            "emergency_fund_gap",
                            "travel_spending",
                            "planned_trip_reserves",
                            "risk_profile",
                        )
                    },
                    "reasons": allocation_result["reasons"],
                    "calculation_policy_version": POLICY_VERSION,
                },
            )
            return PlanRecord.model_validate(plan)

    def get_monthly_financial_plan(
        self, *, year: int | None = None, month: int | None = None, plan_id: int | None = None
    ) -> dict[str, Any]:
        """Get a saved plan or the immutable history for a month."""
        with session_scope(self.session_factory) as session:
            if plan_id is not None:
                self._require_positive_id(plan_id, "plan_id")
                plan = self.plans.get(session, plan_id)
                return {"plan": PlanRecord.model_validate(plan).model_dump(mode="json"), "history": []}
            year, month = resolve_month(year, month)
            plans = self.plans.list(session, year=year, month=month)
            serialized = [PlanRecord.model_validate(plan).model_dump(mode="json") for plan in plans]
            return {"year": year, "month": month, "plan": serialized[0] if serialized else None, "history": serialized}

    def get_monthly_financial_summary(self, year: int | None = None, month: int | None = None) -> dict[str, Any]:
        """Return cashflow, spending context split, and saved monthly plans."""
        year, month = resolve_month(year, month)
        return {
            "cashflow": self.calculate_monthly_cashflow(year, month),
            "spending": self.monthly_spending_summary(year, month),
            **{
                "latest_plan": self.get_monthly_financial_plan(year=year, month=month)["plan"],
                "plan_history": self.get_monthly_financial_plan(year=year, month=month)["history"],
            },
        }

    def _normal_expense_data(self, session: Session, payload: ExpenseCreate) -> dict[str, Any]:
        active = self.trips.get_active(session)
        requested_context = _enum_value(payload.spending_context)
        context = requested_context or (SpendingContext.TRAVEL.value if active else SpendingContext.NORMAL.value)
        if context == SpendingContext.TRAVEL.value:
            if active is None:
                raise NoActiveTripError("No active trip exists for this travel-context expense.")
            trip_id = active.id
            local_timezone = ZoneInfo(active.timezone)
        else:
            trip_id = None
            local_timezone = SEOUL
        local_time = datetime.combine(payload.occurred_at, datetime.min.time(), tzinfo=local_timezone)
        return {
            "amount": payload.amount,
            "category": _enum_value(normalize_category(payload.category)),
            "merchant": payload.merchant,
            "occurred_at": payload.occurred_at,
            "memo": payload.memo,
            "spending_context": context,
            "trip_id": trip_id,
            "original_amount": Decimal(payload.amount),
            "original_currency": "KRW",
            "estimated_amount_krw": payload.amount,
            "settled_amount_krw": payload.amount,
            "exchange_rate": Decimal("1"),
            "exchange_rate_date": payload.occurred_at,
            "exchange_rate_provider": "identity",
            "exchange_rate_unit": 1,
            "conversion_status": ConversionStatus.COMPLETED.value,
            "settlement_status": SettlementStatus.SETTLED.value,
            "occurred_at_utc": local_time.astimezone(timezone.utc),
        }

    def _cashflow_dict(
        self,
        profile: UserProfileModel,
        income: int,
        year: int,
        month: int,
        travel_spending: int,
        planned_trip_reserves: int,
    ) -> dict[str, Any]:
        monthly_required_expenses = (
            profile.monthly_fixed_expenses + profile.monthly_variable_budget + profile.monthly_debt_payment
        )
        raw_disposable_income = income - monthly_required_expenses - travel_spending - planned_trip_reserves
        available_cash = max(raw_disposable_income, 0)
        shortfall = max(-raw_disposable_income, 0)
        emergency_fund_target = monthly_required_expenses * profile.emergency_fund_target_months
        emergency_fund_gap = max(emergency_fund_target - profile.current_emergency_fund, 0)
        emergency_fund_contribution = min(available_cash, emergency_fund_gap)
        investable_amount = available_cash - emergency_fund_contribution
        reasons: list[str] = []
        if travel_spending:
            reasons.append(f"Actual travel spending reduced this month's available cash by {travel_spending:,} KRW.")
        if planned_trip_reserves:
            reasons.append(f"Planned-trip cash reserves reduced this month's available cash by {planned_trip_reserves:,} KRW.")
        if shortfall:
            reasons.append("Income is below required commitments for this month.")
        return {
            "year": year,
            "month": month,
            "income": income,
            "fixed_expenses": profile.monthly_fixed_expenses,
            "variable_budget": profile.monthly_variable_budget,
            "debt_payment": profile.monthly_debt_payment,
            "monthly_required_expenses": monthly_required_expenses,
            "travel_spending": travel_spending,
            "planned_trip_reserves": planned_trip_reserves,
            "raw_disposable_income": raw_disposable_income,
            "available_cash": available_cash,
            "shortfall": shortfall,
            "current_emergency_fund": profile.current_emergency_fund,
            "emergency_fund_target": emergency_fund_target,
            "emergency_fund_gap": emergency_fund_gap,
            "emergency_fund_contribution": emergency_fund_contribution,
            "investable_amount": investable_amount,
            "risk_profile": profile.risk_profile,
            "reasons": reasons,
        }

    @staticmethod
    def _allocate(amount: int, risk_profile: RiskProfile) -> list[AllocationItem]:
        """Use largest-remainder rounding so allocated KRW totals exactly match input."""
        if amount <= 0:
            return []
        allocation = ALLOCATION_PERCENTAGES[risk_profile]
        floors = [(asset_class, percentage, amount * percentage // 100, amount * percentage % 100) for asset_class, percentage in allocation]
        remainder = amount - sum(item[2] for item in floors)
        ranked_indexes = sorted(range(len(floors)), key=lambda index: (-floors[index][3], index))
        extra_indexes = set(ranked_indexes[:remainder])
        return [
            AllocationItem(asset_class=asset_class, percentage=percentage, amount=base_amount + (1 if index in extra_indexes else 0))
            for index, (asset_class, percentage, base_amount, _) in enumerate(floors)
        ]

    def _require_profile(self, session: Session) -> UserProfileModel:
        profile = self.profiles.get(session)
        if profile is None:
            raise ProfileMissingError("Financial profile not found. Save a profile before calculating.")
        return profile

    @staticmethod
    def _validate_date_range(start_date: date | None, end_date: date | None) -> None:
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date cannot be after end_date.")
