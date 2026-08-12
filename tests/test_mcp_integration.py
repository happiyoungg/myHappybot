from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

from personal_finance.db import create_database_engine
from personal_finance.models import Base


def test_finance_mcp_tools_persist_and_create_plan(database_url):
    """Exercise the actual stdio MCP boundary, including a failed batch write."""
    Base.metadata.create_all(create_database_engine(database_url))
    root = Path(__file__).resolve().parents[1]

    async def call(session, name, arguments):
        result = await session.call_tool(name, arguments)
        text = "".join(getattr(content, "text", "") for content in result.content)
        return result.isError, text

    async def scenario():
        client = MultiServerMCPClient(
            {
                "finance": {
                    "command": sys.executable,
                    "args": [str(root / "finance_server.py")],
                    "env": {
                        "PYTHONPATH": str(root / "src"),
                        "PERSONAL_FINANCE_DATABASE_URL": database_url,
                    },
                    "transport": "stdio",
                }
            }
        )
        async with client.session("finance") as session:
            tools = await session.list_tools()
            assert any(tool.name == "create_monthly_financial_plan" for tool in tools.tools)
            assert any(tool.name == "add_travel_expense" for tool in tools.tools)

            error, _ = await call(
                session,
                "add_expenses",
                {
                    "expenses": [
                        {"amount": 9_000, "occurred_at": "2026-08-12"},
                        {"amount": -1, "occurred_at": "2026-08-12"},
                    ]
                },
            )
            assert error
            error, text = await call(session, "get_monthly_expenses", {"year": 2026, "month": 8})
            assert not error
            assert json.loads(text)["count"] == 0

            error, text = await call(
                session,
                "add_expenses",
                {
                    "expenses": [
                        {"amount": 9_000, "occurred_at": "2026-08-12"},
                        {"amount": 4_500, "occurred_at": "2026-08-12"},
                    ]
                },
            )
            assert not error, text
            error, text = await call(session, "get_monthly_expenses", {"year": 2026, "month": 8})
            assert not error
            assert json.loads(text)["count"] == 2

            error, text = await call(
                session,
                "save_financial_profile",
                {
                    "name": "MCP Test",
                    "monthly_fixed_expenses": 1_000_000,
                    "monthly_variable_budget": 500_000,
                    "current_emergency_fund": 4_500_000,
                },
            )
            assert not error, text
            error, text = await call(
                session,
                "record_income",
                {"amount": 3_200_000, "source": "salary", "occurred_at": "2026-08-01"},
            )
            assert not error, text
            error, text = await call(session, "create_monthly_financial_plan", {"year": 2026, "month": 8})
            assert not error, text
            plan = json.loads(text)["plan"]

            error, text = await call(
                session,
                "create_trip",
                {
                    "name": "MCP Tokyo",
                    "local_currency": "JPY",
                    "timezone": "Asia/Tokyo",
                    "start_date": "2026-08-20",
                    "end_date": "2026-08-24",
                },
            )
            assert not error, text
            trip_id = json.loads(text)["trip"]["id"]
            error, text = await call(session, "start_trip", {"trip_id": trip_id})
            assert not error, text
            assert json.loads(text)["trip"]["status"] == "ACTIVE"
            error, text = await call(
                session,
                "add_travel_expense",
                {
                    "original_amount": "30000",
                    "original_currency": "KRW",
                    "occurred_at": "2026-08-20T12:00:00",
                    "merchant": "MCP restaurant",
                },
            )
            assert not error, text
            assert json.loads(text)["expense"]["amount"] == 30_000
            error, text = await call(session, "get_trip_spending_summary", {"trip_id": trip_id})
            assert not error, text
            assert json.loads(text)["total_amount_krw"] == 30_000
            error, text = await call(session, "end_trip", {"trip_id": trip_id})
            assert not error, text
        await asyncio.sleep(0.2)
        return plan

    plan = asyncio.run(scenario())
    assert plan["income"] == 3_200_000
    assert plan["investable_amount"] == 1_700_000
