# After-Close Data Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the real full-market close sync, block new candidates and entries when daily data is incomplete, and label stale or degraded market data clearly in the Web workspace.

**Architecture:** Extend the existing daily health report with one shared candidate-readiness decision, then consume that decision from the market API and after-close pipeline. Keep the current collectors, Celery schedule, pipeline result types, and summary strip; add only an entry toggle to daily paper simulation so exits still run while new entries are blocked.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Celery, pytest, React 19, TypeScript, Vite.

---

## File Map

- Modify `services/engine/features/health.py`: calculate eligible-universe daily coverage and candidate block reasons.
- Modify `apps/api/app/routers/market.py`: expose health gate fields and use the shared 98% market coverage threshold.
- Modify `services/collector/daily.py`: allow a forced resumable refresh for partial datasets.
- Modify `services/jobs/pipeline.py`: expose sync force mode, evaluate the shared gate, and branch candidate/entry work.
- Modify `services/jobs/tasks.py`: replace the 15:30 placeholder with the real guarded sync.
- Modify `services/engine/paper/simulator.py`: allow exits while entries are disabled.
- Modify `apps/web/src/api.ts`: type the new health fields.
- Modify `apps/web/src/App.tsx`: show snapshot scope and low-coverage state.
- Modify focused tests under `tests/` and `apps/web/src/`; create no new runtime modules.

### Task 1: Shared Daily Candidate-Readiness Report

**Files:**
- Modify: `tests/test_data_health.py`
- Modify: `services/engine/features/health.py`
- Modify: `apps/api/app/routers/market.py`
- Modify: `tests/test_market_api.py`

- [ ] **Step 1: Write failing health-report tests**

Add tests that build 100 active non-ST securities, write 97 eligible daily bars, and assert the explicit target date is blocked. Add a passing case with 98 bars and no missing amounts. The assertions are:

```python
report = inspect_daily_data_health(db, trade_date=date(2026, 7, 13))
assert report.expected_security_count == 100
assert report.eligible_daily_bar_count == 97
assert report.daily_coverage_ratio == 0.97
assert report.candidate_generation_allowed is False
assert any("98%" in reason for reason in report.candidate_block_reasons)
```

```python
report = inspect_daily_data_health(db, trade_date=date(2026, 7, 13))
assert report.daily_coverage_ratio == 0.98
assert report.amount_missing_ratio == 0
assert report.candidate_generation_allowed is True
assert report.candidate_block_reasons == []
```

Add a third boundary test with 100 bars and one missing `amount`; the 1% missing ratio must block candidate generation.

