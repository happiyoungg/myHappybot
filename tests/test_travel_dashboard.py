"""Smoke test for the Streamlit travel dashboard integration."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from streamlit.testing.v1 import AppTest


def test_travel_dashboard_tab_renders_with_migrated_database(tmp_path, monkeypatch):
    """Render the dashboard without exceptions and expose the travel tab."""
    database_url = f"sqlite:///{(tmp_path / 'dashboard.sqlite3').as_posix()}"
    monkeypatch.setenv("PERSONAL_FINANCE_DATABASE_URL", database_url)
    root = Path(__file__).resolve().parents[1]
    command.upgrade(Config(str(root / "alembic.ini")), "head")

    app = AppTest.from_file(str(root / "app.py")).run(timeout=30)
    assert not app.exception
    assert any(tab.label == "여행" for tab in app.tabs)
