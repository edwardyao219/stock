# Strong Benchmark Sample Funnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Count strong-start benchmark signals as completed, waiting, or unavailable on exact market trading-day horizons and show the funnel on the sector page.

**Architecture:** Reuse distinct `DailyBar.trade_date` values as the local market calendar. The tracking layer assigns exact horizon statuses and reasons, the current summary endpoint aggregates them without changing policy inputs, and the existing compact sector strip renders the counts.

**Tech Stack:** Python 3.12, SQLAlchemy, FastAPI/Pydantic, React/TypeScript, pytest, Node, Vite.

---

## File Map

- `services/engine/tracking/mainline.py`: exact trading-day outcomes and funnel aggregation.
- `apps/api/app/routers/market.py`: API models and 120-outcome window metadata.
- `apps/web/src/api.ts`: TypeScript contract.
- `apps/web/src/App.tsx`: compact funnel display.
- `tests/test_mainline_tracking.py`: exact-date and aggregation tests.
- `tests/test_market_api.py`: API contract test.
- `apps/web/src/mainlineOutcomeSummaryPanel.test.mjs`: UI contract test.

### Task 1: Resolve Exact Trading-Day Horizons

**Files:**
- Modify: `services/engine/tracking/mainline.py`
- Test: `tests/test_mainline_tracking.py`

- [ ] **Step 1: Write the failing test**

Create a strong signal on July 1. Add full-market proxy bars for July 1-5,
but omit the leader's July 4 third-target bar and give it a July 5 bar.

```python
outcome = list_confirmed_mainline_outcomes(db)[0]
assert outcome.horizons[3].status == "unavailable"
assert outcome.horizons[3].reason == "missing_target_close"
assert outcome.horizons[3].return_pct is None
assert outcome.horizons[5].status == "waiting"
assert outcome.horizons[5].reason == "awaiting_trade_day"
```

Add a second test with proxy market bars but no signal-day leader bar:

```python
outcome = list_confirmed_mainline_outcomes(db)[0]
assert outcome.horizons[1].status == "unavailable"
assert outcome.horizons[1].reason == "missing_signal_close"
assert outcome.horizons[1].return_pct is None
```

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q tests/test_mainline_tracking.py::test_mainline_outcome_does_not_shift_missing_target_to_a_later_bar
```

Expected: FAIL because `reason` and exact market-date matching do not exist.

- [ ] **Step 3: Implement the minimum exact-date resolver**

Add `reason` and change `_horizons` to accept the market calendar:

```python
@dataclass(frozen=True)
class MainlineHorizonOutcome:
    horizon: int
    status: str
    return_pct: float | None
    reason: str | None = None


def _horizons(
    *, bars: list[DailyBar], market_dates: list[date], signal_date: date
) -> dict[int, MainlineHorizonOutcome]:
    bars_by_date = {bar.trade_date: bar for bar in bars}
    signal_bar = bars_by_date.get(signal_date)
    if signal_bar is None or not signal_bar.close:
        return {
            horizon: MainlineHorizonOutcome(
                horizon, "unavailable", None, "missing_signal_close"
            )
            for horizon in MAINLINE_HORIZONS
        }
    future_dates = [item for item in market_dates if item > signal_date]
    result = {}
    for horizon in MAINLINE_HORIZONS:
        if len(future_dates) < horizon:
            result[horizon] = MainlineHorizonOutcome(
                horizon, "waiting", None, "awaiting_trade_day"
            )
            continue
        target = bars_by_date.get(future_dates[horizon - 1])
        if target is None or not target.close:
            result[horizon] = MainlineHorizonOutcome(
                horizon, "unavailable", None, "missing_target_close"
            )
            continue
        result[horizon] = MainlineHorizonOutcome(
            horizon,
            "completed",
            round(float(target.close) / float(signal_bar.close) - 1, 6),
        )
    return result
```

Query distinct ordered dates once in `list_confirmed_mainline_outcomes()` and
pass them to leader and candidate calls:

```python
market_dates = list(
    db.execute(
        select(DailyBar.trade_date).distinct().order_by(DailyBar.trade_date)
    ).scalars()
)
```

- [ ] **Step 4: Verify GREEN and commit**

```bash
.venv/bin/pytest -q tests/test_mainline_tracking.py
git add services/engine/tracking/mainline.py tests/test_mainline_tracking.py
git commit -m "fix: grade benchmarks on exact trading dates"
```

### Task 2: Aggregate And Expose Funnel Counts

**Files:**
- Modify: `services/engine/tracking/mainline.py`
- Modify: `apps/api/app/routers/market.py`
- Test: `tests/test_mainline_tracking.py`
- Test: `tests/test_market_api.py`

- [ ] **Step 1: Write failing summary assertions**

Use three strong outcomes with completed, waiting, and unavailable 3-day
states:

```python
assert summary[3]["total_signal_count"] == 3
assert summary[3]["completed_count"] == 1
assert summary[3]["waiting_count"] == 1
assert summary[3]["unavailable_count"] == 1
assert summary[3]["unavailable_reasons"] == {"missing_target_close": 1}
assert summary[3]["sample_count"] == 1
```

Extend the API test:

```python
assert summary.window_limit == 120
assert summary.horizons[0].total_signal_count == 0
assert summary.horizons[0].completed_count == 0
assert summary.horizons[0].waiting_count == 0
assert summary.horizons[0].unavailable_count == 0
assert summary.horizons[0].unavailable_reasons == {}
```

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest -q tests/test_mainline_tracking.py tests/test_market_api.py -k 'mainline or strong_benchmark'
```

