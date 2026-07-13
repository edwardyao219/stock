# Tushare 5000 Evidence Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist Tushare 5000-point money-flow, limit-event, and chip-distribution data, then use same-day records as explainable support or blocking risk evidence without allowing positive evidence to upgrade candidates.

**Architecture:** Extend the existing Tushare model/sync registry and reuse the current batch-loaded strategy context. Evidence stays low-dimensional in `plans/evidence.py`; a small blocking set in the plan generator suppresses action plans while leaving research candidates intact. Scheduled after-close status reads structured database health after the pipeline finishes.

**Tech Stack:** Python 3.12, SQLAlchemy, FastAPI, Celery, pytest, React 19, TypeScript, Vite.

---

## File Map

- Modify `services/shared/models.py`: add three unique daily Tushare tables.
- Modify `services/collector/tushare_sync.py`: parse and upsert three 5000-point datasets.
- Modify `services/collector/sync.py`: register the datasets for resumable sync.
- Modify `services/collector/daily.py`: include the datasets in normal after-close sync.
- Modify `services/jobs/pipeline.py`: make 18:00 use the same full sync before features.
- Modify `services/engine/plans/context.py`: add exact-date converters and batch map loaders.
- Modify `services/engine/plans/repository.py`: batch-load and pass the three maps.
- Modify `services/engine/plans/evidence.py`: produce seven explainable evidence states.
- Modify `services/engine/plans/generator.py`: suppress action plans for four explicit risk flags.
- Modify `services/engine/features/health.py`: report structured Tushare evidence coverage.
- Modify `services/jobs/tasks.py` and `services/jobs/status.py`: attach and cache the health report.
- Modify `apps/api/app/routers/jobs.py`, `apps/web/src/api.ts`, and `apps/web/src/App.tsx`: expose and display the report.
- Extend existing focused tests; create no new production package or dependency.

### Task 1: Models and Idempotent Sync Functions

**Files:**
- Modify: `services/shared/models.py`
- Modify: `services/collector/tushare_sync.py`
- Modify: `tests/test_tushare_proxy_sync.py`

- [ ] **Step 1: Write failing sync tests for all three datasets**

Extend `test_tushare_sync_writes_core_tables` with fake responses for `moneyflow_dc`, `limit_list_d`, and `cyq_perf`, call each sync function twice, and assert one row remains per table:

```python
assert sync_tushare_moneyflow_dc(db, trade_date="20260710") == 1
assert sync_tushare_limit_list_d(db, trade_date="20260710") == 1
assert sync_tushare_cyq_perf(db, trade_date="20260710") == 1
db.commit()

assert db.query(TushareMoneyflowDc).count() == 1
assert db.query(TushareLimitListD).count() == 1
assert db.query(TushareCyqPerf).count() == 1
assert db.query(TushareMoneyflowDc).one().net_amount_rate == Decimal("1.230000")
assert db.query(TushareLimitListD).one().open_times == 2
assert db.query(TushareCyqPerf).one().winner_rate == Decimal("91.500000")
```

The fake rows must use the real field order verified in the design spec. Add a separate malformed-key test where `ts_code` is absent and assert the sync function raises `ValueError` before writing.

- [ ] **Step 2: Run the focused test and verify RED**

```bash
.venv/bin/pytest tests/test_tushare_proxy_sync.py -q -k "writes_core_tables or rejects_missing_key"
```

Expected: import or attribute failure because the models and sync functions do not exist.

- [ ] **Step 3: Add the three SQLAlchemy models**

Follow the existing Tushare model pattern. Each class uses `(ts_code, trade_date)` as a unique constraint and `Numeric` for optional numeric source fields:

```python
class TushareMoneyflowDc(Base):
    __tablename__ = "tushare_moneyflow_dc"
    __table_args__ = (
        UniqueConstraint("ts_code", "trade_date", name="uq_tushare_moneyflow_dc_code_date"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(64))
    pct_change: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    net_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    net_amount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    buy_elg_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    buy_elg_amount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    buy_lg_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    buy_lg_amount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    buy_md_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    buy_md_amount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
    buy_sm_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
    buy_sm_amount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6))
```

