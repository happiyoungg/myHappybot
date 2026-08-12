from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from personal_finance.schemas import ExpenseCategory, ExpenseCreate, ExpenseUpdate, IncomeCreate, IncomeUpdate


def test_expense_crud_month_filter_and_category_aggregation(service):
    food = service.add_expense(
        ExpenseCreate(amount=9_000, category=ExpenseCategory.FOOD, occurred_at=date(2026, 8, 12), memo="점심")
    )
    service.add_expenses(
        [
            ExpenseCreate(amount=4_500, category=ExpenseCategory.CAFE, occurred_at=date(2026, 8, 12), memo="커피"),
            ExpenseCreate(amount=12_000, category=ExpenseCategory.FOOD, occurred_at=date(2026, 8, 13)),
        ]
    )
    service.add_expense(ExpenseCreate(amount=30_000, category=ExpenseCategory.HOUSING, occurred_at=date(2026, 7, 31)))

    updated = service.update_expense(food.id, ExpenseUpdate(amount=10_000, merchant="식당"))
    assert updated.amount == 10_000
    assert updated.merchant == "식당"

    august = service.get_monthly_expenses(2026, 8)
    assert len(august) == 3
    assert [item.category.value for item in august].count("식비") == 2
    assert updated.id in {item.id for item in service.get_daily_expenses(date(2026, 8, 12))}

    totals = {item["category"]: item["amount"] for item in service.spending_by_category(2026, 8)}
    assert totals == {"식비": 22_000, "카페": 4_500}
    summary = service.monthly_spending_summary(2026, 8)
    assert summary["total_spending"] == 26_500

    service.delete_expense(updated.id)
    assert len(service.get_monthly_expenses(2026, 8)) == 2


def test_expense_validation_and_uncertain_category_fallback(service):
    with pytest.raises(ValidationError):
        ExpenseCreate(amount=-1, occurred_at=date(2026, 8, 1))

    expense = service.add_expense(ExpenseCreate(amount=1, category=None, occurred_at=date(2026, 8, 1)))
    assert expense.category == ExpenseCategory.OTHER


def test_income_crud_multiple_events_and_month_total(service):
    first = service.record_income(IncomeCreate(amount=3_200_000, source="급여", occurred_at=date(2026, 8, 1)))
    service.record_income(IncomeCreate(amount=100_000, source="부수입", occurred_at=date(2026, 8, 20)))
    service.record_income(IncomeCreate(amount=50_000, source="지난달", occurred_at=date(2026, 7, 30)))

    updated = service.update_income(first.id, IncomeUpdate(amount=3_300_000, memo="8월 급여"))
    assert updated.amount == 3_300_000
    assert service.monthly_income(2026, 8)["total_income"] == 3_400_000
    assert len(service.list_income(start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))) == 2

    service.delete_income(first.id)
    assert service.monthly_income(2026, 8)["total_income"] == 100_000
