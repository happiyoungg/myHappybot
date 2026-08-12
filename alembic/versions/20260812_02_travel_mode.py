"""Add travel mode, foreign-exchange snapshots, and optional expense locations.

Revision ID: 20260812_02
Revises: 20260812_01
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260812_02"
down_revision = "20260812_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create travel tables and backfill legacy KRW expenses safely."""
    op.create_table(
        "trips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("destination_country", sa.String(length=100), nullable=True),
        sa.Column("destination_city", sa.String(length=100), nullable=True),
        sa.Column("local_currency", sa.String(length=3), nullable=False, server_default="KRW"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Asia/Seoul"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PLANNED"),
        sa.Column("budget_mode", sa.String(length=20), nullable=False, server_default="RELAXED"),
        sa.Column("planned_budget_krw", sa.Integer(), nullable=True),
        sa.Column("reserved_cash_krw", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_trips_one_active", "trips", ["status"], unique=True, sqlite_where=sa.text("status = 'ACTIVE'")
    )
    op.create_table(
        "exchange_rate_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("source_currency", sa.String(length=3), nullable=False),
        sa.Column("target_currency", sa.String(length=3), nullable=False, server_default="KRW"),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate_per_source_unit", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("quoted_unit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_exchange_rate_cache_quote",
        "exchange_rate_cache",
        ["provider", "source_currency", "target_currency", "rate_date"],
        unique=True,
    )
    op.add_column("expenses", sa.Column("spending_context", sa.String(length=10), nullable=False, server_default="NORMAL"))
    op.add_column("expenses", sa.Column("trip_id", sa.Integer(), nullable=True))
    op.add_column("expenses", sa.Column("original_amount", sa.Numeric(precision=20, scale=6), nullable=False, server_default="0"))
    op.add_column("expenses", sa.Column("original_currency", sa.String(length=3), nullable=False, server_default="KRW"))
    op.add_column("expenses", sa.Column("estimated_amount_krw", sa.Integer(), nullable=True))
    op.add_column("expenses", sa.Column("settled_amount_krw", sa.Integer(), nullable=True))
    op.add_column("expenses", sa.Column("exchange_rate", sa.Numeric(precision=24, scale=10), nullable=True))
    op.add_column("expenses", sa.Column("exchange_rate_date", sa.Date(), nullable=True))
    op.add_column("expenses", sa.Column("exchange_rate_provider", sa.String(length=50), nullable=True))
    op.add_column("expenses", sa.Column("exchange_rate_unit", sa.Integer(), nullable=True))
    op.add_column("expenses", sa.Column("conversion_status", sa.String(length=20), nullable=False, server_default="COMPLETED"))
    op.add_column("expenses", sa.Column("settlement_status", sa.String(length=20), nullable=False, server_default="SETTLED"))
    op.add_column("expenses", sa.Column("occurred_at_utc", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE expenses SET original_amount = amount, original_currency = 'KRW', "
        "estimated_amount_krw = amount, settled_amount_krw = amount, exchange_rate = 1, "
        "exchange_rate_date = occurred_at, exchange_rate_provider = 'identity', exchange_rate_unit = 1"
    )
    op.create_table(
        "expense_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("expense_id", sa.Integer(), sa.ForeignKey("expenses.id"), nullable=False, unique=True),
        sa.Column("place_name", sa.String(length=200), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=10, scale=7), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=10, scale=7), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("provider_place_id", sa.String(length=100), nullable=True),
        sa.Column("location_confidence", sa.String(length=30), nullable=False, server_default="user_confirmed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Remove travel-mode schema while retaining the original expense columns."""
    op.drop_table("expense_locations")
    with op.batch_alter_table("expenses") as batch:
        batch.drop_column("occurred_at_utc")
        batch.drop_column("settlement_status")
        batch.drop_column("conversion_status")
        batch.drop_column("exchange_rate_unit")
        batch.drop_column("exchange_rate_provider")
        batch.drop_column("exchange_rate_date")
        batch.drop_column("exchange_rate")
        batch.drop_column("settled_amount_krw")
        batch.drop_column("estimated_amount_krw")
        batch.drop_column("original_currency")
        batch.drop_column("original_amount")
        batch.drop_column("trip_id")
        batch.drop_column("spending_context")
    op.drop_index("uq_exchange_rate_cache_quote", table_name="exchange_rate_cache")
    op.drop_table("exchange_rate_cache")
    op.drop_index("ix_trips_one_active", table_name="trips")
    op.drop_table("trips")
