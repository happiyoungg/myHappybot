# myHappybot

로컬 SQLite 기반 가계부·월간 현금흐름·자산배분을 제공하는 Streamlit 챗봇입니다.

> 개인 재무 계획 도구입니다. 수익을 보장하지 않으며, 시장 타이밍·개별 종목 추천·자동 매매를 하지 않습니다.

## Quick Start

다른 컴퓨터에서 처음 실행할 때는 아래 순서대로 진행합니다. Python 3.12 또는 3.13이 필요합니다.

```bash
git clone https://github.com/MuchYouth/myHappybot.git
cd myHappybot
python -m venv .venv
```

가상환경을 활성화합니다.

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

의존성을 설치하고, 환경 변수 파일과 로컬 가계부 DB를 준비합니다.

```bash
python -m pip install -e ".[dev]"
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

`.env` 파일에 ChatGPT API 키를 입력합니다.

```dotenv
OPENAI_API_KEY=your_openai_api_key_here
# 선택 사항: 기존 부동산 MCP 기능을 함께 사용할 때만 설정
PUBLIC_DATA_API_KEY=your_public_data_api_key_here
```

마지막으로 DB 테이블을 만든 뒤 앱을 실행합니다.

```bash
alembic upgrade head
streamlit run app.py
```

브라우저에서 Streamlit이 표시한 주소(일반적으로 `http://localhost:8501`)를 열면 됩니다. 이후에는 가상환경을 활성화한 뒤 `streamlit run app.py`만 실행하면 됩니다.

## 기능

- 기존 학습용 MCP: 덧셈, 날씨 예시, Frankfurter 환율 조회
- 기존 한국 부동산 MCP: `PUBLIC_DATA_API_KEY`를 설정한 경우 채팅에서 사용 가능
- 개인 금융 MCP: 프로필, 수입, 지출 CRUD와 월별 집계
- 금융 대시보드: 프로필·수입·지출 관리, 카테고리별 지출 차트, 예산 대비 현황, 월간 계획 이력
- 결정론적 자산배분: Python 코드의 버전 정책을 사용하며, LLM이 임의의 비율을 만들지 않음

## 상세 설치 및 개별 실행

Quick Start를 완료했다면 아래의 개별 명령도 사용할 수 있습니다.

```powershell
python finance_server.py
```

`.env`에는 채팅을 위한 `OPENAI_API_KEY`를 설정합니다. 기존 부동산 MCP도 사용할 때만 `PUBLIC_DATA_API_KEY`를 추가합니다. 실제 키·개인 데이터·SQLite DB는 Git에 포함되지 않습니다.

기존 학습용 MCP 서버는 그대로 다음 명령으로 실행할 수 있습니다.

```powershell
python server.py
```

테스트는 다음과 같습니다.

```powershell
pytest
```

기본 DB 경로는 `data/personal_finance.sqlite3`입니다. 별도의 로컬 DB를 쓰려면 실행 전 `PERSONAL_FINANCE_DATABASE_URL=sqlite:///C:/path/to/finance.sqlite3`을 설정합니다.

## 구조

```text
Streamlit chat / finance dashboard
              │
      LangChain MCP client
              │
      Personal Finance MCP server
              │
    FinanceService (deterministic logic)
              │
          repositories
              │
        SQLAlchemy + SQLite
```

`src/personal_finance/`는 UI·LLM과 분리된 도메인, 리포지터리, 정책, MCP 서버를 담습니다. Streamlit 대시보드도 금융 MCP의 공개 도구만 호출하므로 채팅과 화면의 데이터 경로가 같습니다.

## 금융 정책

- 금액은 부동소수점 없이 원 단위 정수로 저장합니다.
- 기본 통화와 시간대는 KRW, `Asia/Seoul`입니다.
- 월 필요금액 = 고정지출 + 변동예산 + 월 부채상환액입니다.
- 비상금 목표 = 월 필요금액 × 목표 개월입니다.
- 가용현금 = 월 수입 − 월 필요금액입니다. 부족하면 투자 가능액은 0원이며 부족액을 반환합니다.
- 비상금이 부족하면 가용현금을 먼저 비상금에 배정합니다. 남은 금액만 아래 정책으로 배분합니다.