Add `TushareLimitListD` with the verified limit-event fields and `TushareCyqPerf` with the verified cost percentile fields. Use `String(16)` for time/status text and `Integer` for `open_times` and `limit_times`.

- [ ] **Step 4: Implement strict-key parsing and upserts**

Add a shared local helper in `tushare_sync.py`:

```python
def _required_row_keys(row: dict[str, Any]) -> tuple[str, date]:
    ts_code = str(row.get("ts_code") or "").strip()
    raw_trade_date = row.get("trade_date")
    if not ts_code or not raw_trade_date:
        raise ValueError("Tushare row missing ts_code or trade_date")
    return ts_code, _date(raw_trade_date)
```

Implement `sync_tushare_moneyflow_dc`, `sync_tushare_limit_list_d`, and `sync_tushare_cyq_perf` by calling `client.query(api_name, params={"trade_date": trade_date})`, converting optional values with `_decimal`, and using `upsert_rows` with the model's unique constraint and all non-key columns in `update_columns`.

- [ ] **Step 5: Run tests and commit**

```bash
.venv/bin/pytest tests/test_tushare_proxy_sync.py -q
```

Expected: all tests pass.

```bash
git add services/shared/models.py services/collector/tushare_sync.py tests/test_tushare_proxy_sync.py
git commit -m "feat: persist Tushare 5000-point datasets"
```

### Task 2: Resumable Registry and Shared 15:30/18:00 Sync

**Files:**
- Modify: `services/collector/sync.py`
- Modify: `services/collector/daily.py`
- Modify: `services/jobs/pipeline.py`
- Modify: `tests/test_tushare_proxy_sync.py`
- Modify: `tests/test_jobs_pipeline.py`

- [ ] **Step 1: Write failing registry and pipeline tests**

Assert the three names exist in `TUSHARE_MARKET_DATASETS`, `_tushare_dataset_registry()`, and `TUSHARE_AFTER_CLOSE_DATASETS`:

```python
expected = {"moneyflow_dc", "limit_list_d", "cyq_perf"}
assert expected <= set(collector_sync.TUSHARE_MARKET_DATASETS)
assert expected <= set(collector_sync._tushare_dataset_registry())
assert expected <= set(daily.TUSHARE_AFTER_CLOSE_DATASETS)
```

