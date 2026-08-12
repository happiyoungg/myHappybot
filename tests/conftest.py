from __future__ import annotations

import pytest

from personal_finance.db import create_database_engine, create_session_factory
from personal_finance.models import Base
from personal_finance.services import FinanceService


@pytest.fixture
def database_url(tmp_path):
    return f"sqlite:///{(tmp_path / 'finance.sqlite3').as_posix()}"


@pytest.fixture
def service(database_url):
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    return FinanceService(create_session_factory(database_url))