| 위험성향 | 현금 | 저축 | 채권 | 인덱스 주식 | 연금 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 보수형 | 10% | 15% | 40% | 20% | 15% |
| 균형형 | 5% | 10% | 25% | 40% | 20% |
| 성장형 | 5% | 5% | 10% | 55% | 25% |

정책 버전은 `allocation_policy_v1`이며, 최대 나머지 반올림 방식으로 배분 금액의 합계를 보존합니다. 월간 계획을 생성할 때마다 계산 입력·정책 버전·사유·배분 결과를 새 스냅샷으로 남깁니다.

## Travel Mode

여행은 의도적인 지출로 다룹니다. ACTIVE 여행이 하나 있을 때 일반 KRW 지출은 기본적으로 여행 문맥에 연결되고, 외화 지출은 여행 화면 또는 MCP의 `add_travel_expense`로 저장합니다. 여행 지출은 일상 카테고리 예산 분석과 분리하지만, 실제 가용 현금과 투자 가능액에서는 제외하지 않습니다.

여행의 상태는 `PLANNED → ACTIVE → COMPLETED`이며, 계획은 취소할 수 있습니다. 예산 모드는 다음과 같습니다.

- `NONE`: 지출 총액만 기록합니다.
- `RELAXED`: 선택한 여행 예산을 정보로만 보여 줍니다.
- `STRICT`: 명시한 KRW 예산의 80%부터 중립적 상태 알림을 보여 줍니다.

예정 여행의 명시적 적립금은 해당 여행이 시작하는 달의 투자 가능액에서만 차감됩니다. 여행이 시작되면 적립금 대신 실제 여행 지출이 반영됩니다.

### 외화와 정산

외화 지출은 원 통화 금액, 통화 코드, 환율 기준일·provider·단위, 추정 KRW 금액을 함께 저장합니다. 한국수출입은행 환율 API를 사용하려면 `.env`에 `KOREA_EXIM_API_KEY`를 설정한 뒤 DB 마이그레이션을 실행합니다.

```dotenv
KOREA_EXIM_API_KEY=your_korea_exim_api_key_here
```

API 키가 없거나 provider 요청이 실패하면 지출은 삭제되지 않고 `PENDING` 상태로 저장됩니다. `refresh_pending_currency_conversions`로 나중에 다시 환산할 수 있으며, 환율을 임의로 생성하지 않습니다. 카드 정산액을 알게 되면 `reconcile_travel_expense`가 정산 KRW 금액을 회계 금액으로 사용하지만 원래 환율 스냅샷은 유지합니다.

### 여행 화면과 개인정보

금융 대시보드의 **여행** 탭에서 여행 계획 생성·시작·종료, 통화별 합계, 일별/카테고리 차트, 지출 타임라인과 지출 지도를 사용할 수 있습니다. 지도에는 사용자가 직접 확인해 입력한 위도·경도만 표시됩니다. 자동 장소 검색, GPS 추적, 이동 경로 추론은 제공하지 않으며 위치를 삭제해도 지출 기록은 유지됩니다.

새 버전으로 업데이트한 기존 DB에는 반드시 다음을 한 번 실행합니다.

```powershell
alembic upgrade head
```

여행 대화 예시:

```text
8월 20일부터 24일까지 도쿄 여행 갈 거야.
여행 시작했어.
이치란에서 1480엔 썼어.
이번 여행에서 오늘 얼마 썼어?
여행 끝났어.
```

## 채팅 예시

```text
오늘 점심 9000원 썼어.
아까 스타벅스에서 커피 4800원 썼어.
오늘 점심 9000원, 커피 4500원 썼어.
이번 달 식비 얼마 썼어?
이번 달 급여 320만원 받았어.
이번 달 너무 많이 썼어?
```

금융 정보가 필요한 답변은 MCP에서 저장·조회·계산한 결과만 사용합니다. 카테고리가 불확실한 지출은 안전하게 `기타`로 저장됩니다.
