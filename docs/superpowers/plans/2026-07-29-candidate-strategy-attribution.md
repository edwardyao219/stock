# Candidate Strategy Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make candidate walk-forward replay invalidate stale discoveries and report raw and guarded outcomes by selected strategy and month.

**Architecture:** Extend `WalkForwardCandidate` with optional selected-rule identity and group the existing replay returns by that identity. Extend the existing monthly-shard merger and bump both exact-match cache versions; do not add a service, endpoint, table, dependency, or live ranking feedback.

**Tech Stack:** Python 3.12, dataclasses, SQLAlchemy, FastAPI payload helpers, pytest, Ruff

---

### Task 1: Preserve selected rule identity

**Files:**
- Modify: `services/engine/backtest/walk_forward.py:123-145`
- Modify: `services/engine/backtest/walk_forward.py:2768-2808`
- Test: `tests/test_walk_forward_replay.py`

- [ ] **Step 1: Add a failing identity-transfer assertion**

In `test_candidate_walk_forward_replay_carries_sector_strength_context`, add
these fields to the fake discovery item and assert them on the replay candidate:

```python
"selected_rule_id": "R009",
"selected_rule_name": "[均值回归] 价值蓄势",

assert candidate.selected_rule_id == "R009"
assert candidate.selected_rule_name == "[均值回归] 价值蓄势"
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
.venv/bin/pytest tests/test_walk_forward_replay.py::test_candidate_walk_forward_replay_carries_sector_strength_context -q
```

Expected: FAIL because `WalkForwardCandidate` has no selected-rule fields.

- [ ] **Step 3: Add optional fields and transfer them**

Add after the existing optional list fields:

```python
selected_rule_id: str | None = None
selected_rule_name: str | None = None
```

Pass the discovery values when constructing `WalkForwardCandidate`:

```python
selected_rule_id=(
    str(item.get("selected_rule_id")) if item.get("selected_rule_id") else None
),
selected_rule_name=(
    str(item.get("selected_rule_name"))
    if item.get("selected_rule_name")
    else None
),
```

- [ ] **Step 4: Verify the test passes**

Run the Step 2 command again. Expected: PASS.

### Task 2: Summarize outcomes by selected rule

**Files:**
- Modify: `services/engine/backtest/walk_forward.py`
- Test: `tests/test_walk_forward_replay.py`

- [ ] **Step 1: Add a failing rule-summary test**

Create `test_summarize_walk_forward_replay_groups_selected_rules_and_unmatched`.
Build two `WalkForwardDay` values containing candidates for R002, R008, two
R009 candidates, and one candidate with no rule. Use January and February entry
dates and 5-day raw/guarded returns. Assert:

```python
assert summary["rule_counts"] == [
    {"rule_id": "R002", "rule_name": "主升浪回踩", "count": 1},
    {"rule_id": "R008", "rule_name": "[均值回归] 超跌修复", "count": 1},
    {"rule_id": "R009", "rule_name": "[均值回归] 价值蓄势", "count": 2},
    {"rule_id": "unmatched", "rule_name": "未匹配策略", "count": 1},
]
assert summary["rule_horizons"][5]["R009"]["raw"] == {
    "sample_count": 2,
    "avg_return": 0.04,
    "win_rate": 0.5,
    "total_return": 0.08,
}
assert summary["rule_horizons"][5]["R009"]["guarded"]["total_return"] == 0.05
assert summary["rule_horizons"][5]["unmatched"]["raw"]["sample_count"] == 1
assert summary["monthly_rule_horizons"][5]["2026-01"]["R009"]["raw"][
    "total_return"
] == -0.02
assert summary["monthly_rule_horizons"][5]["2026-02"]["R009"]["raw"][
    "total_return"
] == 0.10
```

Use R009 raw returns `-0.02` and `0.10`, guarded returns `-0.03` and
`0.08`; use raw/guarded pairs `0.05/0.03` for R002, `0.06/0.04` for R008,
and `0.01/0.0` for the unmatched candidate.

- [ ] **Step 2: Verify the summary test fails**

Run:

```bash
.venv/bin/pytest tests/test_walk_forward_replay.py::test_summarize_walk_forward_replay_groups_selected_rules_and_unmatched -q
```

Expected: FAIL with missing `rule_counts`.