- [ ] **Step 2: Run the health tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_data_health.py -q
```

Expected: FAIL because `DailyDataHealthReport` does not expose the new readiness fields.

- [ ] **Step 3: Implement the minimal shared gate**

In `services/engine/features/health.py`, add:

```python
DAILY_CANDIDATE_MIN_COVERAGE_RATIO = 0.98
DAILY_CANDIDATE_MAX_AMOUNT_MISSING_RATIO = 0.01
```

Extend `DailyDataHealthReport` with:

```python
expected_security_count: int
eligible_daily_bar_count: int
daily_coverage_ratio: float
candidate_generation_allowed: bool
candidate_block_reasons: list[str] = field(default_factory=list)
```

Load active non-ST symbols from `Security`, restrict gate bars to those symbols, and calculate:

```python
expected_security_count = len(eligible_symbols)
eligible_bars = [row for row in bars if row.symbol in eligible_symbols]
daily_coverage_ratio = (
    len(eligible_bars) / expected_security_count if expected_security_count else 0.0
)
gate_amount_missing_ratio = _amount_missing_ratio(eligible_bars)
```

Build concrete Chinese reasons for an empty universe, no target-date bars, coverage below 98%, and amount missing ratio greater than or equal to 1%. Set `candidate_generation_allowed = not candidate_block_reasons`. Keep the existing general health `status` calculation unchanged so this addition does not rewrite unrelated health semantics.

- [ ] **Step 4: Run the health tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/test_data_health.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Write a failing API serialization test**

Extend the existing `/market/data-health` test to assert:

```python
assert payload.expected_security_count == 3
assert payload.eligible_daily_bar_count == 3
assert payload.daily_coverage_ratio == 1.0
assert payload.candidate_generation_allowed is True
assert payload.candidate_block_reasons == []
```

- [ ] **Step 6: Run the API test and verify RED**

Run the exact new test:

```bash
.venv/bin/pytest tests/test_market_api.py -q -k data_health
```

Expected: FAIL because `DataHealthResponse` does not declare the new fields.

- [ ] **Step 7: Expose the fields and share the coverage threshold**

Add the five fields to `DataHealthResponse`. Import `DAILY_CANDIDATE_MIN_COVERAGE_RATIO` next to `inspect_daily_data_health` and replace the local `MARKET_DAILY_MIN_COVERAGE_RATIO = 0.80` with:

```python
MARKET_DAILY_MIN_COVERAGE_RATIO = DAILY_CANDIDATE_MIN_COVERAGE_RATIO
```

- [ ] **Step 8: Run focused backend tests and commit**

Run:

```bash
.venv/bin/pytest tests/test_data_health.py tests/test_market_api.py -q
```

Expected: all tests pass.

Commit:

```bash
git add services/engine/features/health.py apps/api/app/routers/market.py tests/test_data_health.py tests/test_market_api.py
git commit -m "feat: report daily candidate data readiness"
```

### Task 2: Real 15:30 Full-Market Sync

**Files:**
- Modify: `tests/test_jobs_pipeline.py`
- Modify: `services/collector/daily.py`
- Modify: `services/jobs/pipeline.py`
- Modify: `services/jobs/tasks.py`

- [ ] **Step 1: Write a failing scheduled-task test**

Add a test that fixes `now_local()` at 2026-07-13 15:30, makes the trading-calendar guard pass and the daily lock succeed, then captures the sync call:

```python
def fake_sync_step(trade_date, *, full_refresh=False, force=False):
    captured.update(
        trade_date=trade_date,
        full_refresh=full_refresh,
        force=force,
    )
    return pipeline.PipelineStepResult(
        name="sync_daily_market_data",
        status="ok",
        detail="同步行情完成",
        summary="同步行情完成",
    )

result = tasks.sync_daily_market_data_task()

assert captured == {
    "trade_date": "2026-07-13",
    "full_refresh": True,
    "force": True,
}
assert result["status"] == "ok"
assert result["detail"] == "同步行情完成"
```

Add a non-trading-day test that asserts the sync function is not called and the task returns `status == "skipped"`.

- [ ] **Step 2: Run the task tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_jobs_pipeline.py -q -k "sync_daily_market_data_task"
```

Expected: FAIL because the task still returns the fixed `pending` payload.

- [ ] **Step 3: Thread force mode through the existing sync functions**

Change the collector signature to:

```python
def sync_daily_market_data(
    trade_date: str,
    *,
    full_refresh: bool = False,
    force: bool = False,
) -> list[CollectionResult]:
```

Pass `force=force` to `sync_tushare_market_data_resumable`. Change `_sync_daily_market_data_step` to accept the same keyword and forward it. Preserve all existing defaults so ordinary lightweight calls remain unchanged.

- [ ] **Step 4: Implement the guarded scheduled task**

Import `_is_open_trade_date` and `_sync_daily_market_data_step` from the existing pipeline. Implement:

```python
today = now_local().date()
with SessionLocal() as db:
    if not _is_open_trade_date(db, today.isoformat()):
        return {
            "trade_date": today.isoformat(),
            "status": "skipped",
            "message": "非交易日，已跳过全市场收盘同步。",
        }

acquired, lock_key = _acquire_daily_task_lock("daily-market-sync", today)
if not acquired:
    return {
        "trade_date": today.isoformat(),
        "status": "skipped",
        "message": "当日全市场收盘同步已运行或正在运行。",
        "lock_key": lock_key,
    }

step = _sync_daily_market_data_step(
    today.isoformat(),
    full_refresh=True,
    force=True,
)
return {"trade_date": today.isoformat(), **step.to_dict()}
```

