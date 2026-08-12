# Personal finance MVP execution log

## Architecture decisions

- Existing demo MCP server and Korea real-estate MCP integration remain available.
- The finance server uses MCP 1.29 because the existing LangChain adapter and real-estate package require MCP `<2`.
- Finance data is local, single-user SQLite data accessed only through repositories and finance MCP tools.
- Allocation calculations are deterministic Python services under `src/personal_finance`.

## Milestones

- [x] Inspect the existing demo project and agree the MVP scope.
- [x] Add packaging, database schema, Alembic migration, and finance domain layer.
- [x] Add finance MCP tools and Streamlit dashboard.
- [x] Add automated tests, documentation, and end-to-end verification.

## Unexpected findings

- The repository had no package configuration, SQLAlchemy, Alembic, or pytest installed.
- `app.py` contains uncommitted real-estate MCP integration; it must be preserved.

## Test results

- `alembic upgrade head` created the initial local schema successfully.
- Direct stdio MCP smoke test listed 24 finance tools and returned a profile query response.
- `pytest`: 10 passed (service, persistence, policy rounding, and stdio MCP integration).
- Streamlit `AppTest` rendered the chat and finance-dashboard tabs without application exceptions.

## Limitations

- This MVP uses one local profile and does not execute trades or fetch market data.
- The dashboard needs a prior `alembic upgrade head`; it intentionally does not create schema outside the migration workflow.

## Travel Mode execution log

### Decisions

- Travel Mode remains within the single-user SQLite, MCP, and Streamlit architecture; only one trip may be ACTIVE.
- Travel spending is separately analysed but remains real cashflow. Existing normal-expense budgeting remains unchanged; travel spending and a PLANNED trip's start-month reserve additionally reduce investment capacity.
- Foreign amounts and snapshots use Decimal, historical rate cache records, and optional later settlement. Failed provider requests leave a PENDING expense rather than inventing a rate.
- The first map accepts only user-confirmed manual coordinates and renders with Streamlit. It has no automatic geocoding or GPS collection.

### Delivery checkpoints

- [x] Add Trip, rate-cache, optional location, and expense-context schema with a safe legacy-expense backfill migration.
- [x] Add deterministic travel lifecycle, foreign exchange, reconciliation, summaries, budgeting, and cashflow integration.
- [x] Add travel, exchange, and location MCP tools plus a Streamlit travel dashboard.
- [x] Add service, migration, stdio MCP, and Streamlit rendering tests.
