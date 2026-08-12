"""Migration coverage for legacy normal KRW expense backfill."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine


def test_travel_migration_preserves_and_backfills_legacy_expense(tmp_path, monkeypatch):
    """Upgrade an initial-schema database without losing an existing expense."""
    database_path = tmp_path / "legacy.sqlite3"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("PERSONAL_FINANCE_DATABASE_URL", database_url)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))

    command.upgrade(config, "20260812_01")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO expenses (amount, category, merchant, occurred_at, memo, created_at, updated_at) "
            "VALUES (9000, '식비', NULL, '2026-08-12', NULL, '2026-08-12 00:00:00', '2026-08-12 00:00:00')"
        )

    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT amount, spending_context, trip_id, original_amount, original_currency, "
            "estimated_amount_krw, settled_amount_krw, conversion_status, settlement_status FROM expenses"
        ).one()
    assert tuple(row) == (9000, "NORMAL", None, 9000, "KRW", 9000, 9000, "COMPLETED", "SETTLED")
