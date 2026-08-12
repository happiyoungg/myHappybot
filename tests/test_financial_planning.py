from __future__ import annotations

from datetime import date

import pytest

from personal_finance.policy import ALLOCATION_PERCENTAGES, POLICY_VERSION
from personal_finance.schemas import IncomeCreate, ProfileCreate, ProfileUpdate, RiskProfile
from personal_finance.services import FinanceService, ProfileMissingError


def create_profile(service, *, risk_profile: RiskProfile = RiskProfile.BALANCED, emergency_fund: int = 0):
    return service.save_profile(
        ProfileCreate(
            name="테스터",
            monthly_fixed_expenses=1_000_000,
            monthly_variable_budget=500_000,
            monthly_debt_payment=200_000,
            emergency_fund_target_months=3,
            current_emergency_fund=emergency_fund,
            risk_profile=risk_profile,
            investment_horizon_years=10,
        )
    )


def test_profile_save_update_retrieve_and_missing_profile_error(service):
    with pytest.raises(ProfileMissingError):
        service.calculate_monthly_cashflow(2026, 8)

    created = create_profile(service)
    updated = service.update_profile(ProfileUpdate(monthly_variable_budget=600_000, risk_profile=RiskProfile.GROWTH))
    retrieved = service.get_profile()
    assert created.id == updated.id == retrieved.id
    assert retrieved.monthly_variable_budget == 600_000
    assert retrieved.risk_profile == RiskProfile.GROWTH


def test_cashflow_prioritizes_emergency_fund_and_never_goes_negative(service):
    create_profile(service, emergency_fund=1_000_000)
    service.record_income(IncomeCreate(amount=3_200_000, source="급여", occurred_at=date(2026, 8, 1)))
    cashflow = service.calculate_monthly_cashflow(2026, 8)

    assert cashflow["monthly_required_expenses"] == 1_700_000
    assert cashflow["emergency_fund_target"] == 5_100_000
    assert cashflow["emergency_fund_gap"] == 4_100_000
    assert cashflow["emergency_fund_contribution"] == 1_500_000
    assert cashflow["investable_amount"] == 0

    service.update_profile(ProfileUpdate(current_emergency_fund=5_100_000))
    allocation = service.calculate_asset_allocation(2026, 8)
    assert allocation["investable_amount"] == 1_500_000
    assert sum(item["amount"] for item in allocation["allocations"]) == 1_500_000

    service.update_profile(ProfileUpdate(current_emergency_fund=0))
    low_income = service.calculate_investable_amount(2026, 7)
    assert low_income["investable_amount"] == 0
    assert low_income["shortfall"] == 1_700_000


@pytest.mark.parametrize("risk_profile", list(RiskProfile))
def test_every_risk_profile_uses_policy_and_preserves_krw_rounding(service, risk_profile):
    create_profile(service, risk_profile=risk_profile, emergency_fund=5_100_000)
    service.record_income(IncomeCreate(amount=1_700_101, source="급여", occurred_at=date(2026, 8, 1)))

    allocation = service.calculate_asset_allocation(2026, 8)
    assert allocation["policy_version"] == POLICY_VERSION
    assert sum(item["percentage"] for item in allocation["allocations"]) == 100
    assert sum(item["amount"] for item in allocation["allocations"]) == 101
    assert [item["percentage"] for item in allocation["allocations"]] == [
        percentage for _, percentage in ALLOCATION_PERCENTAGES[risk_profile]
    ]


def test_monthly_plan_is_immutable_and_persists_across_service_sessions(service):
    create_profile(service, emergency_fund=5_100_000)
    service.record_income(IncomeCreate(amount=3_200_000, source="급여", occurred_at=date(2026, 8, 1)))
    first = service.create_monthly_financial_plan(2026, 8)
    second = service.create_monthly_financial_plan(2026, 8)

    restarted_service = FinanceService(service.session_factory)
    history = restarted_service.get_monthly_financial_plan(year=2026, month=8)
    assert first.id != second.id
    assert len(history["history"]) == 2
    assert history["plan"]["calculation_policy_version"] == POLICY_VERSION
