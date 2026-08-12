"""Deterministic service tests for Travel Mode."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from personal_finance.exchange_rates import FakeExchangeRateProvider
from personal_finance.schemas import (
    ExpenseCategory,
    ExpenseCreate,
    ExpenseLocationUpsert,
    IncomeCreate,
    ProfileCreate,
    SpendingContext,
    TravelExpenseCreate,
    TripBudgetMode,
    TripCreate,
    TripStatus,
)
from personal_finance.services import FinanceService, NoActiveTripError, TripTransitionError


def travel_service(service, rates: dict[tuple[str, date], tuple[Decimal, int] | Decimal] | None = None) -> FinanceService:
    """Build a service sharing the fixture database with deterministic foreign exchange."""
    return FinanceService(service.session_factory, FakeExchangeRateProvider(rates if rates is not None else {}))


def create_profile(service: FinanceService, *, emergency_fund: int = 5_100_000) -> None:
    """Create a profile whose travel deductions are easy to assert."""
    service.save_profile(
        ProfileCreate(
            name="Travel Test",
            monthly_fixed_expenses=1_000_000,
            monthly_variable_budget=500_000,
            monthly_debt_payment=200_000,
            emergency_fund_target_months=3,
            current_emergency_fund=emergency_fund,
        )
    )


def create_tokyo_trip(service: FinanceService, *, budget_mode: TripBudgetMode = TripBudgetMode.RELAXED):
    """Create a reusable planned Tokyo trip."""
    return service.create_trip(
        TripCreate(
            name="Tokyo 2026",
            destination_country="Japan",
            destination_city="Tokyo",
            local_currency="JPY",
            timezone="Asia/Tokyo",
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 24),
            budget_mode=budget_mode,
            planned_budget_krw=100_000 if budget_mode == TripBudgetMode.STRICT else None,
        )
    )


def test_trip_lifecycle_requires_one_active_trip(service):
    finance = travel_service(service)
    trip = create_tokyo_trip(finance)

    active = finance.start_trip(trip.id)
    assert active.status == TripStatus.ACTIVE
    assert finance.get_active_trip().id == trip.id
    with pytest.raises(TripTransitionError):
        finance.start_trip(trip.id)

    completed = finance.end_trip()
    assert completed.status == TripStatus.COMPLETED
    assert finance.get_active_trip() is None
    with pytest.raises(NoActiveTripError):
        finance.end_trip()


def test_active_trip_defaults_krw_expenses_to_travel_unless_normal_is_explicit(service):
    finance = travel_service(service)
    trip = create_tokyo_trip(finance)
    finance.start_trip(trip.id)

    automatic = finance.add_expense(ExpenseCreate(amount=2_000, occurred_at=date(2026, 8, 20)))
    normal = finance.add_expense(
        ExpenseCreate(amount=3_000, occurred_at=date(2026, 8, 20), spending_context=SpendingContext.NORMAL)
    )
    assert automatic.spending_context == SpendingContext.TRAVEL
    assert automatic.trip_id == trip.id
    assert normal.spending_context == SpendingContext.NORMAL
    assert normal.trip_id is None


def test_foreign_expense_preserves_snapshot_reconciles_and_maps(service):
    finance = travel_service(service, {("JPY", date(2026, 8, 20)): (Decimal("900"), 100)})
    trip = create_tokyo_trip(finance, budget_mode=TripBudgetMode.STRICT)
    finance.start_trip(trip.id)

    saved = finance.add_travel_expense(
        TravelExpenseCreate(
            original_amount=Decimal("1480"),
            original_currency="JPY",
            category=ExpenseCategory.FOOD,
            merchant="Ichiran",
            occurred_at=datetime(2026, 8, 20, 13, 24),
            latitude=Decimal("35.6595"),
            longitude=Decimal("139.7004"),
        )
    )
    assert saved["amount"] == 13_320
    assert saved["original_amount"] == "1480"
    assert saved["exchange_rate"] == "9"
    assert saved["exchange_rate_unit"] == 100
    assert saved["conversion_status"] == "COMPLETED"

    reconciled = finance.reconcile_travel_expense(saved["id"], 14_350)
    assert reconciled.amount == 14_350
    assert reconciled.estimated_amount_krw == 13_320
    assert reconciled.settled_amount_krw == 14_350

    summary = finance.get_trip_spending_summary(trip.id)
    assert summary["total_amount_krw"] == 14_350
    assert summary["by_currency"] == [{"currency": "JPY", "original_amount": "1480"}]
    assert summary["budget"]["state"] == "informational"
    assert finance.get_trip_map_data(trip.id)["locations"][0]["expense_id"] == saved["id"]
    assert finance.get_trip_category_summary(trip.id) == [{"category": "식비", "amount_krw": 14_350}]
    assert finance.get_trip_daily_summary(trip.id) == [{"date": "2026-08-20", "amount_krw": 14_350}]


def test_provider_failure_keeps_expense_pending_and_refreshes(service):
    rates: dict[tuple[str, date], tuple[Decimal, int] | Decimal] = {}
    finance = travel_service(service, rates)
    trip = create_tokyo_trip(finance)
    finance.start_trip(trip.id)
    pending = finance.add_travel_expense(
        TravelExpenseCreate(
            original_amount=Decimal("18.5"), original_currency="USD", occurred_at=datetime(2026, 8, 20, 12, 0)
        )
    )
    assert pending["amount"] == 0
    assert pending["conversion_status"] == "PENDING"
    assert pending["original_amount"] == "18.5"

    rates[("USD", date(2026, 8, 20))] = Decimal("1350.5")
    assert finance.refresh_pending_currency_conversions() == {"converted": 1, "pending": 0}
    refreshed = finance.get_expense(pending["id"])
    assert refreshed.amount == 24_984
    assert refreshed.conversion_status.value == "COMPLETED"


def test_normal_analysis_excludes_travel_and_cashflow_deducts_travel_and_reserve(service):
    finance = travel_service(service, {("JPY", date(2026, 8, 20)): (Decimal("1000"), 100)})
    create_profile(finance)
    finance.record_income(IncomeCreate(amount=3_200_000, source="salary", occurred_at=date(2026, 8, 1)))
    finance.add_expense(ExpenseCreate(amount=90_000, category=ExpenseCategory.FOOD, occurred_at=date(2026, 8, 10)))
    active_trip = create_tokyo_trip(finance)
    finance.start_trip(active_trip.id)
    finance.add_travel_expense(
        TravelExpenseCreate(
            original_amount=Decimal("5000"), original_currency="JPY", occurred_at=datetime(2026, 8, 20, 12, 0)
        )
    )
    reserve_trip = finance.create_trip(
        TripCreate(
            name="Busan",
            start_date=date(2026, 8, 28),
            end_date=date(2026, 8, 30),
            reserved_cash_krw=100_000,
        )
    )
    assert reserve_trip.status == TripStatus.PLANNED

    summary = finance.monthly_spending_summary(2026, 8)
    assert summary["normal_spending"] == 90_000
    assert summary["travel_spending"] == 50_000
    assert summary["total_spending"] == 140_000
    assert finance.spending_by_category(2026, 8) == [{"category": "식비", "amount": 90_000}]

    cashflow = finance.calculate_monthly_cashflow(2026, 8)
    assert cashflow["travel_spending"] == 50_000
    assert cashflow["planned_trip_reserves"] == 100_000
    assert cashflow["investable_amount"] == 1_350_000


def test_location_can_be_added_and_deleted_without_deleting_expense(service):
    finance = travel_service(service)
    trip = create_tokyo_trip(finance)
    finance.start_trip(trip.id)
    expense = finance.add_travel_expense(
        TravelExpenseCreate(original_amount=Decimal("2000"), original_currency="KRW")
    )
    location = finance.set_expense_location(
        expense["id"],
        ExpenseLocationUpsert(place_name="Hotel", latitude=Decimal("35.0"), longitude=Decimal("139.0")),
    )
    assert location["place_name"] == "Hotel"
    assert finance.delete_expense_location(expense["id"])
    assert finance.get_expense(expense["id"]).id == expense["id"]


def test_strict_budget_exposes_neutral_approaching_and_exceeded_states(service):
    finance = travel_service(service)
    trip = finance.create_trip(
        TripCreate(
            name="Strict trip",
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 24),
            budget_mode=TripBudgetMode.STRICT,
            planned_budget_krw=10_000,
        )
    )
    finance.start_trip(trip.id)
    finance.add_travel_expense(TravelExpenseCreate(original_amount=Decimal("8_000"), original_currency="KRW"))
    assert finance.get_trip_spending_summary(trip.id)["budget"]["state"] == "approaching"
    finance.add_travel_expense(TravelExpenseCreate(original_amount=Decimal("3_000"), original_currency="KRW"))
    assert finance.get_trip_spending_summary(trip.id)["budget"]["state"] == "exceeded"
