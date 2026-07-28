# Candidate Discovery Funnel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report a deterministic candidate-selection funnel before changing any candidate threshold or execution quota.

**Architecture:** Preserve current candidate selection. Return an additional diagnostic summary from `discover_next_session_candidates`, and add a concise rendering of it to the existing after-close candidate job output.

**Tech Stack:** Python 3.12, SQLAlchemy, pytest.

---

### Task 1: Candidate discovery diagnostics

**Files:**
- Modify: `services/engine/research_pool/candidates.py`
- Test: `tests/test_next_session_candidates.py`

- [x] **Step 1: Write the failing tests**

```python
def test_discovery_reports_selection_funnel(monkeypatch) -> None:
    result = discover_next_session_candidates(...)
    funnel = result["selection_funnel"]
    assert funnel["universe"] == 2
    assert funnel["hard_safety_rejected"] == 1


def test_discovery_reports_mode_qualification_and_truncation(monkeypatch) -> None:
    result = discover_next_session_candidates(...)
    funnel = result["selection_funnel"]
    assert funnel["formal_qualified"] >= funnel["formal_selected"]
    assert funnel["formal_ranked_out"] >= 0
```

- [x] **Step 2: Verify the tests fail**

Run: `pytest tests/test_next_session_candidates.py -k 'selection_funnel or research_slots' -v`

Expected: assertions fail because `selection_funnel` is absent.

- [x] **Step 3: Implement the smallest selection counters and result field**

```python
selection_funnel = {
    "universe": len(contexts),
    "hard_safety_rejected": 0,
    "strategy_matched": 0,
}

if not _passes_hard_safety_filters(context):
    selection_funnel["hard_safety_rejected"] += 1
    continue

result["selection_funnel"] = selection_funnel
```

Count mode qualification and rank truncation after mode-specific ranking. Keep every existing selection limit and candidate path unchanged.

- [x] **Step 4: Verify the focused tests pass**

Run: `pytest tests/test_next_session_candidates.py -k 'selection_funnel or research_slots' -v`

Expected: 2 passed.

### Task 2: Pipeline visibility and regression coverage

**Files:**
- Modify: `services/jobs/pipeline.py`
- Modify: `tests/test_next_session_candidates.py`
- Test: `tests/test_jobs_pipeline.py`

- [x] **Step 1: Write a failing pipeline-output test**

```python
assert "筛选漏斗" in result.details
assert "硬风控淘汰" in result.details
```

- [x] **Step 2: Verify it fails**

Run: `pytest tests/test_jobs_pipeline.py -k candidate -v`

Expected: assertion fails because the after-close detail does not render the funnel.

- [x] **Step 3: Add one compact funnel detail line**

```python
funnel = discovery.get("selection_funnel") or {}
details.insert(1, f"筛选漏斗：硬风控淘汰 {funnel.get('hard_safety_rejected', 0)} ...")
```

Do not alter job status, candidate notifications, or plan generation.

- [x] **Step 4: Verify focused tests and candidate suite**

Run: `pytest tests/test_next_session_candidates.py tests/test_jobs_pipeline.py -k 'candidate or funnel' -v`

Expected: all selected tests pass.

- [x] **Step 5: Run the full suite and commit**

Run: `pytest -q`

Expected: no failures.

```bash
git add docs/superpowers/specs/2026-07-28-candidate-discovery-funnel-design.md docs/superpowers/plans/2026-07-28-candidate-discovery-funnel.md services/engine/research_pool/candidates.py services/jobs/pipeline.py tests/test_next_session_candidates.py tests/test_jobs_pipeline.py
git commit -m "feat: expose candidate discovery funnel"
git push origin main
```