Update the successful after-close pipeline test so a full-market run expects `sync_daily_market_data` before feature preparation, captures `full_refresh=True, force=True`, and asserts feature preparation receives `sync_daily=False`. Add a lightweight test asserting `full_market_sync=False` skips this extra sync step.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.venv/bin/pytest tests/test_tushare_proxy_sync.py tests/test_jobs_pipeline.py -q -k "5000 or after_close_session"
```

Expected: FAIL because the registry and 18:00 shared sync step are absent.

- [ ] **Step 3: Register the datasets**

Import the three models and sync functions into `services/collector/sync.py`, add them to `TUSHARE_MARKET_DATASETS`, and add exact registry entries:

```python
"moneyflow_dc": (TushareMoneyflowDc, sync_tushare_moneyflow_dc),
"limit_list_d": (TushareLimitListD, sync_tushare_limit_list_d),
"cyq_perf": (TushareCyqPerf, sync_tushare_cyq_perf),
```

Append all three names to `TUSHARE_AFTER_CLOSE_DATASETS` in `services/collector/daily.py`.

- [ ] **Step 4: Make 18:00 reuse the full sync entry point**

In `run_after_close_session`, when `full_market_sync` is true, prepend:

```python
_run_step(
    "sync_daily_market_data",
    lambda: _sync_daily_market_data_step(
        trade_date,
        full_refresh=True,
        force=True,
    ),
)
```

Then call `_prepare_market_feature_universe_step(..., sync_daily=False)` so the base daily endpoint is not fetched twice. When `full_market_sync` is false, retain the current local-data behavior and do not add the full sync step.

- [ ] **Step 5: Run task regression and commit**

```bash
.venv/bin/pytest tests/test_tushare_proxy_sync.py tests/test_jobs_pipeline.py -q
```

Expected: all tests pass.

```bash
git add services/collector/sync.py services/collector/daily.py services/jobs/pipeline.py tests/test_tushare_proxy_sync.py tests/test_jobs_pipeline.py
git commit -m "feat: sync Tushare evidence before after-close screening"
```

### Task 3: Exact-Date Batch Strategy Context

**Files:**
- Modify: `services/engine/plans/context.py`
- Modify: `services/engine/plans/repository.py`
- Modify: `tests/test_plans_context_tushare.py`

- [ ] **Step 1: Write failing exact-date context tests**

Insert same-symbol rows for 2026-07-09 and 2026-07-10 in all three tables, then load contexts for 2026-07-10 and assert only same-day values appear:

```python
context = contexts[0]
assert context["dc_net_amount_rate"] == -1.5
assert context["limit_event"] == "U"
assert context["limit_open_times"] == 2
assert context["chip_cost_50pct"] == 10.2
assert context["chip_cost_85pct"] == 11.4
assert context["chip_winner_rate"] == 91.0
```

Add a second symbol with only 2026-07-09 rows and assert none of these keys are populated for the 2026-07-10 context. Preserve the existing batched-query assertion by counting only one query per new table, not one query per symbol.

- [ ] **Step 2: Run the context tests and verify RED**

```bash
.venv/bin/pytest tests/test_plans_context_tushare.py -q -k "5000 or exact_date"
```

Expected: FAIL because the new maps and context keys do not exist.

- [ ] **Step 3: Add converters and batch loaders**

In `plans/context.py`, add converters that return these keys:

```python
def _moneyflow_dc_context(row: TushareMoneyflowDc) -> dict[str, Any]:
    return {
        "dc_net_amount": _optional_float(row.net_amount),
        "dc_net_amount_rate": _optional_float(row.net_amount_rate),
        "dc_buy_lg_amount_rate": _optional_float(row.buy_lg_amount_rate),
        "dc_buy_elg_amount_rate": _optional_float(row.buy_elg_amount_rate),
    }
```

```python
def _limit_list_context(row: TushareLimitListD) -> dict[str, Any]:
    return {
        "limit_event": row.limit,
        "limit_open_times": row.open_times,
        "limit_times": row.limit_times,
        "limit_first_time": row.first_time,
        "limit_last_time": row.last_time,
        "limit_fd_amount": _optional_float(row.fd_amount),
    }
```

```python
def _cyq_context(row: TushareCyqPerf) -> dict[str, Any]:
    return {
        "chip_cost_50pct": _optional_float(row.cost_50pct),
        "chip_cost_85pct": _optional_float(row.cost_85pct),
        "chip_weight_avg": _optional_float(row.weight_avg),
        "chip_winner_rate": _optional_float(row.winner_rate),
    }
