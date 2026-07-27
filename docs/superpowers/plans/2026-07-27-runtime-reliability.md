# Runtime Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scheduled research outputs accurately represent data readiness and make runtime maintenance measurable and safe.

**Architecture:** Keep job state in the existing Redis status payload, use pipeline step warnings for incomplete inputs, and provide maintenance through an explicit standard-library command. Preserve existing naive UTC database storage with one shared time helper.

**Tech Stack:** Python 3.11+, Celery, Redis, pytest, standard library `pathlib` and `datetime`.

---

### Task 1: Surface empty feature computation

**Files:**
- Modify: `services/jobs/pipeline.py`
- Test: `tests/test_jobs_pipeline.py`

- [ ] Add a failing test that a feature computation returning zero stock features is `warning`.
- [ ] Run the focused test and confirm the current result is `ok`.
- [ ] Update `_compute_features_step` to produce a data-readiness warning only for zero output.
- [ ] Re-run the focused pipeline tests.

### Task 2: Measure rule regression

**Files:**
- Modify: `services/jobs/tasks.py`, `services/jobs/status.py`
- Test: `tests/test_jobs_pipeline.py`, `tests/test_after_close_status.py`

- [ ] Add a failing task test for elapsed seconds and completion status.
- [ ] Use `time.monotonic()` around the existing regression call and merge the result into status.
- [ ] Re-run focused task and status tests.

### Task 3: Add log maintenance command

**Files:**
- Create: `services/jobs/log_maintenance.py`
- Test: `tests/test_log_maintenance.py`

- [ ] Add failing tests for dry-run selection and explicit archive behavior in a temporary directory.
- [ ] Implement only named log-file discovery, age filtering, gzip archive, and dry-run output.
- [ ] Re-run the command tests.

### Task 4: Replace deprecated UTC calls

**Files:**
- Modify: `services/shared/time.py` and each file found by `rg 'datetime.utcnow' services apps`
- Test: `tests/test_time.py`

- [ ] Add a failing naive-UTC contract test.
- [ ] Add `now_utc()` and replace direct calls without changing local-time scheduling calls.
- [ ] Run focused time and affected repository tests.

### Task 5: Verify and deliver

- [ ] Run `pytest -q`, `ruff check services apps tests`, and `git diff --check`.
- [ ] Commit the scoped changes directly on `main`.
- [ ] Push `main`; retry only transient network failures and report any remaining external block.
