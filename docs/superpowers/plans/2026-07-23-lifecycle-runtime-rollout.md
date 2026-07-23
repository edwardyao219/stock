# Startup Lifecycle Runtime Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load the current `main` lifecycle code into the local API and Celery worker, then verify it through read-only runtime probes.

**Architecture:** The existing `stock-api-funnel` screen owns Uvicorn, and launchd owns the worker and beat. Restart only the API screen and the idle launchd worker; retain beat because its schedule is unchanged and do not enqueue any market task.

**Tech Stack:** macOS launchd, GNU screen, Uvicorn, Celery, FastAPI, curl, Python standard library JSON parser

---

### Task 1: Confirm the safe restart window

**Files:**
- Verify: `/Users/yaotianshun/stock/logs/celery-worker.log`
- Verify: live API and Celery processes

- [ ] **Step 1: Verify API and worker availability**

Run:

```bash
curl --fail --silent --show-error --max-time 3 http://127.0.0.1:8000/health
.venv/bin/celery -A services.jobs.celery_app.celery_app inspect active --timeout=2
screen -ls
launchctl print "gui/$(id -u)/com.stock-research.celery-worker" | rg 'state =|pid =|working directory'
```

Expected: API health returns `status: ok`; exactly one Celery node reports `empty`; a detached `stock-api-funnel` screen exists; launchd reports the worker `state = running` in `/Users/yaotianshun/stock`.

- [ ] **Step 2: Stop if the worker becomes active**

Do not restart anything when `inspect active` contains a task. Record the returned task name and end the rollout; retry only during a future empty window.

### Task 2: Restart the API screen and prove the new response contract

**Files:**
- Verify: `apps/api/app/routers/jobs.py:318-333`
- Verify: `apps/api/app/routers/workspace.py:1307-1325`

- [ ] **Step 1: Gracefully stop the existing API screen**

Run:

```bash
screen -S stock-api-funnel -X stuff $'\003'
for attempt in {1..10}; do
  if ! curl --silent --max-time 1 http://127.0.0.1:8000/health >/dev/null; then
    break
  fi
  sleep 0.5
done
if curl --silent --max-time 1 http://127.0.0.1:8000/health >/dev/null; then
  echo 'API did not stop; refusing to start a second server.' >&2
  exit 1
fi
```

Expected: the old process exits and 8000 is unavailable before a replacement is created.

- [ ] **Step 2: Start one replacement screen from the repository root**

Run:

```bash
screen -dmS stock-api-funnel bash -lc \
  'cd /Users/yaotianshun/stock && exec .venv/bin/uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000'
```

Expected: `screen -ls` shows one detached `stock-api-funnel` session.

- [ ] **Step 3: Probe API recovery and lifecycle response fields**

Run:

```bash
for attempt in {1..10}; do
  if curl --fail --silent --max-time 2 http://127.0.0.1:8000/health >/dev/null; then
    break
  fi
  sleep 0.5
done
curl --fail --silent --show-error --max-time 3 http://127.0.0.1:8000/health
curl --fail --silent --show-error --max-time 3 \
  'http://127.0.0.1:8000/jobs/after-close/status?trade_date=2026-07-22' \
  | .venv/bin/python -c 'import json, sys; payload = json.load(sys.stdin); assert "candidate_retire_reasons" in payload; print(payload["status"], payload["candidate_retire_reasons"])'
curl --fail --silent --show-error --max-time 3 \
  'http://127.0.0.1:8000/workspace/startup-tracking?pool_name=experiment' \
  | .venv/bin/python -c 'import json, sys; payload = json.load(sys.stdin); assert isinstance(payload, list); print(f"startup_tracking_rows={len(payload)}")'
```

Expected: health succeeds, after-close response includes `candidate_retire_reasons`, and startup tracking returns a JSON list. Empty tracking data is valid.

### Task 3: Restart only the idle worker and verify registration

**Files:**
- Verify: `services/jobs/tasks.py:381-545`
- Verify: `services/jobs/celery_app.py:16-97`

- [ ] **Step 1: Recheck activity immediately before restart**

Run:

```bash
.venv/bin/celery -A services.jobs.celery_app.celery_app inspect active --timeout=2
```

Expected: the node remains `empty`. Stop the rollout if a task appears.

- [ ] **Step 2: Restart the existing launchd worker without touching beat**

Run:

```bash
launchctl kickstart -k "gui/$(id -u)/com.stock-research.celery-worker"
```

Expected: launchd replaces the worker process. Do not run any command against `com.stock-research.celery-beat`.

- [ ] **Step 3: Verify worker response, task registration, and idle state**

Run:

```bash
for attempt in {1..10}; do
  if .venv/bin/celery -A services.jobs.celery_app.celery_app inspect ping --timeout=2 | rg -q 'pong'; then
    break
  fi
  sleep 0.5
done
.venv/bin/celery -A services.jobs.celery_app.celery_app inspect ping --timeout=2
.venv/bin/celery -A services.jobs.celery_app.celery_app inspect registered --timeout=2 \
  | rg 'capture_intraday_market_turn_snapshot_task|monitor_paper_positions_realtime_task'
.venv/bin/celery -A services.jobs.celery_app.celery_app inspect active --timeout=2
launchctl print "gui/$(id -u)/com.stock-research.celery-worker" | rg 'state =|pid =|working directory'
```

Expected: one worker returns `pong`, both scheduled task names are registered, active work is empty, and launchd reports a single running worker in the repository directory.

### Task 4: Record rollout evidence without altering market state

**Files:**
- Modify: `docs/AI_HANDOFF_2026-07-22.md`

- [ ] **Step 1: Append runtime evidence**

Add a dated entry under the verification baseline stating the API and worker were restarted from `main`, API lifecycle fields were observed, worker registration was checked, beat was intentionally retained, and no market task or notification was manually triggered. Include only command results and process identifiers; do not include credentials, webhook URLs, database records, or log payloads.

- [ ] **Step 2: Check and commit the handoff update**

Run:

```bash
git diff --check
git add docs/AI_HANDOFF_2026-07-22.md
git commit -m 'docs: record lifecycle runtime rollout'
git push origin main
```

Expected: whitespace check has no output and the handoff evidence is pushed to `origin/main`.