- [ ] **Step 5: Run sync tests and commit**

Run:

```bash
.venv/bin/pytest tests/test_jobs_pipeline.py tests/test_jobs_api.py -q
```

Expected: all tests pass.

Commit:

```bash
git add services/collector/daily.py services/jobs/pipeline.py services/jobs/tasks.py tests/test_jobs_pipeline.py
git commit -m "fix: run scheduled full-market close sync"
```

### Task 3: Gate Candidates While Preserving Paper Exits

**Files:**
- Modify: `tests/test_jobs_pipeline.py`
- Modify: `tests/test_paper_simulator.py`
- Modify: `services/jobs/pipeline.py`
- Modify: `services/engine/paper/simulator.py`

- [ ] **Step 1: Write a failing paper-simulator exit-only test**

Extend the existing paper simulator test setup with one open position that reaches its stop and one eligible same-day plan. Call:

```python
result = run_daily_paper_simulation(
    trade_date="2026-07-13",
    execute_entries=False,
)

assert result.closed == 1
assert result.opened == 0
```

Also assert no filled buy order was created for the eligible plan.

- [ ] **Step 2: Run the simulator test and verify RED**

Run the exact new test:

```bash
.venv/bin/pytest tests/test_paper_simulator.py -q -k "entries_disabled"
```

Expected: FAIL because `run_daily_paper_simulation` has no `execute_entries` parameter.

- [ ] **Step 3: Add the minimal entry toggle**

Add `execute_entries: bool = True` to `run_daily_paper_simulation`. Keep the existing position-exit loop unchanged and wrap only the trade-plan entry loop:

```python
if execute_entries:
    for plan in load_trade_plans_for_trade_date(...):
        ...
```

Thread the keyword through `_run_daily_paper_simulation_step` in `services/jobs/pipeline.py`.

- [ ] **Step 4: Run simulator tests and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/test_paper_simulator.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Write failing after-close gate tests**

Add a focused test where `_daily_candidate_data_gate_step` returns a warning. Make `_discover_next_session_candidates_step` raise if called, capture the paper step keyword, and assert:

```python
assert "discover_next_session_candidates" in [step.name for step in result.steps]
blocked = next(step for step in result.steps if step.name == "discover_next_session_candidates")
assert blocked.status == "warning"
assert "数据完整性不足" in blocked.detail
assert captured["execute_entries"] is False
```

Update the existing successful after-close test to return an `ok` gate and assert `execute_entries is True`.

- [ ] **Step 6: Run the pipeline gate tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_jobs_pipeline.py -q -k "after_close_session"
```

Expected: FAIL because the gate step and branch do not exist.

- [ ] **Step 7: Implement the shared-health pipeline gate**

Add `_daily_candidate_data_gate_step(trade_date)` that calls `inspect_daily_data_health` and returns:

```python
PipelineStepResult(
    name="validate_daily_candidate_data",
    status="ok" if report.candidate_generation_allowed else "warning",
    detail=(
        f"候选数据门禁通过：日线 {report.eligible_daily_bar_count}/"
        f"{report.expected_security_count}，覆盖 {report.daily_coverage_ratio:.1%}。"
        if report.candidate_generation_allowed
        else "候选数据门禁未通过：" + "；".join(report.candidate_block_reasons)
    ),
    summary="候选数据可用" if report.candidate_generation_allowed else "数据完整性不足",
    details=report.candidate_block_reasons,
)
```

In `run_after_close_session`, run this gate immediately after `prepare_market_feature_universe`. If it passes, run normal discovery and tracking. If it does not, append a warning `discover_next_session_candidates` step instead of calling discovery, skip tracking, and call daily paper simulation with `execute_entries=False`. Continue paper reviews, regression, learning, and daily review; do not alter `run_intraday_trade_session`.

- [ ] **Step 8: Run pipeline and paper regression tests, then commit**

Run:

```bash
.venv/bin/pytest tests/test_jobs_pipeline.py tests/test_paper_simulator.py tests/test_realtime_quotes.py -q
```

Expected: all tests pass.

Commit:

```bash
git add services/jobs/pipeline.py services/engine/paper/simulator.py tests/test_jobs_pipeline.py tests/test_paper_simulator.py
git commit -m "feat: gate candidates on daily data readiness"
```

### Task 4: Clear Web Snapshot and Coverage Labels

**Files:**
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/dataHealthPanel.test.mjs`

