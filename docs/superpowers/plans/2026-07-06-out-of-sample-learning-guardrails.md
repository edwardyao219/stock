# Out Of Sample Learning Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rolling train/validation guardrails so backtest learning only promotes factors that survive later out-of-sample samples.

**Architecture:** Keep the learning change inside `services/engine/backtest/learning.py`. Split each grouped backtest sample by `signal_date`, compute simple train and validation return metrics, and require both breadth and validation pass before positive recommendations are emitted.

**Tech Stack:** Python, SQLAlchemy model objects, pytest, ruff.

---

### Task 1: Add Regression Tests For Validation Failure And Pass

**Files:**
- Modify: `tests/test_backtest_learning.py`

- [ ] **Step 1: Write the failing validation-failure test**

Add a sector sample with older positive trades and newer negative trades. Persist the report, then assert `positive_learning_allowed` is false, `out_of_sample_passed` is false, no positive recommendation is saved, and the report text mentions sample-out validation.

- [ ] **Step 2: Run the failure test**

Run: `uv run pytest tests/test_backtest_learning.py::test_backtest_learning_blocks_positive_when_validation_fails -q`

Expected: FAIL because the current insight JSON has no out-of-sample fields and still allows positive learning from aggregate metrics.

- [ ] **Step 3: Write the validation-pass test**

Add a broad sector sample where both older train trades and newer validation trades are positive. Assert `positive_learning_allowed` is true, `out_of_sample_passed` is true, and positive recommendations still appear.

- [ ] **Step 4: Run both new tests**

Run: `uv run pytest tests/test_backtest_learning.py::test_backtest_learning_blocks_positive_when_validation_fails tests/test_backtest_learning.py::test_backtest_learning_allows_positive_when_train_and_validation_pass -q`

Expected: the failure test fails before implementation; the pass test may fail because fields do not exist yet.

### Task 2: Implement Low-Dimensional Train/Validation Metrics

**Files:**
- Modify: `services/engine/backtest/learning.py`

- [ ] **Step 1: Add a small return metrics dataclass**

Create a frozen dataclass with `sample_count`, `avg_return`, `win_rate`, `profit_factor`, and `total_return`. Use existing `_avg` and `_profit_factor` helpers.

- [ ] **Step 2: Add chronological split helper**

Sort trades by `(signal_date or date.min, symbol, id or 0)`. For groups with at least ten trades, use the latest 30% as validation with at least three validation samples. Smaller groups should return insufficient validation.

- [ ] **Step 3: Gate positive learning**

Keep existing breadth thresholds, then require `out_of_sample_passed`. Validation passes only when train and validation have enough samples, both average returns are positive, validation win rate is at least 45%, and validation profit factor is at least 1.05.

- [ ] **Step 4: Add transparent report fields**

Extend `BacktestLearningInsight` with train/validation sample counts, average returns, win rates, validation profit factor, total return, status, and pass flag. Mention validation status in `summary` and warning text.

- [ ] **Step 5: Pass the updated positive flag into suggestions**

Change `_suggestions` to receive `positive_learning_allowed` and validation guardrails, instead of recomputing only breadth internally.

### Task 3: Verify And Commit

**Files:**
- Test: `tests/test_backtest_learning.py`
- Test: `tests/test_plan_learning_adjustments.py`
- Test: `tests/test_strategy_fit_api.py`

- [ ] **Step 1: Run focused learning tests**

Run: `uv run pytest tests/test_backtest_learning.py -q`

Expected: all tests pass.

- [ ] **Step 2: Run adjacent regression tests**

Run: `uv run pytest tests/test_backtest_learning.py tests/test_plan_learning_adjustments.py tests/test_strategy_fit_api.py -q`

Expected: all tests pass.

- [ ] **Step 3: Run lint and diff checks**

Run: `uv run ruff check services/engine/backtest/learning.py tests/test_backtest_learning.py`

Expected: no lint errors.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 4: Commit and push**

Run: `git add docs/superpowers/plans/2026-07-06-out-of-sample-learning-guardrails.md services/engine/backtest/learning.py tests/test_backtest_learning.py`

Run: `git commit -m "feat: add out-of-sample learning guardrails"`

Run: `git push`

Expected: branch `codex/startup-signal-replay` is pushed to origin.