```

Each `load_*_map` must filter both `ts_code.in_(...)` and `trade_date == target_date`.

- [ ] **Step 4: Thread maps through context construction**

Add optional map arguments to `build_strategy_context`, merge their same-day dictionaries into the context, and update `load_feature_contexts` in `plans/repository.py` to batch-load the three maps once before iterating rows.

- [ ] **Step 5: Run context regression and commit**

```bash
.venv/bin/pytest tests/test_plans_context_tushare.py tests/test_trade_plan_repository.py -q
```

Expected: all tests pass.

```bash
git add services/engine/plans/context.py services/engine/plans/repository.py tests/test_plans_context_tushare.py
git commit -m "feat: add same-day Tushare evidence context"
```

### Task 4: Explainable Evidence and Action-Plan Blocking

**Files:**
- Modify: `services/engine/plans/evidence.py`
- Modify: `services/engine/plans/generator.py`
- Modify: `tests/test_trade_plan_generator.py`

- [ ] **Step 1: Write failing evidence matrix tests**

Add focused `build_trade_evidence` cases and assert flags:

```python
assert "dual_source_moneyflow_confirmation" in supportive["support_flags"]
assert "dual_source_moneyflow_outflow" in outflow["risk_flags"]
assert "moneyflow_source_divergence" in divergent["risk_flags"]
assert "limit_down_risk" in limit_down["risk_flags"]
assert "repeated_limit_open" in opened_twice["risk_flags"]
assert "chip_overhead_pressure" in below_cost["risk_flags"]
assert "chip_overheat" in overheated["risk_flags"]
```

Use the fixed boundaries: existing support score `54/45`, DC rate `+1/-1`, `open_times >= 2`, and `winner_rate >= 90` with `close >= cost_85pct`.

- [ ] **Step 2: Write failing plan-blocking tests**

Generate otherwise-valid `long_term` or `swing` plans with each blocking flag and assert no plan is returned. Verify `moneyflow_source_divergence`, `chip_overhead_pressure`, and all positive support flags remain explanatory and do not independently block or raise `confidence_score`.

Blocking set:

```python
ACTION_BLOCKING_TUSHARE_RISKS = {
    "dual_source_moneyflow_outflow",
    "limit_down_risk",
    "repeated_limit_open",
    "chip_overheat",
}
```

- [ ] **Step 3: Run tests and verify RED**

```bash
.venv/bin/pytest tests/test_trade_plan_generator.py -q -k "tushare or moneyflow_source or chip_ or limit_"
```

Expected: FAIL because the evidence tags and blocking set do not exist.

- [ ] **Step 4: Implement evidence tags**

Add tags to `build_trade_evidence` using only non-`None` inputs. `dual_source_moneyflow_confirmation` is support/low; `moneyflow_source_divergence` is risk/low; the four blocking risks are risk/high; `chip_overhead_pressure` is risk/medium. Include the raw threshold inputs in each tag's `values`.

Do not add DC or chip values to the confidence formula. Add their raw values only to `evidence["scores"]` for diagnostics.

- [ ] **Step 5: Filter blocking plans after evidence construction**

Add:

```python
def _has_blocking_tushare_risk(plan: TradePlanCandidate) -> bool:
    condition = plan.entry_condition or {}
    evidence = condition.get("evidence") or {}
    return bool(ACTION_BLOCKING_TUSHARE_RISKS & set(evidence.get("risk_flags") or []))
