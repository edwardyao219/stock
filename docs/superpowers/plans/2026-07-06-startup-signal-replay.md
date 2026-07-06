# Startup Signal Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add historical replay summaries for the startup observation signal so we can judge whether high startup scores actually hold up over 5/10/20 trading days.

**Architecture:** Carry `startup_signal_score`, `startup_signal_label`, and `startup_signal_reasons` from discovered candidates into walk-forward replay candidates. Summarize startup candidates by score bucket without changing candidate selection, action promotion, or portfolio rules.

**Tech Stack:** Python walk-forward replay, FastAPI response dictionaries, TypeScript API types and React display helpers.

---

### Task 1: Replay Candidate Startup Fields

**Files:**
- Modify: `services/engine/backtest/walk_forward.py`
- Test: `tests/test_walk_forward_replay.py`

- [ ] **Step 1: Write the failing test**

Add a test that builds a startup preheat discovery item with `startup_signal_score=82.5`, then asserts the replay candidate carries that score and label.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_walk_forward_replay.py -q -k startup_signal`

Expected: FAIL because `WalkForwardCandidate` does not expose startup signal fields in replay.

- [ ] **Step 3: Write minimal implementation**

Add optional startup signal fields to `WalkForwardCandidate` and populate them from discovery item keys:

```python
startup_signal_score=_optional_float(item, "startup_signal_score"),
startup_signal_label=(str(item.get("startup_signal_label")) if item.get("startup_signal_label") else None),
startup_signal_reasons=[str(reason) for reason in item.get("startup_signal_reasons") or []],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_walk_forward_replay.py -q -k startup_signal`

Expected: PASS.

### Task 2: Startup Score Bucket Summaries

**Files:**
- Modify: `services/engine/backtest/walk_forward.py`
- Test: `tests/test_walk_forward_replay.py`

- [ ] **Step 1: Write the failing test**

Add a summary test with two startup candidates: one score `82.5` and positive guarded return, one score `62.0` and negative guarded return. Assert `startup_signal_horizons[5]["high"]["guarded"]["total_return"]` and `startup_signal_horizons[5]["low"]["guarded"]["total_return"]` are separated.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_walk_forward_replay.py -q -k startup_signal`

Expected: FAIL because `startup_signal_horizons` is missing.

- [ ] **Step 3: Write minimal implementation**

Add score bucket helper:

```python
def _startup_signal_bucket(candidate: WalkForwardCandidate) -> str | None:
    score = candidate.startup_signal_score
    if score is None:
        return None
    if score >= 80.0:
        return "high"
    if score >= 70.0:
        return "medium"
    return "low"
```

Add per-horizon summary function using existing `_return_summary` and guarded returns.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_walk_forward_replay.py -q -k startup_signal`

Expected: PASS.

### Task 3: API and Frontend Exposure

**Files:**
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/replayInsights.ts`
- Modify: `apps/web/src/App.tsx`

- [ ] **Step 1: Type the new replay summary field**

Add `startup_signal_horizons` to `ReplayScopeSummary` as `Record<number, Record<string, ReplayHorizonSummary>>`.

- [ ] **Step 2: Show the key result in startup rows**

Extend startup-preheat insight rows with high-score guarded return when available.

- [ ] **Step 3: Build frontend**

Run: `npm run build` in `apps/web`.

Expected: TypeScript and Vite build pass.

### Task 4: Verification and Real Replay

**Files:**
- Modify only if verification exposes a real defect.

- [ ] **Step 1: Run backend tests**

Run: `uv run pytest tests/test_walk_forward_replay.py tests/test_strategy_fit_api.py -q`

Expected: PASS.

- [ ] **Step 2: Run lint**

Run: `uv run ruff check services/engine/backtest/walk_forward.py tests/test_walk_forward_replay.py`

Expected: PASS.

- [ ] **Step 3: Run a real 2026-05/2026-06 replay API check**

Call `/rules/candidate-replay-effect?start_date=2026-05-01&end_date=2026-06-30&limit=15&min_coverage_ratio=0.70&include_fundamentals=false` and inspect startup signal buckets in the JSON.

Expected: API returns successfully and includes startup signal bucket summaries when startup candidates have scores.