Expected: FAIL because funnel fields and `window_limit` are absent.

- [ ] **Step 3: Add minimum aggregation**

Filter strong outcomes once per summary, preserve current completed return
values, and add:

```python
"total_signal_count": len(signal_outcomes),
"completed_count": len(completed),
"waiting_count": sum(item is None or item.status == "waiting" for item in horizon_rows),
"unavailable_count": len(unavailable),
"unavailable_reasons": {
    reason: sum(item.reason == reason for item in unavailable)
    for reason in ("missing_signal_close", "missing_target_close")
    if any(item.reason == reason for item in unavailable)
},
```

Only completed values continue to feed `sample_count`, returns, rates, and the
20-sample gate.

- [ ] **Step 4: Extend API models**

Add the five funnel fields to `MainlineOutcomeSummaryHorizonResponse`, add
`reason` to `MainlineOutcomeHorizonResponse`, and add:

```python
MAINLINE_OUTCOME_WINDOW_LIMIT = 120
```

Return `window_limit=MAINLINE_OUTCOME_WINDOW_LIMIT` and call the loader with
that same limit.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest -q tests/test_mainline_tracking.py tests/test_market_api.py -k 'mainline or strong_benchmark'
.venv/bin/ruff check services/engine/tracking/mainline.py apps/api/app/routers/market.py tests/test_mainline_tracking.py tests/test_market_api.py
git add services/engine/tracking/mainline.py apps/api/app/routers/market.py tests/test_mainline_tracking.py tests/test_market_api.py
git commit -m "feat: expose benchmark sample funnel"
```

### Task 3: Show One Compact Funnel Line

**Files:**
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/App.tsx`
- Test: `apps/web/src/mainlineOutcomeSummaryPanel.test.mjs`

- [ ] **Step 1: Write the failing UI contract**

```javascript
for (const text of ["样本漏斗", "总信号", "成熟", "等待", "异常"]) {
  if (!app.includes(text)) throw new Error(`样本漏斗缺少：${text}`);
}
for (const field of ["window_limit", "completed_count", "waiting_count", "unavailable_count", "unavailable_reasons"]) {
  if (!api.includes(field)) throw new Error(`样本漏斗接口缺少：${field}`);
}
```

- [ ] **Step 2: Verify RED**

```bash
cd apps/web
node --experimental-strip-types src/mainlineOutcomeSummaryPanel.test.mjs
```

Expected: FAIL on `样本漏斗`.

- [ ] **Step 3: Extend types and existing strip**

Add the API fields to `api.ts`. Render one additional `span` inside the current
`review-strip-meta`:

```tsx
<span>
  样本漏斗 / 近{mainlineOutcomeSummary.window_limit}条窗口 / 总信号 {mainlineOutcomeSummary.horizons[0]?.total_signal_count ?? 0} / {mainlineOutcomeSummary.horizons
    .map((item) => {
      const reasons = [
        item.unavailable_reasons.missing_signal_close
          ? `信号日缺失${item.unavailable_reasons.missing_signal_close}`
          : "",
        item.unavailable_reasons.missing_target_close
          ? `目标日缺失/停牌${item.unavailable_reasons.missing_target_close}`
          : "",
      ].filter(Boolean).join("、");
      return `${item.horizon}日 成熟${item.completed_count} 等待${item.waiting_count} 异常${item.unavailable_count}${reasons ? `（${reasons}）` : ""}`;
    })
    .join(" / ")}
</span>
```

Do not add a card, dependency, or stylesheet unless browser verification finds
actual overflow.

- [ ] **Step 4: Verify and commit**

```bash
cd apps/web
node --experimental-strip-types src/mainlineOutcomeSummaryPanel.test.mjs
npm run build
cd ../..
git add apps/web/src/api.ts apps/web/src/App.tsx apps/web/src/mainlineOutcomeSummaryPanel.test.mjs
git commit -m "feat: show benchmark sample funnel"
```

### Task 4: Live Verification And Push

**Files:**
- No code changes.

- [ ] **Step 1: Run final checks**

```bash
.venv/bin/pytest -q tests/test_mainline_tracking.py tests/test_market_api.py -k 'mainline or strong_benchmark'
.venv/bin/ruff check services/engine/tracking/mainline.py apps/api/app/routers/market.py tests/test_mainline_tracking.py tests/test_market_api.py
git diff --check
cd apps/web
node --experimental-strip-types src/mainlineOutcomeSummaryPanel.test.mjs
npm run build
```

- [ ] **Step 2: Restart API and inspect live services**

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/market/mainline-outcome-summary
.venv/bin/celery -A services.jobs.celery_app.celery_app inspect ping --timeout 5
```

Expected: health `ok`, summary contains `window_limit: 120`, and one worker
returns `pong`.

- [ ] **Step 3: Check responsive layout**

Use the local browser to verify the sector-page funnel is visible and has no
horizontal overflow at 1280px and 390px. Check page console errors.

- [ ] **Step 4: Push**

```bash
git push origin codex/startup-signal-replay
git status --short --branch
```

Expected: branch matches origin. `.stock-dev.sqlite` and `dump.rdb` remain
untracked and uncommitted.
