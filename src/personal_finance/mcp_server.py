"""MCP 1.x server exposing the personal-finance application service."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from mcp.server.fastmcp import FastMCP

from .schemas import (
    ExpenseCategory,
    ExpenseCreate,
    ExpenseLocationUpsert,
    ExpenseUpdate,
    IncomeCreate,
    IncomeUpdate,
    ProfileCreate,
    ProfileUpdate,
    SpendingContext,
    TravelExpenseCreate,
    TripBudgetMode,
    TripCreate,
    TripStatus,
    TripUpdate,
)
from .services import FinanceService, today_in_seoul

mcp = FastMCP("Personal Finance")
service = FinanceService()


def dump(model: Any) -> dict[str, Any]:
    """Return JSON-ready Pydantic output to MCP clients."""
    return model.model_dump(mode="json")


@mcp.tool()
def save_financial_profile(
    name: str,
    monthly_fixed_expenses: int = 0,
    monthly_variable_budget: int = 0,
    emergency_fund_target_months: int = 3,
    current_emergency_fund: int = 0,
    current_cash: int = 0,
    monthly_debt_payment: int = 0,
    risk_profile: str = "balanced",
    investment_horizon_years: int = 0,
) -> dict[str, Any]:
    """Save the one-time local financial profile. Use this during financial onboarding."""
    profile = service.save_profile(
        ProfileCreate(
            name=name,
            monthly_fixed_expenses=monthly_fixed_expenses,
            monthly_variable_budget=monthly_variable_budget,
            emergency_fund_target_months=emergency_fund_target_months,
            current_emergency_fund=current_emergency_fund,
            current_cash=current_cash,
            monthly_debt_payment=monthly_debt_payment,
            risk_profile=risk_profile,
            investment_horizon_years=investment_horizon_years,
        )
    )
    return {"saved": True, "profile": dump(profile)}


@mcp.tool()
def get_financial_profile() -> dict[str, Any]:
    """Retrieve the saved local financial profile; use this before financial calculations."""
    profile = service.get_profile()
    return {"found": profile is not None, "profile": dump(profile) if profile else None}


@mcp.tool()
def update_financial_profile(
    name: str | None = None,
    monthly_fixed_expenses: int | None = None,
    monthly_variable_budget: int | None = None,
    emergency_fund_target_months: int | None = None,
    current_emergency_fund: int | None = None,
    current_cash: int | None = None,
    monthly_debt_payment: int | None = None,
    risk_profile: str | None = None,
    investment_horizon_years: int | None = None,
) -> dict[str, Any]:
    """Update one or more fields in the saved local financial profile."""
    profile = service.update_profile(
        ProfileUpdate(
            name=name,
            monthly_fixed_expenses=monthly_fixed_expenses,
            monthly_variable_budget=monthly_variable_budget,
            emergency_fund_target_months=emergency_fund_target_months,
            current_emergency_fund=current_emergency_fund,
            current_cash=current_cash,
            monthly_debt_payment=monthly_debt_payment,
            risk_profile=risk_profile,
            investment_horizon_years=investment_horizon_years,
        )
    )
    return {"updated": True, "profile": dump(profile)}


@mcp.tool()
def add_expense(
    amount: int,
    category: ExpenseCategory | None = None,
    merchant: str | None = None,
    occurred_at: date | None = None,
    memo: str | None = None,
    spending_context: SpendingContext | None = None,
) -> dict[str, Any]:
    """Persist one KRW expense; active travel defaults to TRAVEL unless NORMAL is explicit."""
    expense = service.add_expense(
        ExpenseCreate(
            amount=amount,
            category=category,
            merchant=merchant,
            occurred_at=occurred_at or today_in_seoul(),
            memo=memo,
            spending_context=spending_context,
        )
    )
    return {"saved": True, "expense": dump(expense)}


@mcp.tool()
def add_expenses(expenses: list[ExpenseCreate]) -> dict[str, Any]:
    """Atomically persist multiple expenses, for example a meal and coffee in one message."""
    records = service.add_expenses(expenses)
    return {"saved": True, "count": len(records), "expenses": [dump(record) for record in records]}


@mcp.tool()
def update_expense(
    expense_id: int,
    amount: int | None = None,
    category: ExpenseCategory | None = None,
    merchant: str | None = None,
    occurred_at: date | None = None,
    memo: str | None = None,
) -> dict[str, Any]:
    """Update a saved expense by its positive numeric ID."""
    expense = service.update_expense(
        expense_id,
        ExpenseUpdate(amount=amount, category=category, merchant=merchant, occurred_at=occurred_at, memo=memo),
    )
    return {"updated": True, "expense": dump(expense)}


@mcp.tool()
def delete_expense(expense_id: int) -> dict[str, Any]:
    """Delete one expense by ID after the user explicitly asks to remove it."""
    service.delete_expense(expense_id)
    return {"deleted": True, "expense_id": expense_id}


@mcp.tool()
def get_expense(expense_id: int) -> dict[str, Any]:
    """Get one expense by ID."""
    return {"expense": dump(service.get_expense(expense_id))}


@mcp.tool()
def list_expenses(
    start_date: date | None = None,
    end_date: date | None = None,
    category: ExpenseCategory | None = None,
    spending_context: SpendingContext | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """List persisted expenses, optionally filtered by inclusive dates and category."""
    records = service.list_expenses(
        start_date=start_date, end_date=end_date, category=category, spending_context=spending_context, limit=limit
    )
    return {"expenses": [dump(record) for record in records], "count": len(records)}


@mcp.tool()
def get_daily_expenses(occurred_at: date | None = None) -> dict[str, Any]:
    """List expenses for a calendar day; omit the date for today in Asia/Seoul."""
    records = service.get_daily_expenses(occurred_at)
    return {"expenses": [dump(record) for record in records], "count": len(records)}


@mcp.tool()
def get_monthly_expenses(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """List expenses in a calendar month; omitted values default to the Korea current month."""
    records = service.get_monthly_expenses(year, month)
    return {"expenses": [dump(record) for record in records], "count": len(records)}


@mcp.tool()
def get_spending_by_category(
    year: int | None = None, month: int | None = None, include_travel: bool = False
) -> dict[str, Any]:
    """Aggregate normal monthly spending by category; set include_travel only when explicitly requested."""
    return {"items": service.spending_by_category(year, month, include_travel=include_travel)}


@mcp.tool()
def get_monthly_spending_summary(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Return database-backed monthly spending, category totals, and saved-budget comparison."""
    return service.monthly_spending_summary(year, month)


