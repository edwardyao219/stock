# Data Guard And Long Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent critical jobs from silently using the local sqlite fallback, then add a lightweight long replay baseline command for month-by-month strategy checks.

**Architecture:** Keep the existing database fallback for local imports and tests, but expose whether the active engine is the primary database or fallback sqlite. Critical pipelines and replay commands call a small guard before doing real market work. Long replay reuses existing walk-forward/replay code and reports non-compounded monthly and total return.

**Tech Stack:** Python, SQLAlchemy, pytest, existing `services.engine.backtest.walk_forward` utilities.

---

### Task 1: Guard Critical Jobs Against Fallback Sqlite

**Files:**
- Modify: `services/shared/database.py`
- Modify: `services/jobs/run_pipeline.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Write the failing test**

Add tests proving the database module reports fallback state and raises for critical jobs when fallback is active.

Run: `uv run pytest tests/test_database.py -q`

Expected: FAIL because the guard does not exist yet.

- [ ] **Step 2: Implement the minimal guard**

Add `is_database_fallback_active()` and `require_primary_database(reason: str)` to `services/shared/database.py`. Keep fallback available for tests/local import, but make critical jobs opt into the guard.

- [ ] **Step 3: Wire the guard into CLI pipeline**

Call `require_primary_database("run_pipeline")` near the start of `services/jobs/run_pipeline.py`, before stages touch data.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/test_database.py -q`

Expected: PASS.

### Task 2: Add Long Replay Baseline CLI

**Files:**
- Create: `services/engine/backtest/run_long_replay_baseline.py`
- Test: `tests/test_long_replay_baseline.py`

- [ ] **Step 1: Write the failing tests**

Test monthly bucketing and non-compounded totals with a tiny in-memory result object.

Run: `uv run pytest tests/test_long_replay_baseline.py -q`

Expected: FAIL because the module does not exist yet.

- [ ] **Step 2: Implement a small reporting module**

Add helpers that summarize replay candidates by month with `month_return = sum(candidate forward return) / candidate_count`, `total_return = sum(month_return)`, and max drawdown from non-compounded cumulative returns.

- [ ] **Step 3: Add CLI wrapper**

The command accepts `--start-date`, `--end-date`, `--horizon`, `--limit`, and `--candidate-scope`, calls the existing replay function, and prints a compact table.

- [ ] **Step 4: Verify on code and real data**

Run: `uv run pytest tests/test_long_replay_baseline.py -q`

Then run a bounded smoke check against MySQL:

`uv run python -m services.engine.backtest.run_long_replay_baseline --start-date 2026-05-01 --end-date 2026-06-30 --horizon 5 --limit 15`

Expected: command completes and prints monthly rows without writing trades or plans.
