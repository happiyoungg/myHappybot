from mcp.server.fastmcp import FastMCP
import requests

# MCP 객체를 가져오기
mcp = FastMCP("Demo")
# 데코레이터를 이용해서 TOOL 제작
@mcp.tool()
def add(a: int, b: int) -> int:
    """두 숫자를 더합니다."""
    return a + b

# 날씨 정보 도구
@mcp.tool()
def get_weather(location: str) -> str:
    """특정 지역의 날씨 정보 제공"""
    return f"{location}의 날씨: 눈, -2°C, 미세먼지 매우나쁨"

# 환율 정보 도구
@mcp.tool()
def get_exchange_rate(base: str = "USD", quote: str = "KRW", amount: float = 1.0) -> str:
    """
    특정 통화의 환율을 조회합니다.
    예: base='USD', quote='KRW'이면 1달러가 몇 원인지 조회합니다.
    amount를 넣으면 해당 금액을 환산합니다.
    """

    base = base.upper()
    quote = quote.upper()

    url = f"https://api.frankfurter.dev/v2/rate/{base}/{quote}"

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    data = response.json()

    rate = data["rate"]
    date = data.get("date", "알 수 없음")

    converted = amount * rate

    return (
        f"기준일: {date}\n"
        f"환율: 1 {base} = {rate:,.2f} {quote}\n"
        f"환산: {amount:,.2f} {base} = {converted:,.2f} {quote}"
    )

# 어떤 방식으로 MCP를 실행할지
if __name__ == "__main__":
    mcp.run(transport="stdio")