@mcp.tool()
def record_income(
    amount: int,
    source: str,
    occurred_at: date | None = None,
    memo: str | None = None,
) -> dict[str, Any]:
    """Persist a positive KRW income event; multiple income events per month are supported."""
    income = service.record_income(
        IncomeCreate(amount=amount, source=source, occurred_at=occurred_at or today_in_seoul(), memo=memo)
    )
    return {"saved": True, "income": dump(income)}


@mcp.tool()
def update_income(
    income_id: int,
    amount: int | None = None,
    source: str | None = None,
    occurred_at: date | None = None,
    memo: str | None = None,
) -> dict[str, Any]:
    """Update a persisted income event by ID."""
    income = service.update_income(income_id, IncomeUpdate(amount=amount, source=source, occurred_at=occurred_at, memo=memo))
    return {"updated": True, "income": dump(income)}


@mcp.tool()
def delete_income(income_id: int) -> dict[str, Any]:
    """Delete an income event by ID."""
    service.delete_income(income_id)
    return {"deleted": True, "income_id": income_id}


@mcp.tool()
def list_income(start_date: date | None = None, end_date: date | None = None, limit: int = 200) -> dict[str, Any]:
    """List persisted income events, optionally filtered by inclusive dates."""
    records = service.list_income(start_date=start_date, end_date=end_date, limit=limit)
    return {"income": [dump(record) for record in records], "count": len(records)}


