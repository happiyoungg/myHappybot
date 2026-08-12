"""Repository layer; all SQLAlchemy queries live here."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .models import (
    ExchangeRateCacheModel,
    ExpenseLocationModel,
    ExpenseModel,
    IncomeModel,
    MonthlyFinancialPlanModel,
    TripModel,
    UserProfileModel,
)


class NotFoundError(ValueError):
    """Raised when a persisted record does not exist."""


class ProfileRepository:
    def get(self, session: Session) -> UserProfileModel | None:
        return session.scalar(select(UserProfileModel).order_by(UserProfileModel.id).limit(1))

    def create(self, session: Session, data: dict[str, Any]) -> UserProfileModel:
        profile = UserProfileModel(**data)
        session.add(profile)
        session.flush()
        return profile

    def update(self, session: Session, profile: UserProfileModel, data: dict[str, Any]) -> UserProfileModel:
        for field, value in data.items():
            setattr(profile, field, value)
        session.flush()
        return profile


class ExpenseRepository:
    def create(self, session: Session, data: dict[str, Any]) -> ExpenseModel:
        expense = ExpenseModel(**data)
        session.add(expense)
        session.flush()
        return expense

    def get(self, session: Session, expense_id: int) -> ExpenseModel:
        expense = session.get(ExpenseModel, expense_id)
        if expense is None:
            raise NotFoundError(f"Expense {expense_id} was not found.")
        return expense

    def update(self, session: Session, expense: ExpenseModel, data: dict[str, Any]) -> ExpenseModel:
        for field, value in data.items():
            setattr(expense, field, value)
        session.flush()
        return expense

    def delete(self, session: Session, expense: ExpenseModel) -> None:
        session.delete(expense)
        session.flush()

    def list(
        self,
        session: Session,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        category: str | None = None,
        spending_context: str | None = None,
        trip_id: int | None = None,
        limit: int = 200,
    ) -> list[ExpenseModel]:
        statement: Select[tuple[ExpenseModel]] = select(ExpenseModel)
        if start_date:
            statement = statement.where(ExpenseModel.occurred_at >= start_date)
        if end_date:
            statement = statement.where(ExpenseModel.occurred_at <= end_date)
        if category:
            statement = statement.where(ExpenseModel.category == category)
        if spending_context:
            statement = statement.where(ExpenseModel.spending_context == spending_context)
        if trip_id is not None:
            statement = statement.where(ExpenseModel.trip_id == trip_id)
        statement = statement.order_by(ExpenseModel.occurred_at.desc(), ExpenseModel.id.desc()).limit(limit)
        return list(session.scalars(statement))

    def total_by_category(
        self, session: Session, start_date: date, end_date: date, *, spending_context: str | None = None, trip_id: int | None = None
    ) -> list[tuple[str, int]]:
        statement = (
            select(ExpenseModel.category, func.coalesce(func.sum(ExpenseModel.amount), 0))
            .where(ExpenseModel.occurred_at.between(start_date, end_date))
            .group_by(ExpenseModel.category)
            .order_by(func.sum(ExpenseModel.amount).desc())
        )
        if spending_context:
            statement = statement.where(ExpenseModel.spending_context == spending_context)
        if trip_id is not None:
            statement = statement.where(ExpenseModel.trip_id == trip_id)
        return [(category, int(amount)) for category, amount in session.execute(statement).all()]

    def total(
        self, session: Session, start_date: date, end_date: date, *, spending_context: str | None = None, trip_id: int | None = None
    ) -> int:
        statement = select(func.coalesce(func.sum(ExpenseModel.amount), 0)).where(
            ExpenseModel.occurred_at.between(start_date, end_date)
        )
        if spending_context:
            statement = statement.where(ExpenseModel.spending_context == spending_context)
        if trip_id is not None:
            statement = statement.where(ExpenseModel.trip_id == trip_id)
        return int(session.scalar(statement) or 0)

    def list_pending_conversions(self, session: Session, *, limit: int = 200) -> list[ExpenseModel]:
        """Return travel expenses that await a trustworthy foreign-exchange quote."""
        statement = (
            select(ExpenseModel)
            .where(ExpenseModel.spending_context == "TRAVEL", ExpenseModel.conversion_status == "PENDING")
            .order_by(ExpenseModel.occurred_at.asc(), ExpenseModel.id.asc())
            .limit(limit)
        )
        return list(session.scalars(statement))


class IncomeRepository:
    def create(self, session: Session, data: dict[str, Any]) -> IncomeModel:
        income = IncomeModel(**data)
        session.add(income)
        session.flush()
        return income

    def get(self, session: Session, income_id: int) -> IncomeModel:
        income = session.get(IncomeModel, income_id)
        if income is None:
            raise NotFoundError(f"Income {income_id} was not found.")
        return income

    def update(self, session: Session, income: IncomeModel, data: dict[str, Any]) -> IncomeModel:
        for field, value in data.items():
            setattr(income, field, value)
        session.flush()
        return income

    def delete(self, session: Session, income: IncomeModel) -> None:
        session.delete(income)
        session.flush()

    def list(
        self,
        session: Session,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 200,
    ) -> list[IncomeModel]:
        statement: Select[tuple[IncomeModel]] = select(IncomeModel)
        if start_date:
            statement = statement.where(IncomeModel.occurred_at >= start_date)
        if end_date:
            statement = statement.where(IncomeModel.occurred_at <= end_date)
        statement = statement.order_by(IncomeModel.occurred_at.desc(), IncomeModel.id.desc()).limit(limit)
        return list(session.scalars(statement))

    def total(self, session: Session, start_date: date, end_date: date) -> int:
        statement = select(func.coalesce(func.sum(IncomeModel.amount), 0)).where(
            IncomeModel.occurred_at.between(start_date, end_date)
        )
        return int(session.scalar(statement) or 0)


class PlanRepository:
    def create(self, session: Session, data: dict[str, Any]) -> MonthlyFinancialPlanModel:
        plan = MonthlyFinancialPlanModel(**data)
        session.add(plan)
        session.flush()
        return plan

    def list(self, session: Session, *, year: int | None = None, month: int | None = None) -> list[MonthlyFinancialPlanModel]:
        statement: Select[tuple[MonthlyFinancialPlanModel]] = select(MonthlyFinancialPlanModel)
        if year is not None:
            statement = statement.where(MonthlyFinancialPlanModel.year == year)
        if month is not None:
            statement = statement.where(MonthlyFinancialPlanModel.month == month)
        statement = statement.order_by(MonthlyFinancialPlanModel.created_at.desc(), MonthlyFinancialPlanModel.id.desc())
        return list(session.scalars(statement))

    def get(self, session: Session, plan_id: int) -> MonthlyFinancialPlanModel:
        plan = session.get(MonthlyFinancialPlanModel, plan_id)
        if plan is None:
            raise NotFoundError(f"Monthly financial plan {plan_id} was not found.")
        return plan


class TripRepository:
    """Persistence operations for travel lifecycle records."""

    def create(self, session: Session, data: dict[str, Any]) -> TripModel:
        trip = TripModel(**data)
        session.add(trip)
        session.flush()
        return trip

    def get(self, session: Session, trip_id: int) -> TripModel:
        trip = session.get(TripModel, trip_id)
        if trip is None:
            raise NotFoundError(f"Trip {trip_id} was not found.")
        return trip

    def update(self, session: Session, trip: TripModel, data: dict[str, Any]) -> TripModel:
        for field, value in data.items():
            setattr(trip, field, value)
        session.flush()
        return trip

    def get_active(self, session: Session) -> TripModel | None:
        return session.scalar(select(TripModel).where(TripModel.status == "ACTIVE").limit(1))

    def list(self, session: Session, *, status: str | None = None, limit: int = 100) -> list[TripModel]:
        statement: Select[tuple[TripModel]] = select(TripModel)
        if status:
            statement = statement.where(TripModel.status == status)
        statement = statement.order_by(TripModel.start_date.desc(), TripModel.id.desc()).limit(limit)
        return list(session.scalars(statement))

    def planned_starting_in_month(self, session: Session, start_date: date, end_date: date) -> list[TripModel]:
        statement = select(TripModel).where(
            TripModel.status == "PLANNED", TripModel.start_date.between(start_date, end_date)
        )
        return list(session.scalars(statement))


class ExchangeRateCacheRepository:
    """Persistence operations for normalized historical exchange quotes."""

    def get(
        self, session: Session, *, provider: str, source_currency: str, target_currency: str, rate_date: date
    ) -> ExchangeRateCacheModel | None:
        statement = select(ExchangeRateCacheModel).where(
            ExchangeRateCacheModel.provider == provider,
            ExchangeRateCacheModel.source_currency == source_currency,
            ExchangeRateCacheModel.target_currency == target_currency,
            ExchangeRateCacheModel.rate_date == rate_date,
        )
        return session.scalar(statement)

    def latest_on_or_before(
        self, session: Session, *, provider: str, source_currency: str, target_currency: str, earliest_date: date, latest_date: date
    ) -> ExchangeRateCacheModel | None:
        statement = (
            select(ExchangeRateCacheModel)
            .where(
                ExchangeRateCacheModel.provider == provider,
                ExchangeRateCacheModel.source_currency == source_currency,
                ExchangeRateCacheModel.target_currency == target_currency,
                ExchangeRateCacheModel.rate_date.between(earliest_date, latest_date),
            )
            .order_by(ExchangeRateCacheModel.rate_date.desc())
            .limit(1)
        )
        return session.scalar(statement)

    def create(self, session: Session, data: dict[str, Any]) -> ExchangeRateCacheModel:
        record = ExchangeRateCacheModel(**data)
        session.add(record)
        session.flush()
        return record


class ExpenseLocationRepository:
    """Persistence operations for optional manually confirmed locations."""

    def get(self, session: Session, expense_id: int) -> ExpenseLocationModel | None:
        return session.scalar(select(ExpenseLocationModel).where(ExpenseLocationModel.expense_id == expense_id))

    def upsert(self, session: Session, expense_id: int, data: dict[str, Any]) -> ExpenseLocationModel:
        location = self.get(session, expense_id)
        if location is None:
            location = ExpenseLocationModel(expense_id=expense_id, **data)
            session.add(location)
        else:
            for field, value in data.items():
                setattr(location, field, value)
        session.flush()
        return location

    def delete(self, session: Session, expense_id: int) -> bool:
        location = self.get(session, expense_id)
        if location is None:
            return False
        session.delete(location)
        session.flush()
        return True