```

In `generate_trade_plans`, build the candidate, then append it only when this helper is false. This suppresses the plan but does not modify the research-pool candidate.

- [ ] **Step 6: Run plan regression and commit**

```bash
.venv/bin/pytest tests/test_trade_plan_generator.py tests/test_plans_sync.py tests/test_plan_learning_adjustments.py -q
```

Expected: all tests pass.

```bash
git add services/engine/plans/evidence.py services/engine/plans/generator.py tests/test_trade_plan_generator.py
git commit -m "feat: apply Tushare risk evidence to action plans"
```

### Task 5: Structured Dataset Health and Cached After-Close Status

**Files:**
- Modify: `services/engine/features/health.py`
- Modify: `services/jobs/tasks.py`
- Modify: `services/jobs/status.py`
- Modify: `apps/api/app/routers/jobs.py`
- Modify: `tests/test_data_health.py`
- Modify: `tests/test_jobs_pipeline.py`
- Modify: `tests/test_jobs_api.py`

- [ ] **Step 1: Write failing dataset-health tests**

Create 100 eligible daily bars, 90 matching `moneyflow_dc` rows, 80 matching `cyq_perf` rows, and 7 limit events. Assert:

```python
health = inspect_tushare_evidence_health(db, date(2026, 7, 10))
assert health == {
    "trade_date": "2026-07-10",
    "daily_symbol_count": 100,
    "datasets": [
        {"name": "moneyflow_dc", "rows": 90, "matched_rows": 90, "coverage_ratio": 0.9, "status": "partial"},
        {"name": "cyq_perf", "rows": 80, "matched_rows": 80, "coverage_ratio": 0.8, "status": "partial"},
        {"name": "limit_list_d", "rows": 7, "matched_rows": 7, "coverage_ratio": None, "status": "ok"},
    ],
}
```

Use `ok` for coverage at least 98%, `partial` for nonzero lower coverage, and `missing` for zero rows. Define `inspect_tushare_evidence_health(db, trade_date, sync_statuses=None)`. For `limit_list_d`, return `ok` with zero rows only when `sync_statuses["limit_list_d"]` is `ok` or `skipped`; return `missing` when no successful sync status and no rows exist.

- [ ] **Step 2: Write failing status/API tests**

Make `run_after_close_session_task` return a pipeline result, monkeypatch the health inspector, and assert the task adds top-level `tushare_evidence_health` before `write_after_close_status`. Assert `build_after_close_status` carries this object unchanged, and `AfterCloseStatusResponse` exposes it.

- [ ] **Step 3: Run tests and verify RED**

```bash
.venv/bin/pytest tests/test_data_health.py tests/test_jobs_pipeline.py tests/test_jobs_api.py -q -k "tushare_evidence or after_close_status"
```

Expected: FAIL because the health inspector and response field do not exist.

- [ ] **Step 4: Implement database health inspection**

In `features/health.py`, query eligible `DailyBar` symbols for the exact date and exact-date rows from the three new tables. Normalize Tushare symbols with `ts_code.split(".", 1)[0]`, compute matched distinct symbols, and return the deterministic dictionary shape asserted above. Never query a prior date.

- [ ] **Step 5: Attach health to scheduled status**

After `run_after_close_session(...).to_dict()` in `run_after_close_session_task`, extract statuses from the `sync_daily_market_data` step details with this exact pattern:

```python
match = re.match(
    r"^(moneyflow_dc|limit_list_d|cyq_perf): (ok|skipped|failed), rows=(\d+)",
    detail,
)
```

Pass the resulting `{dataset: status}` map to `inspect_tushare_evidence_health`, add the report as `result["tushare_evidence_health"]`, then call `write_after_close_status(result)`. In `build_after_close_status`, carry this top-level value with a safe empty default.

Add `tushare_evidence_health: dict[str, Any]` to `AfterCloseStatusResponse` using `Field(default_factory=dict)`.

- [ ] **Step 6: Run backend status regression and commit**

```bash
.venv/bin/pytest tests/test_data_health.py tests/test_jobs_pipeline.py tests/test_jobs_api.py -q
```

Expected: all tests pass.

```bash
git add services/engine/features/health.py services/jobs/tasks.py services/jobs/status.py apps/api/app/routers/jobs.py tests/test_data_health.py tests/test_jobs_pipeline.py tests/test_jobs_api.py
git commit -m "feat: report Tushare evidence data health"
```

### Task 6: Web Status and Real 2026-07-10 Smoke Sync

**Files:**
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/postCloseDrawerLayout.test.mjs`
- Verify: local MySQL tables and counts for 2026-07-10

- [ ] **Step 1: Write failing Web source assertions**

Assert the status drawer contains `Tushare证据`, renders `moneyflow_dc`, `cyq_perf`, and `limit_list_d`, and uses the structured `tushare_evidence_health` field.

- [ ] **Step 2: Run the Web test and verify RED**

```bash
cd apps/web && node src/postCloseDrawerLayout.test.mjs
```

Expected: FAIL because the structured dataset summary is not rendered.

- [ ] **Step 3: Add types and compact status rows**

Add:

```typescript
interface TushareEvidenceDatasetHealth {
  name: "moneyflow_dc" | "cyq_perf" | "limit_list_d" | string;
  rows: number;
  matched_rows: number;
  coverage_ratio: number | null;
  status: "ok" | "partial" | "missing" | string;
}
```