- [ ] **Step 1: Write failing source-level display assertions**

Extend `dataHealthPanel.test.mjs`:

```javascript
assert(app.includes("snapshot_scope_label"), "市场宽度需要展示快照范围");
assert(app.includes("覆盖不足"), "低覆盖市场数据需要明确降级标识");
assert(app.includes("candidate_generation_allowed"), "数据健康面板需要展示候选门禁状态");
```

- [ ] **Step 2: Run the frontend test and verify RED**

Run:

```bash
cd apps/web && node src/dataHealthPanel.test.mjs
```

Expected: FAIL on the missing low-coverage or candidate-gate source text.

- [ ] **Step 3: Type the health response and update compact labels**

Add the five Task 1 fields to `DataHealth` in `apps/web/src/api.ts`.

Update the existing helpers without adding a new component:

```typescript
function marketBreadthText(overview: MarketOverview | null) {
  if (!overview) return "-";
  return `${overview.snapshot_scope_label} · ${overview.up_count}涨 ${overview.down_count}跌`;
}

function marketCoverageText(overview: MarketOverview | null) {
  if (!overview) return "-";
  const state = overview.is_full_market ? "覆盖可用" : "覆盖不足";
  return `${overview.stock_count}/${overview.active_security_count} 样本 / ${state} ${pct(overview.coverage_ratio)}`;
}
```

Use `marketCoverageText(marketOverview)` in the summary strip. Update the data pipeline status helper so `candidate_generation_allowed === false` displays `候选已阻断`, and include the daily coverage ratio in its detail text.

- [ ] **Step 4: Run frontend tests and build, then commit**

Run:

```bash
cd apps/web
node src/dataHealthPanel.test.mjs
node --experimental-strip-types src/stockLabels.test.ts
npm run build
```

Expected: both tests and the TypeScript/Vite build pass.

Commit:

```bash
git add apps/web/src/api.ts apps/web/src/App.tsx apps/web/src/dataHealthPanel.test.mjs
git commit -m "fix: label stale and incomplete market data"
```

### Task 5: Full First-Round Verification

**Files:**
- Verify only; modify a file only if a regression exposes a defect in this plan's scope.

- [ ] **Step 1: Run backend regression and lint**

```bash
.venv/bin/pytest \
  tests/test_data_health.py \
  tests/test_market_api.py \
  tests/test_jobs_pipeline.py \
  tests/test_jobs_api.py \
  tests/test_next_session_candidates.py \
  tests/test_paper_simulator.py \
  tests/test_realtime_quotes.py \
  -q --disable-warnings

.venv/bin/ruff check \
  services/engine/features/health.py \
  services/collector/daily.py \
  services/jobs/pipeline.py \
  services/jobs/tasks.py \
  services/engine/paper/simulator.py \
  apps/api/app/routers/market.py \
  tests/test_data_health.py \
  tests/test_market_api.py \
  tests/test_jobs_pipeline.py \
  tests/test_paper_simulator.py
```

Expected: zero test failures and zero Ruff errors.

- [ ] **Step 2: Run frontend verification**

```bash
cd apps/web
node src/dataHealthPanel.test.mjs
node --experimental-strip-types src/stockLabels.test.ts
npm run build
```

Expected: both tests pass and Vite completes a production build.

- [ ] **Step 3: Inspect the final diff and runtime-file safety**

```bash
git diff --check
git status --short
git diff --stat HEAD~4..HEAD
```

Expected: no whitespace errors; `.stock-dev.sqlite` and `dump.rdb` remain untracked and unstaged.

- [ ] **Step 4: Record verification evidence**

Report the exact test count, build result, the new gate thresholds, and any remaining external data-source limitation. Do not push while the configured local proxy is unavailable.
