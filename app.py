"""Streamlit host for the learning MCP tools and personal-finance dashboard."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
KOREAN_CATEGORIES = ["식비", "카페", "교통", "쇼핑", "주거", "통신", "구독", "문화", "여행", "의료", "기타"]
RISK_OPTIONS = {"보수형": "conservative", "균형형": "balanced", "성장형": "growth"}
RISK_LABELS = {value: key for key, value in RISK_OPTIONS.items()}

FINANCE_AGENT_INSTRUCTIONS = """
You are a helpful Korean personal-finance assistant using MCP tools.
For any question or action involving expenses, income, financial profiles, monthly totals,
previous transactions, budget comparisons, cashflow, or asset allocation, call the relevant
MCP tool instead of relying on conversation memory or doing the arithmetic yourself.
Never say a record was saved unless the write tool returns saved=true. If a tool fails, clearly
state that the record was not saved. When expense category is unclear, save it as 기타.
For Korean relative dates such as 오늘, 어제, 이번 달, and 지난달, resolve the calendar date
in Asia/Seoul before calling a tool, except that an active trip uses its own timezone. When an
active trip exists, use add_travel_expense for foreign-currency purchases and retrieve the
active trip or a travel summary before answering travel-spending questions. Never invent an
exchange rate or coordinates. Travel spending is intentional: report factual totals and only
surface a budget warning when the trip is in STRICT mode. Asset allocations are educational, deterministic plans;
never promise returns, time markets, recommend individual securities, or execute trades.
Use the existing demo and real-estate tools only when they are relevant to the user request.
""".strip()


def _python_path_env() -> str:
    existing = os.getenv("PYTHONPATH", "")
    source_path = str(PROJECT_ROOT / "src")
    return source_path if not existing else source_path + os.pathsep + existing


def mcp_connections(include_realestate: bool = True) -> dict[str, dict[str, Any]]:
    """Build portable stdio connections without hard-coded user paths."""
    finance_environment = {"PYTHONPATH": _python_path_env()}
    for name in ("PERSONAL_FINANCE_DATABASE_URL", "KOREA_EXIM_API_KEY"):
        if os.getenv(name):
            finance_environment[name] = os.environ[name]
    connections: dict[str, dict[str, Any]] = {
        "demo": {
            "command": sys.executable,
            "args": [str(PROJECT_ROOT / "server.py")],
            "transport": "stdio",
        },
        "finance": {
            "command": sys.executable,
            "args": [str(PROJECT_ROOT / "finance_server.py")],
            "env": finance_environment,
            "transport": "stdio",
        },
    }
    if include_realestate and os.getenv("PUBLIC_DATA_API_KEY"):
        realestate_executable = Path(sys.executable).with_name("korea-realestate-mcp.exe")
        connections["realestate"] = {
            "command": str(realestate_executable),
            "args": [],
            "env": {"PUBLIC_DATA_API_KEY": os.getenv("PUBLIC_DATA_API_KEY", "")},
            "transport": "stdio",
        }
    return connections


async def run_agent(prompt: str) -> str:
    """Run a new agent turn with the currently available MCP tools."""
    client = MultiServerMCPClient(mcp_connections(), tool_name_prefix=True)
    tools = await client.get_tools()
    agent = create_agent("gpt-5.4-mini", tools, system_prompt=FINANCE_AGENT_INSTRUCTIONS)
    response = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    return str(response["messages"][-1].content)


async def call_finance_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call the finance server directly so dashboard and chat share one public API."""
    client = MultiServerMCPClient(mcp_connections(include_realestate=False))
    async with client.session("finance") as session:
        result = await session.call_tool(tool_name, arguments or {})
    if result.isError:
        message = " ".join(getattr(content, "text", "") for content in result.content)
        raise RuntimeError(message or f"Finance tool {tool_name} failed.")
    text_content = "".join(getattr(content, "text", "") for content in result.content)
    try:
        return json.loads(text_content)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Finance tool {tool_name} returned invalid JSON.") from error


