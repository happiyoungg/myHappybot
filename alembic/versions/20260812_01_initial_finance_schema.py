"""Create the personal finance MVP schema.

Revision ID: 20260812_01
Revises:
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "20260812_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("default_currency", sa.String(length=3), nullable=False),
        sa.Column("monthly_fixed_expenses", sa.Integer(), nullable=False),
        sa.Column("monthly_variable_budget", sa.Integer(), nullable=False),
        sa.Column("emergency_fund_target_months", sa.Integer(), nullable=False),
        sa.Column("current_emergency_fund", sa.Integer(), nullable=False),
        sa.Column("current_cash", sa.Integer(), nullable=False),
        sa.Column("monthly_debt_payment", sa.Integer(), nullable=False),
        sa.Column("risk_profile", sa.String(length=20), nullable=False),
        sa.Column("investment_horizon_years", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "incomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("occurred_at", sa.Date(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("merchant", sa.String(length=100), nullable=True),
        sa.Column("occurred_at", sa.Date(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "monthly_financial_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("income", sa.Integer(), nullable=False),
        sa.Column("fixed_expenses", sa.Integer(), nullable=False),
        sa.Column("variable_budget", sa.Integer(), nullable=False),
        sa.Column("debt_payment", sa.Integer(), nullable=False),
        sa.Column("emergency_fund_contribution", sa.Integer(), nullable=False),
        sa.Column("investable_amount", sa.Integer(), nullable=False),
        sa.Column("asset_allocation", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("calculation_policy_version", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("monthly_financial_plans")
    op.drop_table("expenses")
    op.drop_table("incomes")
    op.drop_table("user_profiles")