- [ ] **Step 3: Add rule normalization and grouped summaries**

Add beside the selection-mode summary helpers:

```python
UNMATCHED_RULE_ID = "unmatched"
UNMATCHED_RULE_NAME = "未匹配策略"


def _candidate_rule_id(candidate: WalkForwardCandidate) -> str:
    return str(candidate.selected_rule_id or "").strip() or UNMATCHED_RULE_ID


def _candidate_rule_names(candidates: list[WalkForwardCandidate]) -> dict[str, str]:
    names: dict[str, str] = {}
    for candidate in candidates:
        rule_id = _candidate_rule_id(candidate)
        if rule_id == UNMATCHED_RULE_ID:
            names.setdefault(rule_id, UNMATCHED_RULE_NAME)
            continue
        rule_name = str(candidate.selected_rule_name or "").strip()
        if rule_name and names.get(rule_id, rule_id) == rule_id:
            names[rule_id] = rule_name
        else:
            names.setdefault(rule_id, rule_id)
    return names


def _rule_return_summaries(
    candidates: list[WalkForwardCandidate], *, horizon: int
) -> dict[str, dict[str, Any]]:
    names = _candidate_rule_names(candidates)
    summaries: dict[str, dict[str, Any]] = {}
    for rule_id in sorted(names):
        selected = [
            item for item in candidates if _candidate_rule_id(item) == rule_id
        ]
        summaries[rule_id] = {
            "rule_name": names[rule_id],
            "raw": _return_summary(
                [
                    value
                    for item in selected
                    if (value := item.forward_returns.get(horizon)) is not None
                ]
            ),
            "guarded": _return_summary(
                [
                    value
                    for item in selected
                    if (value := item.guarded_forward_returns.get(horizon)) is not None
                ]
            ),
        }
    return summaries


def _monthly_rule_return_summaries(
    candidates: list[WalkForwardCandidate], *, horizon: int
) -> dict[str, dict[str, Any]]:
    return {
        month: _rule_return_summaries(
            [item for item in candidates if _month_key(item.entry_date) == month],
            horizon=horizon,
        )
        for month in sorted({_month_key(item.entry_date) for item in candidates})
    }
```

- [ ] **Step 4: Expose counts, horizons, and monthly horizons**

In `summarize_walk_forward_replay`, derive names and counts from the existing
post-noise-filter `candidates`, populate `_rule_return_summaries` inside the
horizon loop, and return:

```python
"rule_counts": [
    {"rule_id": rule_id, "rule_name": rule_names[rule_id], "count": rule_counts[rule_id]}
    for rule_id in sorted(rule_counts)
],
"rule_horizons": rule_horizon_summaries,
"monthly_rule_horizons": {
    horizon: _monthly_rule_return_summaries(candidates, horizon=horizon)
    for horizon in horizons
},
```

- [ ] **Step 5: Run summary regressions**

Run:

```bash
.venv/bin/pytest tests/test_walk_forward_replay.py -k 'summarize_walk_forward_replay or carries_sector_strength_context' -q
```

Expected: PASS.

### Task 3: Merge attribution across monthly API shards

**Files:**
- Modify: `apps/api/app/routers/rules.py:282-345`
- Modify: `apps/api/app/routers/rules.py:453-539`
- Test: `tests/test_strategy_fit_api.py`

- [ ] **Step 1: Extend the shard fixture and failing assertions**

Add `rule_counts`, `rule_horizons`, and `monthly_rule_horizons` to
`_candidate_scope_summary`, using R009 and the fixture's existing `metric` and
`guarded_metric`. Extend
`test_candidate_replay_monthly_merge_uses_simple_sum_without_compounding`:

```python
scope = merged["scopes"]["action_long"]
assert scope["rule_counts"] == [
    {"rule_id": "R009", "rule_name": "[均值回归] 价值蓄势", "count": 5}
]
assert scope["rule_horizons"][20]["R009"]["guarded"]["total_return"] == 0.2
assert sorted(scope["monthly_rule_horizons"][20]) == ["2026-05", "2026-06"]
```

- [ ] **Step 2: Verify the shard test fails**

Run:

```bash
.venv/bin/pytest tests/test_strategy_fit_api.py::test_candidate_replay_monthly_merge_uses_simple_sum_without_compounding -q
```

Expected: FAIL with missing merged `rule_counts`.

