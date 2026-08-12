"""Application settings that do not belong to domain logic."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "personal_finance.sqlite3"


def database_url() -> str:
    """Return the configured SQLite URL without creating any database."""
    return os.getenv("PERSONAL_FINANCE_DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE_PATH}")