def finance_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Synchronously bridge Streamlit callbacks to the asynchronous MCP client."""
    return asyncio.run(call_finance_tool(tool_name, arguments))


def korean_month_default() -> tuple[int, int]:
    now = datetime.now().astimezone()
    return now.year, now.month


def show_profile_editor(profile: dict[str, Any] | None) -> None:
    st.subheader("재무 프로필")
    if profile is None:
        st.info("프로필을 먼저 저장하면 예산 비교와 자산 배분을 계산할 수 있습니다.")
    risk_value = profile.get("risk_profile", "balanced") if profile else "balanced"
    risk_index = list(RISK_OPTIONS.values()).index(risk_value)
    with st.form("profile_form"):
        name = st.text_input("이름", value=profile.get("name", "") if profile else "")
        left, right = st.columns(2)
        with left:
            fixed = st.number_input("월 고정지출 (원)", min_value=0, step=10_000, value=int(profile.get("monthly_fixed_expenses", 0)) if profile else 0)
            variable = st.number_input("월 변동예산 (원)", min_value=0, step=10_000, value=int(profile.get("monthly_variable_budget", 0)) if profile else 0)
            debt = st.number_input("월 부채상환액 (원)", min_value=0, step=10_000, value=int(profile.get("monthly_debt_payment", 0)) if profile else 0)
        with right:
            emergency_months = st.number_input("비상금 목표 개월", min_value=1, max_value=24, value=int(profile.get("emergency_fund_target_months", 3)) if profile else 3)
            emergency_fund = st.number_input("현재 비상금 (원)", min_value=0, step=10_000, value=int(profile.get("current_emergency_fund", 0)) if profile else 0)
            cash = st.number_input("현재 현금 (원)", min_value=0, step=10_000, value=int(profile.get("current_cash", 0)) if profile else 0)
        risk_label = st.selectbox("위험성향", list(RISK_OPTIONS), index=risk_index)
        horizon = st.number_input("투자 기간 (년)", min_value=0, max_value=100, value=int(profile.get("investment_horizon_years", 0)) if profile else 0)
        submitted = st.form_submit_button("프로필 저장" if profile is None else "프로필 업데이트")
    if submitted:
        arguments = {
            "name": name,
            "monthly_fixed_expenses": fixed,
            "monthly_variable_budget": variable,
            "monthly_debt_payment": debt,
            "emergency_fund_target_months": emergency_months,
            "current_emergency_fund": emergency_fund,
            "current_cash": cash,
            "risk_profile": RISK_OPTIONS[risk_label],
            "investment_horizon_years": horizon,
        }
        if not name.strip():
            st.error("이름을 입력해 주세요.")
            return
        try:
            finance_tool("update_financial_profile" if profile else "save_financial_profile", arguments)
            st.success("재무 프로필을 저장했습니다.")
            st.rerun()
        except Exception as error:
            st.error(f"프로필을 저장하지 못했습니다: {error}")


def show_income_manager(year: int, month: int) -> None:
    st.subheader("수입 관리")
    with st.form("income_create_form", clear_on_submit=True):
        first, second = st.columns(2)
        with first:
            amount = st.number_input("수입 금액 (원)", min_value=1, step=10_000, key="income_amount")
            source = st.text_input("수입 출처", value="급여")
        with second:
            occurred_at = st.date_input("수입일", value=date(year, month, 1))
            memo = st.text_input("메모", key="income_memo")
        submitted = st.form_submit_button("수입 추가")
    if submitted:
        try:
            finance_tool("record_income", {"amount": amount, "source": source, "occurred_at": occurred_at.isoformat(), "memo": memo or None})
            st.success("수입을 저장했습니다.")
            st.rerun()
        except Exception as error:
            st.error(f"수입을 저장하지 못했습니다: {error}")

    income = finance_tool("get_monthly_income", {"year": year, "month": month})
    st.metric("이번 달 수입", f"{income['total_income']:,}원")
    for record in income["income_events"]:
        with st.expander(f"{record['occurred_at']} · {record['source']} · {record['amount']:,}원"):
            with st.form(f"income_edit_{record['id']}"):
                edit_amount = st.number_input("금액", min_value=1, value=record["amount"], step=10_000, key=f"income_amount_{record['id']}")
                edit_source = st.text_input("출처", value=record["source"], key=f"income_source_{record['id']}")
                edit_date = st.date_input("수입일", value=date.fromisoformat(record["occurred_at"]), key=f"income_date_{record['id']}")
                edit_memo = st.text_input("메모", value=record["memo"] or "", key=f"income_memo_{record['id']}")
                saved = st.form_submit_button("수정")
            if saved:
                try:
                    finance_tool("update_income", {"income_id": record["id"], "amount": edit_amount, "source": edit_source, "occurred_at": edit_date.isoformat(), "memo": edit_memo})
                    st.rerun()
                except Exception as error:
                    st.error(f"수입을 수정하지 못했습니다: {error}")
            if st.button("삭제", key=f"delete_income_{record['id']}"):
                try:
                    finance_tool("delete_income", {"income_id": record["id"]})
                    st.rerun()
                except Exception as error:
                    st.error(f"수입을 삭제하지 못했습니다: {error}")


def show_expense_manager(year: int, month: int) -> None:
    st.subheader("지출 관리")
    with st.form("expense_create_form", clear_on_submit=True):
        first, second = st.columns(2)
        with first:
            amount = st.number_input("지출 금액 (원)", min_value=1, step=1_000, key="expense_amount")
            category = st.selectbox("카테고리", KOREAN_CATEGORIES)
            merchant = st.text_input("가맹점")
        with second:
            occurred_at = st.date_input("지출일", value=date.today())
            memo = st.text_input("메모", key="expense_memo")
        submitted = st.form_submit_button("지출 추가")
    if submitted:
        try:
            finance_tool(
                "add_expense",
                {
                    "amount": amount,
                    "category": category,
                    "merchant": merchant or None,
                    "occurred_at": occurred_at.isoformat(),
                    "memo": memo or None,
                    "spending_context": "NORMAL",
                },
            )
            st.success("지출을 저장했습니다.")
            st.rerun()
        except Exception as error:
            st.error(f"지출을 저장하지 못했습니다: {error}")

    expenses = finance_tool("get_monthly_expenses", {"year": year, "month": month})["expenses"]
    for record in expenses:
        merchant_text = f" · {record['merchant']}" if record["merchant"] else ""
        with st.expander(f"{record['occurred_at']} · {record['category']}{merchant_text} · {record['amount']:,}원"):
            with st.form(f"expense_edit_{record['id']}"):
                edit_amount = st.number_input("금액", min_value=1, value=record["amount"], step=1_000, key=f"expense_amount_{record['id']}")
                edit_category = st.selectbox("카테고리", KOREAN_CATEGORIES, index=KOREAN_CATEGORIES.index(record["category"]), key=f"expense_category_{record['id']}")
                edit_merchant = st.text_input("가맹점", value=record["merchant"] or "", key=f"expense_merchant_{record['id']}")
                edit_date = st.date_input("지출일", value=date.fromisoformat(record["occurred_at"]), key=f"expense_date_{record['id']}")
                edit_memo = st.text_input("메모", value=record["memo"] or "", key=f"expense_memo_{record['id']}")
                saved = st.form_submit_button("수정")
            if saved:
                try:
                    finance_tool("update_expense", {"expense_id": record["id"], "amount": edit_amount, "category": edit_category, "merchant": edit_merchant, "occurred_at": edit_date.isoformat(), "memo": edit_memo})
                    st.rerun()
                except Exception as error:
                    st.error(f"지출을 수정하지 못했습니다: {error}")
            if st.button("삭제", key=f"delete_expense_{record['id']}"):
                try:
                    finance_tool("delete_expense", {"expense_id": record["id"]})
                    st.rerun()
                except Exception as error:
                    st.error(f"지출을 삭제하지 못했습니다: {error}")


def show_travel_manager() -> None:
    """Render trip lifecycle, travel expenses, and the optional spending map."""
    st.subheader("여행 모드")
    try:
        active_response = finance_tool("get_active_trip")
        trips_response = finance_tool("list_trips", {"limit": 100})
    except Exception as error:
        st.error(f"여행 정보를 불러오지 못했습니다: {error}")
        return

    active_trip = active_response["trip"]
    if active_trip:
        st.success(f"여행 모드 활성화: {active_trip['name']} · {active_trip['timezone']}")
    else:
        st.info("활성 여행이 없습니다. 계획을 만들거나 예정된 여행을 시작해 주세요.")

    with st.expander("새 여행 만들기", expanded=not trips_response["trips"]):
        with st.form("trip_create_form", clear_on_submit=True):
            first, second = st.columns(2)
            with first:
                name = st.text_input("여행 이름", placeholder="Tokyo 2026")
                country = st.text_input("국가 (선택)", placeholder="Japan")
                city = st.text_input("도시 (선택)", placeholder="Tokyo")
                currency = st.text_input("기본 통화", value="JPY", max_chars=3)
            with second:
                start_date = st.date_input("시작일", value=date.today())
                end_date = st.date_input("종료일", value=date.today() + timedelta(days=3))
                timezone = st.text_input("IANA 시간대", value="Asia/Tokyo")
                budget_mode = st.selectbox("여행 예산 모드", ["RELAXED", "NONE", "STRICT"])
                planned_budget = st.number_input("여행 예산 (원, 선택)", min_value=0, step=10_000)
                reserve = st.number_input("여행 시작 월 적립금 (원)", min_value=0, step=10_000)
            submitted = st.form_submit_button("여행 계획 저장")
        if submitted:
            if not name.strip():
                st.error("여행 이름을 입력해 주세요.")
            elif budget_mode == "STRICT" and planned_budget <= 0:
                st.error("STRICT 모드에는 양수 여행 예산이 필요합니다.")
            else:
                try:
                    finance_tool(
                        "create_trip",
                        {
                            "name": name,
                            "destination_country": country or None,
                            "destination_city": city or None,
                            "local_currency": currency.upper(),
                            "timezone": timezone,
                            "start_date": start_date.isoformat(),
                            "end_date": end_date.isoformat(),
                            "budget_mode": budget_mode,
                            "planned_budget_krw": int(planned_budget) if planned_budget else None,
                            "reserved_cash_krw": int(reserve),
                        },
                    )
                    st.success("여행 계획을 저장했습니다.")
                    st.rerun()
                except Exception as error:
                    st.error(f"여행 계획을 저장하지 못했습니다: {error}")

    trips = trips_response["trips"]
    if not trips:
        return
    labels = {trip["id"]: f"#{trip['id']} · {trip['name']} · {trip['status']}" for trip in trips}
    selected_id = st.selectbox("여행 선택", list(labels), format_func=lambda trip_id: labels[trip_id])
    selected = next(trip for trip in trips if trip["id"] == selected_id)
    action_left, action_middle, action_right = st.columns(3)
    with action_left:
        if selected["status"] == "PLANNED" and st.button("여행 시작", key=f"start_trip_{selected_id}"):
            try:
                finance_tool("start_trip", {"trip_id": selected_id})
                st.rerun()
            except Exception as error:
                st.error(f"여행을 시작하지 못했습니다: {error}")
    with action_middle:
        if selected["status"] == "ACTIVE" and st.button("여행 종료", key=f"end_trip_{selected_id}"):
            try:
                finance_tool("end_trip", {"trip_id": selected_id})
                st.rerun()
            except Exception as error:
                st.error(f"여행을 종료하지 못했습니다: {error}")
    with action_right:
        if selected["status"] == "PLANNED" and st.button("계획 취소", key=f"cancel_trip_{selected_id}"):
            try:
                finance_tool("cancel_trip", {"trip_id": selected_id})
                st.rerun()
            except Exception as error:
                st.error(f"여행 계획을 취소하지 못했습니다: {error}")

    try:
        summary = finance_tool("get_trip_spending_summary", {"trip_id": selected_id})
        categories = finance_tool("get_trip_category_summary", {"trip_id": selected_id})["items"]
        daily = finance_tool("get_trip_daily_summary", {"trip_id": selected_id})["items"]
        expenses = finance_tool("get_trip_expenses", {"trip_id": selected_id})["expenses"]
        map_data = finance_tool("get_trip_map_data", {"trip_id": selected_id})["locations"]
    except Exception as error:
        st.error(f"여행 지출을 불러오지 못했습니다: {error}")
        return

    first, second, third = st.columns(3)
    first.metric("여행 지출 합계", f"{summary['total_amount_krw']:,}원")
    second.metric("지출 건수", f"{summary['expense_count']}건")
    third.metric("미환산 지출", f"{summary['pending_conversion_count']}건")
    if summary["by_currency"]:
        st.caption("원 통화 합계: " + ", ".join(f"{item['currency']} {item['original_amount']}" for item in summary["by_currency"]))
    budget = summary["budget"]
    if budget["state"] in {"approaching", "exceeded"}:
        st.warning(f"STRICT 예산 상태: {budget['state']} · 남은 예산 {budget['remaining_budget_krw']:,}원")
    elif budget["planned_budget_krw"] is not None:
        st.caption(f"예산 정보: {budget['spent_percentage']}% 사용 · 남은 예산 {budget['remaining_budget_krw']:,}원")

    if selected["status"] == "ACTIVE":
        with st.expander("여행 지출 기록", expanded=True):
            with st.form("travel_expense_form", clear_on_submit=True):
                left, right = st.columns(2)
                with left:
                    original_amount = st.number_input("원 통화 금액", min_value=0.01, step=1.0)
                    original_currency = st.text_input("통화", value=selected["local_currency"], max_chars=3)
                    category = st.selectbox("카테고리", KOREAN_CATEGORIES, key="travel_category")
                    merchant = st.text_input("가맹점/장소", key="travel_merchant")
                with right:
                    occurred_date = st.date_input("지출일", value=date.today(), key="travel_date")
                    memo = st.text_input("메모", key="travel_memo")
                    add_location = st.checkbox("확인한 위치 추가")
                    latitude = st.number_input("위도", value=0.0, format="%.7f", disabled=not add_location)
                    longitude = st.number_input("경도", value=0.0, format="%.7f", disabled=not add_location)
                submitted = st.form_submit_button("여행 지출 저장")
            if submitted:
                arguments: dict[str, Any] = {
                    "original_amount": str(original_amount),
                    "original_currency": original_currency.upper(),
                    "category": category,
                    "merchant": merchant or None,
                    "occurred_at": f"{occurred_date.isoformat()}T12:00:00",
                    "memo": memo or None,
                    "trip_id": selected_id,
                }
                if add_location:
                    arguments.update({"place_name": merchant or None, "latitude": str(latitude), "longitude": str(longitude)})
                try:
                    saved = finance_tool("add_travel_expense", arguments)
                    status = saved["expense"]["conversion_status"]
                    st.success("여행 지출을 저장했습니다." if status == "COMPLETED" else "지출은 저장했고 환율 변환을 기다리고 있습니다.")
                    st.rerun()
                except Exception as error:
                    st.error(f"여행 지출을 저장하지 못했습니다: {error}")

    dashboard_left, dashboard_right = st.columns(2)
    with dashboard_left:
        st.markdown("**일별 지출**")
        if daily:
            st.bar_chart(pd.DataFrame(daily).set_index("date"))
        st.markdown("**카테고리**")
        if categories:
            category_frame = pd.DataFrame(categories)
            st.altair_chart(
                alt.Chart(category_frame).mark_arc().encode(theta="amount_krw:Q", color="category:N"),
                use_container_width=True,
            )
    with dashboard_right:
        st.markdown("**지출 지도**")
        if map_data:
            map_frame = pd.DataFrame(map_data)
            st.map(map_frame, latitude="latitude", longitude="longitude", size="amount_krw")
            st.caption("핀은 사용자가 직접 확인해 저장한 위치만 나타납니다.")
        else:
            st.info("확인한 좌표가 있는 지출만 지도에 표시됩니다.")

    st.markdown("**여행 지출 타임라인**")
    for expense in expenses:
        location = expense.get("location")
        location_text = f" · {location['place_name']}" if location and location.get("place_name") else ""
        original = f"{expense['original_currency']} {expense['original_amount']}"
        with st.expander(f"{expense['occurred_at']} · {expense['category']}{location_text} · {original} · {expense['amount']:,}원"):
            st.write(f"환산 상태: {expense['conversion_status']} · 정산 상태: {expense['settlement_status']}")
            if expense.get("memo"):
                st.caption(expense["memo"])
            if location and st.button("위치 삭제", key=f"delete_location_{expense['id']}"):
                try:
                    finance_tool("delete_expense_location", {"expense_id": expense["id"]})
                    st.rerun()
                except Exception as error:
                    st.error(f"위치를 삭제하지 못했습니다: {error}")


def show_summary(year: int, month: int) -> None:
    st.subheader("월간 현황과 자산 배분")
    try:
        summary = finance_tool("get_monthly_financial_summary", {"year": year, "month": month})
    except Exception as error:
        st.warning(f"프로필을 저장한 뒤 월간 계산을 확인할 수 있습니다: {error}")
        return

    cashflow = summary["cashflow"]
    spending = summary["spending"]
    first, second, third, fourth = st.columns(4)
    first.metric("월 수입", f"{cashflow['income']:,}원")
    second.metric("실제 지출", f"{spending['total_spending']:,}원")
    third.metric("비상금 기여", f"{cashflow['emergency_fund_contribution']:,}원")
    fourth.metric("투자 가능", f"{cashflow['investable_amount']:,}원")
    if spending["variable_budget"] is not None:
        st.caption(
            f"일상 변동예산 대비 {spending['budget_difference']:,}원 "
            f"{'남음' if spending['budget_difference'] >= 0 else '초과'} · 여행 지출 {spending['travel_spending']:,}원은 별도 표시"
        )

    if spending["by_category"]:
        chart_data = pd.DataFrame(spending["by_category"])
        chart = alt.Chart(chart_data).mark_arc().encode(theta="amount:Q", color="category:N", tooltip=["category:N", "amount:Q"])
        st.altair_chart(chart, use_container_width=True)

    if st.button("이번 달 계획 생성", type="primary"):
        try:
            created = finance_tool("create_monthly_financial_plan", {"year": year, "month": month})
            st.success(f"계획 #{created['plan']['id']}을 저장했습니다.")
            st.rerun()
        except Exception as error:
            st.error(f"계획을 만들지 못했습니다: {error}")

    latest_plan = summary["latest_plan"]
    if latest_plan:
        st.markdown(f"**최신 계획 #{latest_plan['id']} · {latest_plan['calculation_policy_version']}**")
        for reason in latest_plan["reasons"]:
            st.write(f"- {reason}")
        allocations = latest_plan["asset_allocation"]
        if allocations:
            st.dataframe(pd.DataFrame(allocations), hide_index=True, use_container_width=True)
        if summary["plan_history"]:
            st.caption(f"이 달의 감사 가능한 계획 스냅샷: {len(summary['plan_history'])}개")


def render_dashboard() -> None:
    st.title("개인 금융 대시보드")
    default_year, default_month = korean_month_default()
    selector_left, selector_right = st.columns(2)
    with selector_left:
        year = st.number_input("연도", min_value=2000, max_value=2200, value=default_year, step=1)
    with selector_right:
        month = st.selectbox("월", list(range(1, 13)), index=default_month - 1)
    try:
        profile_response = finance_tool("get_financial_profile")
        profile = profile_response["profile"]
    except Exception as error:
        st.error(f"금융 MCP 서버에 연결하지 못했습니다. 먼저 `alembic upgrade head`를 실행해 주세요. ({error})")
        return
    profile_tab, income_tab, expense_tab, travel_tab, summary_tab = st.tabs(["프로필", "수입", "지출", "여행", "월간 분석"])
    with profile_tab:
        show_profile_editor(profile)
    with income_tab:
        show_income_manager(int(year), int(month))
    with expense_tab:
        show_expense_manager(int(year), int(month))
    with travel_tab:
        show_travel_manager()
    with summary_tab:
        show_summary(int(year), int(month))


def render_chat() -> None:
    st.title("myHappybot 채팅")
    if "messages" not in st.session_state:
        st.session_state.messages = []
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    prompt = st.chat_input("무엇을 도와드릴까요?")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("MCP 도구를 확인하고 답변하는 중입니다."):
                try:
                    response = asyncio.run(run_agent(prompt))
                except Exception as error:
                    response = f"요청을 처리하지 못했습니다: {error}"
                st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})


st.set_page_config(page_title="myHappybot", page_icon="💰", layout="wide")
chat_tab, finance_tab = st.tabs(["채팅", "금융 대시보드"])
with chat_tab:
    render_chat()
with finance_tab:
    render_dashboard()
