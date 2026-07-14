# Startup Signal Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show unmistakable startup-preheat and startup-confirmed signals with historical 5/10/20-day evidence and each current candidate's realised return since the signal date.

**Architecture:** Add a read-only startup tracking service which joins current workspace startup tags to strict signal-date/last-date bars and reuses completed candidate walk-forward replay summaries for historical evidence. Expose it through the workspace router and render one compact strip in the existing candidate-tier area. The feature is observational only: it cannot alter ranking, plans, confidence or entry logic.

**Tech Stack:** Python 3.12, SQLAlchemy, FastAPI, pytest, React 19, TypeScript, Vite.

---

### Task 1: Startup Tracking Service

**Files:**
- Create: `services/engine/tracking/startup.py`
- Test: `tests/test_startup_tracking.py`

- [ ] **Step 1: Write failing strict-date and progress tests**

Create two startup-tagged `WorkspaceItem`-equivalent inputs and daily bars. Assert a preheat tag maps to `startup_preheat`, an expansion tag maps to `startup_confirmed`, return uses signal-date close, and 5/10/20 progress is `completed` only after that many subsequent trading bars.

```python
assert row.signal_type == "startup_preheat"
assert row.realised_return == 0.10
assert row.horizons[5].status == "completed"
assert row.horizons[10].status == "in_progress"
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_startup_tracking.py -q`

Expected: import failure because the tracking service does not exist.

- [ ] **Step 3: Implement minimal tag, bar and progress helpers**

Add `StartupTrackingRow`, `StartupHistoricalMetric`, and helpers that:

- classify only `candidate_pool:startup_preheat` and `candidate_pool:expansion_confirm`;
- parse only ISO-date candidate tags as signal dates;
- query `DailyBar` with `trade_date >= signal_date`, never a prior bar;
- calculate close-to-close realised return and completed/in-progress 5/10/20 horizons;
- return `None` / `data_pending` for missing bars.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/pytest tests/test_startup_tracking.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/engine/tracking/startup.py tests/test_startup_tracking.py
git commit -m "feat: calculate startup candidate tracking"
```

### Task 2: Historical Replay Evidence

**Files:**
- Modify: `services/engine/tracking/startup.py`
- Modify: `apps/api/app/routers/rules.py`
- Test: `tests/test_startup_tracking.py`
- Test: `tests/test_walk_forward_replay.py`

- [ ] **Step 1: Write failing completed-sample tests**

Build a replay summary containing completed and incomplete forward returns. Assert each signal type returns 5/10/20-day sample count, win rate, median raw return and median guarded return using only non-`None` completed observations.

```python
assert evidence["startup_preheat"][5].sample_count == 2
assert evidence["startup_preheat"][5].win_rate == 0.5
assert evidence["startup_preheat"][5].median_raw_return == 0.03
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_startup_tracking.py tests/test_walk_forward_replay.py -q -k "startup_tracking or completed_startup"`

Expected: failure because the startup evidence adapter does not exist.

- [ ] **Step 3: Reuse replay cache data**

Add a small adapter that reads `startup_signal_horizons` from the existing candidate replay-effect payload, maps the existing buckets to the two visible signal types, and preserves `sample_count`, `win_rate`, median raw and guarded returns. Do not rerun walk-forward replay per request and do not use incomplete observations.

- [ ] **Step 4: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/test_startup_tracking.py tests/test_walk_forward_replay.py -q
git add services/engine/tracking/startup.py apps/api/app/routers/rules.py tests/test_startup_tracking.py tests/test_walk_forward_replay.py
git commit -m "feat: expose startup replay evidence"
```

### Task 3: Workspace API

**Files:**
- Modify: `apps/api/app/routers/workspace.py`
- Test: `tests/test_workspace_api.py`

- [ ] **Step 1: Write failing endpoint tests**

Call `GET /workspace/startup-tracking` against a session with a preheat candidate, a confirmed candidate and a manual candidate. Assert only automatic startup rows appear and the response separates `historical` from `current_tracking`.

```python
assert [row["symbol"] for row in payload] == ["000001", "000002"]
assert payload[0]["signal_label"] == "启动观察"
assert "historical" in payload[0]
assert "current_tracking" in payload[0]
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_workspace_api.py -q -k "startup_tracking"`

Expected: route missing.

- [ ] **Step 3: Add typed read-only response and route**

Define Pydantic response models for signals, horizons and metrics. Load current automatic workspace candidate items, pass their tags to the tracking service, attach the cached replay evidence, and return `[]` for no startup candidates. Do not mutate candidate rows.

- [ ] **Step 4: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/test_workspace_api.py tests/test_startup_tracking.py -q
git add apps/api/app/routers/workspace.py tests/test_workspace_api.py
git commit -m "feat: add startup tracking workspace API"
```

### Task 4: Candidate and After-Close Presentation

**Files:**
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/candidateTiers.ts`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/src/candidateTiers.typecheck.ts`
- Test: `apps/web/src/startupTrackingPanel.test.mjs`

- [ ] **Step 1: Write failing source assertions**

Create `startupTrackingPanel.test.mjs` which asserts `启动追踪`, `启动观察`, `启动确认`, `历史验证`, `当前跟踪`, and `进行中` appear in the candidate area and that the UI reads the startup tracking API rather than calculating returns locally.

- [ ] **Step 2: Verify RED**

Run: `cd apps/web && node src/startupTrackingPanel.test.mjs`

Expected: missing startup tracking panel strings/API call.

- [ ] **Step 3: Add compact startup strip**

Add API interfaces and `fetchStartupTracking`. Fetch it alongside workspace stocks. Render a compact unframed strip only for nonempty rows, with a yellow preheat badge, green confirmed badge, two historical/current groups and fixed-width horizon cells. Extend candidate-tier summary with startup counts in the after-close drawer.

- [ ] **Step 4: Verify frontend and commit**

```bash
cd apps/web
node src/startupTrackingPanel.test.mjs
node src/candidateTiers.typecheck.ts
npm run build
git add src/api.ts src/App.tsx src/candidateTiers.ts src/styles.css src/startupTrackingPanel.test.mjs
git commit -m "feat: show startup tracking evidence"
```

### Task 5: Full Verification

**Files:** Verify only.

- [ ] **Step 1: Run backend regression**

```bash
.venv/bin/pytest tests/test_startup_tracking.py tests/test_workspace_api.py tests/test_walk_forward_replay.py tests/test_next_session_candidates.py -q --disable-warnings
```

- [ ] **Step 2: Run static and frontend checks**

```bash
.venv/bin/ruff check services/engine/tracking/startup.py apps/api/app/routers/workspace.py tests/test_startup_tracking.py tests/test_workspace_api.py
cd apps/web && node src/startupTrackingPanel.test.mjs && node src/candidateTiers.typecheck.ts && npm run build
```

- [ ] **Step 3: Check Git safety**

```bash
git diff --check
git status --short
```

Expected: only `.stock-dev.sqlite` and `dump.rdb` remain untracked.