@mcp.tool()
def get_monthly_income(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Calculate monthly income from every stored income event, not just salary."""
    return service.monthly_income(year, month)


@mcp.tool()
def calculate_monthly_cashflow(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Calculate required expenses, available cash, and any shortfall from profile plus stored income."""
    return service.calculate_monthly_cashflow(year, month)


@mcp.tool()
def calculate_investable_amount(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Calculate the amount left after living costs, debt, and required emergency-fund contribution."""
    return service.calculate_investable_amount(year, month)


@mcp.tool()
def calculate_asset_allocation(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Return deterministic, versioned asset-class allocation from the saved profile and monthly income."""
    return service.calculate_asset_allocation(year, month)


@mcp.tool()
def create_monthly_financial_plan(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Persist an immutable, auditable monthly plan snapshot based on current saved data."""
    return {"created": True, "plan": dump(service.create_monthly_financial_plan(year, month))}


@mcp.tool()
def get_monthly_financial_plan(
    year: int | None = None, month: int | None = None, plan_id: int | None = None
) -> dict[str, Any]:
    """Get the latest plan and immutable plan history for a month, or one plan by ID."""
    return service.get_monthly_financial_plan(year=year, month=month, plan_id=plan_id)


@mcp.tool()
def get_monthly_financial_summary(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Return monthly cashflow, actual spending, budget comparison, and latest saved plan."""
    return service.get_monthly_financial_summary(year, month)


@mcp.tool()
def create_trip(
    name: str,
    start_date: date,
    end_date: date,
    destination_country: str | None = None,
    destination_city: str | None = None,
    local_currency: str = "KRW",
    timezone: str = "Asia/Seoul",
    budget_mode: TripBudgetMode = TripBudgetMode.RELAXED,
    planned_budget_krw: int | None = None,
    reserved_cash_krw: int = 0,
) -> dict[str, Any]:
    """Create a planned trip before departure; STRICT requires an explicit KRW budget."""
    trip = service.create_trip(
        TripCreate(
            name=name,
            destination_country=destination_country,
            destination_city=destination_city,
            local_currency=local_currency,
            timezone=timezone,
            start_date=start_date,
            end_date=end_date,
            budget_mode=budget_mode,
            planned_budget_krw=planned_budget_krw,
            reserved_cash_krw=reserved_cash_krw,
        )
    )
    return {"created": True, "trip": dump(trip)}


@mcp.tool()
def update_trip(
    trip_id: int,
    name: str | None = None,
    destination_country: str | None = None,
    destination_city: str | None = None,
    local_currency: str | None = None,
    timezone: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    budget_mode: TripBudgetMode | None = None,
    planned_budget_krw: int | None = None,
    reserved_cash_krw: int | None = None,
) -> dict[str, Any]:
    """Update mutable trip details; use start_trip, end_trip, or cancel_trip for status changes."""
    trip = service.update_trip(
        trip_id,
        TripUpdate(
            name=name,
            destination_country=destination_country,
            destination_city=destination_city,
            local_currency=local_currency,
            timezone=timezone,
            start_date=start_date,
            end_date=end_date,
            budget_mode=budget_mode,
            planned_budget_krw=planned_budget_krw,
            reserved_cash_krw=reserved_cash_krw,
        ),
    )
    return {"updated": True, "trip": dump(trip)}


@mcp.tool()
def start_trip(trip_id: int | None = None) -> dict[str, Any]:
    """Activate a planned trip. Omit trip_id only when one eligible planned trip exists."""
    return {"started": True, "trip": dump(service.start_trip(trip_id))}


@mcp.tool()
def end_trip(trip_id: int | None = None) -> dict[str, Any]:
    """Complete the active trip and disable travel mode."""
    return {"completed": True, "trip": dump(service.end_trip(trip_id))}


@mcp.tool()
def cancel_trip(trip_id: int) -> dict[str, Any]:
    """Cancel a planned trip without deleting its financial audit record."""
    return {"cancelled": True, "trip": dump(service.cancel_trip(trip_id))}


@mcp.tool()
def get_active_trip() -> dict[str, Any]:
    """Check whether travel mode is active and return its trip context."""
    trip = service.get_active_trip()
    return {"active": trip is not None, "trip": dump(trip) if trip else None}


@mcp.tool()
def get_trip(trip_id: int) -> dict[str, Any]:
    """Get one trip by ID."""
    return {"trip": dump(service.get_trip(trip_id))}


@mcp.tool()
def list_trips(status: TripStatus | None = None, limit: int = 100) -> dict[str, Any]:
    """List planned, active, completed, or cancelled trips."""
    trips = service.list_trips(status=status, limit=limit)
    return {"trips": [dump(trip) for trip in trips], "count": len(trips)}


@mcp.tool()
def set_trip_budget(
    trip_id: int, budget_mode: TripBudgetMode, planned_budget_krw: int | None = None
) -> dict[str, Any]:
    """Set NONE, RELAXED, or STRICT travel budgeting; only STRICT requires a KRW budget."""
    return {"updated": True, "trip": dump(service.set_trip_budget(trip_id, budget_mode, planned_budget_krw))}


@mcp.tool()
def set_trip_cash_reserve(trip_id: int, reserved_cash_krw: int) -> dict[str, Any]:
    """Set a planned-trip reserve deducted only in the trip's start month."""
    return {"updated": True, "trip": dump(service.set_trip_cash_reserve(trip_id, reserved_cash_krw))}


@mcp.tool()
def add_travel_expense(
    original_amount: Decimal,
    original_currency: str,
    category: ExpenseCategory | None = None,
    merchant: str | None = None,
    occurred_at: datetime | None = None,
    memo: str | None = None,
    trip_id: int | None = None,
    place_name: str | None = None,
    address: str | None = None,
    latitude: Decimal | None = None,
    longitude: Decimal | None = None,
) -> dict[str, Any]:
    """Save one active-trip expense with original currency and an immutable rate snapshot when available."""
    expense = service.add_travel_expense(
        TravelExpenseCreate(
            original_amount=original_amount,
            original_currency=original_currency,
            category=category,
            merchant=merchant,
            occurred_at=occurred_at,
            memo=memo,
            trip_id=trip_id,
            place_name=place_name,
            address=address,
            latitude=latitude,
            longitude=longitude,
        )
    )
    return {"saved": True, "expense": expense}


@mcp.tool()
def add_travel_expenses(expenses: list[TravelExpenseCreate]) -> dict[str, Any]:
    """Atomically save several active-trip expenses while reusing cached same-day rates."""
    records = service.add_travel_expenses(expenses)
    return {"saved": True, "count": len(records), "expenses": records}


@mcp.tool()
def reconcile_travel_expense(expense_id: int, settled_amount_krw: int) -> dict[str, Any]:
    """Store a confirmed card settlement amount while retaining the original foreign-currency quote."""
    return {"reconciled": True, "expense": dump(service.reconcile_travel_expense(expense_id, settled_amount_krw))}


@mcp.tool()
def get_trip_spending_summary(trip_id: int) -> dict[str, Any]:
    """Return trip totals in KRW plus separate original-currency totals and neutral budget status."""
    return service.get_trip_spending_summary(trip_id)


@mcp.tool()
def get_trip_category_summary(trip_id: int) -> dict[str, Any]:
    """Return database-backed travel spending grouped by normal expense category."""
    return {"items": service.get_trip_category_summary(trip_id)}


@mcp.tool()
def get_trip_daily_summary(trip_id: int) -> dict[str, Any]:
    """Return database-backed travel spending grouped by local accounting day."""
    return {"items": service.get_trip_daily_summary(trip_id)}


@mcp.tool()
def get_trip_expenses(trip_id: int, limit: int = 500) -> dict[str, Any]:
    """List detailed travel expenses, including unresolved and manually located entries."""
    expenses = service.get_trip_expenses(trip_id, limit=limit)
    return {"expenses": expenses, "count": len(expenses)}


@mcp.tool()
def get_trip_map_data(trip_id: int) -> dict[str, Any]:
    """Return confirmed-coordinate markers for a Streamlit trip spending map; never invent coordinates."""
    return service.get_trip_map_data(trip_id)


@mcp.tool()
def get_exchange_rate(source_currency: str, rate_date: date | None = None) -> dict[str, Any]:
    """Get a provider-backed KRW quote; use the returned metadata instead of mental arithmetic."""
    return dump(service.get_exchange_rate(source_currency, rate_date))


@mcp.tool()
def convert_currency(amount: Decimal, source_currency: str, rate_date: date | None = None) -> dict[str, Any]:
    """Convert an amount to KRW using an actual cached or provider quote, never a fabricated rate."""
    return service.convert_currency(amount, source_currency, rate_date)


@mcp.tool()
def get_supported_currencies(rate_date: date | None = None) -> dict[str, Any]:
    """List currencies currently supported by the configured exchange-rate provider."""
    currencies = service.get_supported_currencies(rate_date)
    return {"currencies": currencies, "count": len(currencies)}


@mcp.tool()
def refresh_pending_currency_conversions(limit: int = 200) -> dict[str, Any]:
    """Retry trustworthy conversion of stored pending foreign expenses after provider recovery."""
    return service.refresh_pending_currency_conversions(limit)


@mcp.tool()
def set_expense_location(
    expense_id: int,
    latitude: Decimal,
    longitude: Decimal,
    place_name: str | None = None,
    address: str | None = None,
) -> dict[str, Any]:
    """Attach a user-confirmed coordinate to a travel expense for the map."""
    return {
        "saved": True,
        "location": service.set_expense_location(
            expense_id,
            ExpenseLocationUpsert(
                place_name=place_name, address=address, latitude=latitude, longitude=longitude
            ),
        ),
    }


@mcp.tool()
def delete_expense_location(expense_id: int) -> dict[str, Any]:
    """Delete only optional travel location metadata and keep the financial expense."""
    return {"deleted": service.delete_expense_location(expense_id), "expense_id": expense_id}


def main() -> None:
    """Run the finance MCP server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