Type `AfterCloseStatus.tushare_evidence_health`, then add one unframed metrics row in the existing drawer. Display Chinese names, row counts, and coverage for the two full-market datasets; display event count for `limit_list_d`. Do not add cards, tabs, or a new page.

- [ ] **Step 4: Run frontend verification**

```bash
cd apps/web
node src/postCloseDrawerLayout.test.mjs
node src/dataHealthPanel.test.mjs
node --experimental-strip-types src/stockLabels.test.ts
npm run build
```

Expected: tests pass and Vite completes a production build.

- [ ] **Step 5: Sync the verified historical date through production code**

Run schema creation/sync first, then force the three datasets only:

```bash
.venv/bin/python -m services.shared.create_tables
.venv/bin/python -m services.shared.sync_schema
.venv/bin/python -m services.collector.run_sync tushare-backfill \
  --start-date 20260710 \
  --end-date 20260710 \
  --datasets moneyflow_dc limit_list_d cyq_perf \
  --force \
  --skip-stock-basic \
  --sleep-seconds 0
```

Verify only counts and dates; do not print row payloads or settings:

```bash
.venv/bin/python -c 'from datetime import date; from sqlalchemy import func, select; from services.shared.database import SessionLocal; from services.shared.models import TushareMoneyflowDc, TushareLimitListD, TushareCyqPerf; d=date(2026,7,10); s=SessionLocal(); print({m.__tablename__: s.scalar(select(func.count()).select_from(m).where(m.trade_date==d)) for m in (TushareMoneyflowDc,TushareLimitListD,TushareCyqPerf)}); s.close()'
```

Expected counts are nonzero and approximately match the permission probe: 5907, 187, and 5521. Exact counts may differ if the upstream source revises data.

- [ ] **Step 6: Commit Web changes**

```bash
git add apps/web/src/api.ts apps/web/src/App.tsx apps/web/src/postCloseDrawerLayout.test.mjs
git commit -m "feat: show Tushare evidence data status"
```

### Task 7: Full Verification

**Files:**
- Verify only; modify only defects within this plan's scope.

- [ ] **Step 1: Run backend regression**

```bash
.venv/bin/pytest \
  tests/test_tushare_proxy_sync.py \
  tests/test_plans_context_tushare.py \
  tests/test_trade_plan_generator.py \
  tests/test_plans_sync.py \
  tests/test_data_health.py \
  tests/test_jobs_pipeline.py \
  tests/test_jobs_api.py \
  tests/test_next_session_candidates.py \
  tests/test_paper_simulator.py \
  tests/test_walk_forward_replay.py \
  -q --disable-warnings
```

Expected: zero failures.

- [ ] **Step 2: Run Ruff**

```bash
.venv/bin/ruff check \
  services/shared/models.py \
  services/collector/tushare_sync.py \
  services/collector/sync.py \
  services/collector/daily.py \
  services/engine/plans/context.py \
  services/engine/plans/repository.py \
  services/engine/plans/evidence.py \
  services/engine/plans/generator.py \
  services/engine/features/health.py \
  services/jobs/pipeline.py \
  services/jobs/tasks.py \
  services/jobs/status.py \
  apps/api/app/routers/jobs.py \
  tests/test_tushare_proxy_sync.py \
  tests/test_plans_context_tushare.py \
  tests/test_trade_plan_generator.py \
  tests/test_data_health.py \
  tests/test_jobs_pipeline.py \
  tests/test_jobs_api.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Run frontend regression**

```bash
cd apps/web
node src/postCloseDrawerLayout.test.mjs
node src/dataHealthPanel.test.mjs
node --experimental-strip-types src/stockLabels.test.ts
npm run build
```

Expected: source tests pass and Vite completes a production build.

- [ ] **Step 4: Inspect Git safety and report evidence**

```bash
git diff --check
git status --short
```

Expected: `.stock-dev.sqlite` and `dump.rdb` remain untracked and unstaged. Report test counts, actual three-dataset row counts, and any source limitation. Never print Tushare token or `.env` values.