- [ ] **Step 3: Preserve `rule_name` in category merging**

Replace the single-label copy in `_merge_category_horizons` with:

```python
for label_key in ("label", "rule_name"):
    label = next(
        (
            item.get(label_key)
            for item in category_items
            if isinstance(item, dict) and item.get(label_key)
        ),
        None,
    )
    if label:
        row[label_key] = label
```

- [ ] **Step 4: Merge the three new fields**

Add to `_merge_candidate_replay_scope_summaries`:

```python
"rule_counts": _merge_count_rows(summaries, "rule_counts", "rule_id"),
"rule_horizons": _merge_category_horizons(
    summaries, "rule_horizons", horizons=horizons
),
"monthly_rule_horizons": _merge_monthly_horizons(
    summaries, "monthly_rule_horizons", horizons=horizons
),
```

- [ ] **Step 5: Run merger regressions**

Run:

```bash
.venv/bin/pytest tests/test_strategy_fit_api.py -k 'candidate_replay_monthly_merge or builds_range_from_monthly_shards' -q
```

Expected: PASS.

### Task 4: Invalidate both stale cache layers

**Files:**
- Modify: `services/engine/backtest/walk_forward.py:40`
- Modify: `apps/api/app/routers/rules.py:45`
- Test: `tests/test_walk_forward_replay.py`
- Test: `tests/test_strategy_fit_api.py`

- [ ] **Step 1: Add failing version assertions**

Extend `test_candidate_discovery_cache_version_fits_database_column` and add an
API cache test:

```python
assert walk_forward.CANDIDATE_DISCOVERY_CACHE_VERSION == "candidate-v6-rule-attribution"


def test_candidate_replay_effect_cache_version_includes_rule_attribution() -> None:
    assert rules.CANDIDATE_REPLAY_EFFECT_CACHE_VERSION == "candidate-replay-effect-v5"
```

- [ ] **Step 2: Verify both tests fail**

Run:

```bash
.venv/bin/pytest tests/test_walk_forward_replay.py::test_candidate_discovery_cache_version_fits_database_column tests/test_strategy_fit_api.py::test_candidate_replay_effect_cache_version_includes_rule_attribution -q
```

Expected: FAIL on both old constants.

- [ ] **Step 3: Update exact-match cache versions**

```python
CANDIDATE_DISCOVERY_CACHE_VERSION = "candidate-v6-rule-attribution"
CANDIDATE_REPLAY_EFFECT_CACHE_VERSION = "candidate-replay-effect-v5"
```

- [ ] **Step 4: Run cache regressions**

Run:

```bash
.venv/bin/pytest tests/test_walk_forward_replay.py -k 'candidate_discovery_cache or snapshot' -q
.venv/bin/pytest tests/test_strategy_fit_api.py -k 'candidate_replay_effect_cache or rule_attribution' -q
```

Expected: PASS. Old cache files and rows remain untouched but no longer match.

### Task 5: Regression and delivery

**Files:**
- Modify: `docs/superpowers/plans/2026-07-29-candidate-strategy-attribution.md`

- [ ] **Step 1: Run focused cross-module tests**

```bash
.venv/bin/pytest tests/test_walk_forward_replay.py tests/test_strategy_fit_api.py tests/test_jobs_pipeline.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the complete suite**

```bash
.venv/bin/pytest -q
```

Expected: all tests pass; the existing SQLAlchemy `LargePortableJSON.cache_ok`
warning may remain.

- [ ] **Step 3: Run static and diff checks**

```bash
.venv/bin/ruff check --ignore E501 services/engine/backtest/walk_forward.py apps/api/app/routers/rules.py tests/test_walk_forward_replay.py tests/test_strategy_fit_api.py
git diff --check
git status --short
```

Expected: no new lint or whitespace errors and only planned files changed.

- [ ] **Step 4: Mark the plan complete, commit, and push main**

```bash
git add docs/superpowers/plans/2026-07-29-candidate-strategy-attribution.md services/engine/backtest/walk_forward.py apps/api/app/routers/rules.py tests/test_walk_forward_replay.py tests/test_strategy_fit_api.py
git commit -m "feat: attribute candidate replay outcomes by strategy"
git push origin main
```

Do not run live candidate selection, DingTalk, replay, recovery, or historical
jobs.
