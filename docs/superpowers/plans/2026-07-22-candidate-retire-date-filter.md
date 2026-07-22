# Candidate Retire Date Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure after-close status reports candidate retirement reasons only for the requested trade date while preserving the repository helper's all-history default.

**Architecture:** Reuse the existing `dropped:<date>` retirement tag. Add one optional filter argument to the shared summary helper and pass the API's existing `target_date`; no schema, query dialect, response, or frontend changes.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, pytest

---

### Task 1: Prove the cross-date aggregation bug

**Files:**
- Modify: `tests/test_research_pool.py`
- Modify: `tests/test_jobs_api.py`
- Test: `tests/test_research_pool.py`
- Test: `tests/test_jobs_api.py`

- [ ] **Step 1: Temporarily hide the pre-existing production edits**

Run:

```bash
git stash push -m "codex-tdd-retire-date-production" -- \
  apps/api/app/routers/jobs.py \
  services/engine/research_pool/repository.py
```

Expected: both production files disappear from `git status`; the design and plan commits remain on the branch.

- [ ] **Step 2: Add the repository-level failing test**

Import `retired_reason_summary` in `tests/test_research_pool.py`, then add:

```python
def test_retired_reason_summary_can_filter_by_dropped_date() -> None:
    items = [
        ResearchPoolItem(
            pool_name="experiment",
            symbol="000001",
            status="retired",
            tags_json={"tags": ["dropped:2026-07-21", "retire_reason:当日淘汰"]},
        ),
        ResearchPoolItem(
            pool_name="experiment",
            symbol="000002",
            status="retired",
            tags_json={"tags": ["dropped:2026-07-18", "retire_reason:历史淘汰"]},
        ),
        ResearchPoolItem(
            pool_name="experiment",
            symbol="000003",
            status="active",
            tags_json={"tags": ["dropped:2026-07-21", "retire_reason:仍在观察"]},
        ),
        ResearchPoolItem(
            pool_name="experiment",
            symbol="000004",
            status="retired",
            tags_json={"tags": ["dropped:2026-07-21"]},
        ),
    ]

    assert retired_reason_summary(items, "2026-07-21") == {"当日淘汰": 1}
    assert retired_reason_summary(items) == {"当日淘汰": 1, "历史淘汰": 1}
```

- [ ] **Step 3: Add the API-level failing test**

Import `ResearchPoolItem` in `tests/test_jobs_api.py`, then add:

```python
def test_after_close_status_filters_candidate_retire_reasons_by_trade_date(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(
        jobs,
        "read_after_close_status",
        lambda trade_date: {"trade_date": trade_date, "status": "ok", "message": "已完成"},
    )

    with session() as db:
        db.add_all(
            [
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000001",
                    status="retired",
                    tags_json={"tags": ["dropped:2026-07-21", "retire_reason:当日淘汰"]},
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="000002",
                    status="retired",
                    tags_json={"tags": ["dropped:2026-07-18", "retire_reason:历史淘汰"]},
                ),
            ]
        )
        db.commit()

        payload = jobs.get_after_close_status(db=db, trade_date="2026-07-21")

    assert payload.candidate_retire_reasons == {"当日淘汰": 1}
```

- [ ] **Step 4: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_research_pool.py::test_retired_reason_summary_can_filter_by_dropped_date \
  tests/test_jobs_api.py::test_after_close_status_filters_candidate_retire_reasons_by_trade_date
```

Expected: FAIL because the helper does not accept `dropped_date`; the API behavior also includes the historical reason when run independently.

### Task 2: Apply the minimal date filter

**Files:**
- Modify: `services/engine/research_pool/repository.py:41`
- Modify: `apps/api/app/routers/jobs.py:319`
- Test: `tests/test_research_pool.py`
- Test: `tests/test_jobs_api.py`

- [ ] **Step 1: Restore the pre-existing production edits**

Run:

```bash
git stash pop stash@{0}
```

Expected: the two production files return without conflicts and the TDD stash is dropped.

- [ ] **Step 2: Verify the shared helper contains only the minimal filter**

`services/engine/research_pool/repository.py` must contain:

```python
def retired_reason_summary(
    items: list[ResearchPoolItem],
    dropped_date: str | None = None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if item.status != "retired":
            continue
        tags = [str(tag) for tag in (item.tags_json or {}).get("tags", [])]
        if dropped_date and f"dropped:{dropped_date}" not in tags:
            continue
        reason = tag_value(tags, "retire_reason:")
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    return counts
```

- [ ] **Step 3: Verify the API passes its canonical target date**

`apps/api/app/routers/jobs.py` must call:

```python
retire_reasons = (
    retired_reason_summary(
        list(db.execute(select(ResearchPoolItem)).scalars()),
        target_date,
    )
    if db is not None
    else {}
)
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_research_pool.py::test_retired_reason_summary_can_filter_by_dropped_date \
  tests/test_jobs_api.py::test_after_close_status_filters_candidate_retire_reasons_by_trade_date
```

Expected: `2 passed`.

- [ ] **Step 5: Run the affected test modules**

Run:

```bash
.venv/bin/pytest -q tests/test_research_pool.py tests/test_jobs_api.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit the tested behavior**

Run:

```bash
git add \
  apps/api/app/routers/jobs.py \
  services/engine/research_pool/repository.py \
  tests/test_jobs_api.py \
  tests/test_research_pool.py
git commit -m "fix: scope candidate retirement reasons by date"
```

Expected: one commit containing only the two production files and two test files.

### Task 3: Full verification

**Files:**
- Verify: entire repository

- [ ] **Step 1: Run the complete backend suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: all tests pass with no failures.

- [ ] **Step 2: Check patch hygiene and final branch state**

Run:

```bash
git diff --check
git status --short --branch
git log --oneline --decorate -3
```

Expected: `git diff --check` has no output and the branch has no uncommitted files.
