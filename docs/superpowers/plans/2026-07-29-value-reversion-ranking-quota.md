# Value Reversion Ranking Quota Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cap the next-session list at 15 while reserving up to five slots for independently ranked R009 value-reversion candidates and backfilling unused slots with general candidates.

**Architecture:** Add a deterministic R009 setup-quality scorer and a pure quota selector inside the existing candidate module. Feed all qualified R009 formal/observation candidates into that selector before final truncation, preserve existing general ordering, then persist ranks from the combined final list.

**Tech Stack:** Python 3.12, SQLAlchemy, pytest, existing next-session candidate pipeline.

---

### Task 1: Score R009 setup quality independently

**Files:**
- Modify: `services/engine/research_pool/candidates.py`
- Test: `tests/test_next_session_candidates.py`

- [x] **Step 1: Add failing setup-quality tests**

Add direct tests for `_value_reversion_setup_quality`:

```python
def test_value_reversion_setup_quality_prefers_tight_controlled_base() -> None:
    preferred = {
        "pe_ttm": 18.0,
        "pb": 2.0,
        "consolidation_range_3d": 0.055,
        "amount_contraction_3d_vs_5d": 0.50,
        "distance_to_60d_high": -0.20,
        "return_3d": 0.02,
        "distance_to_ma20": -0.04,
    }
    loose = {
        "pe_ttm": 30.0,
        "pb": 2.8,
        "consolidation_range_3d": 0.11,
        "amount_contraction_3d_vs_5d": 0.10,
        "distance_to_60d_high": -0.09,
        "return_3d": 0.05,
        "distance_to_ma20": -0.14,
    }

    assert candidate_module._value_reversion_setup_quality(preferred) == 100.0
    assert candidate_module._value_reversion_setup_quality(loose) == 50.0
```

Add a launch test proving prior setup fields and neutral short stability are
used:

```python
def test_value_reversion_launch_quality_uses_prior_setup_fields() -> None:
    context = {
        "pe_ttm": 18.0,
        "pb": 2.0,
        "prior_consolidation_range_3d": 0.055,
        "prior_amount_contraction_3d_vs_5d": 0.50,
        "distance_to_60d_high": -0.20,
        "return_3d": 0.12,
        "distance_to_ma20": 0.04,
    }

    assert candidate_module._value_reversion_setup_quality(context, launch=True) == 95.0
```

- [x] **Step 2: Verify the scorer tests fail**

Run: `.venv/bin/pytest tests/test_next_session_candidates.py -k value_reversion_setup_quality -q`

Expected: FAIL because `_value_reversion_setup_quality` does not exist.

- [x] **Step 3: Implement the exact 100-point bands**

Add `VALUE_REVERSION_RESERVED_LIMIT = 5` and implement:

```python
def _value_reversion_setup_quality(
    context: dict[str, Any], *, launch: bool = False
) -> float:
    pe = _float(context, "pe_ttm")
    pb = _float(context, "pb")
    valuation = 20.0 if 0 < pe <= 25 and 0 < pb <= 3 else 15.0
    range_key = "prior_consolidation_range_3d" if launch else "consolidation_range_3d"
    contraction_key = (
        "prior_amount_contraction_3d_vs_5d"
        if launch
        else "amount_contraction_3d_vs_5d"
    )
    platform_range = _float(context, range_key, 1.0)
    compactness = 25.0 if platform_range <= 0.06 else 18.0 if platform_range <= 0.09 else 10.0
    contraction_ratio = _float(context, contraction_key, 1.0)
    contraction = (
        25.0
        if 0.35 <= contraction_ratio <= 0.60
        else 18.0
        if 0.20 <= contraction_ratio <= 0.75
        else 10.0
    )
    drawdown = 15.0 if -0.30 <= _float(context, "distance_to_60d_high") <= -0.12 else 8.0
    return_3d = _optional_float(context, "return_3d")
    stability = 5.0 if launch or return_3d is None else 10.0 if abs(return_3d) <= 0.03 else 5.0
    distance_to_ma20 = _optional_float(context, "distance_to_ma20")
    ma_proximity = (
        5.0
        if distance_to_ma20 is not None and -0.10 <= distance_to_ma20 <= 0.08
        else 2.0
    )
    return valuation + compactness + contraction + drawdown + stability + ma_proximity
```

- [x] **Step 4: Verify scorer tests pass**

Run: `.venv/bin/pytest tests/test_next_session_candidates.py -k 'value_reversion_setup_quality or value_reversion_launch_quality' -q`

Expected: PASS.

### Task 2: Select R009 with a hard five-candidate ceiling

**Files:**
- Modify: `services/engine/research_pool/candidates.py`
- Test: `tests/test_next_session_candidates.py`

- [x] **Step 1: Add pure quota and ordering tests**

Add a test candidate helper that builds `NextSessionCandidate` objects with a
specified rule, mode, score, and sector. Test these behaviors through
`_apply_value_reversion_quota`:

```python
selected, selected_r009 = candidate_module._apply_value_reversion_quota(
    general_candidates=general_candidates,
    value_reversion_candidates=value_candidates,
    context_by_symbol=context_by_symbol,
    limit=15,
)
assert len(selected) == 15
assert len(selected_r009) == 5
assert sum(item.selected_rule_id == "R009" for item in selected) == 5
assert sum(item.selected_rule_id != "R009" for item in selected) == 10
```

Add separate cases asserting:

```python
# Two R009 candidates allow 13 general candidates to backfill.
assert (general_count, r009_count, total_count) == (13, 2, 15)

# Eight R009 candidates and six general candidates return only 11.
assert (general_count, r009_count, total_count) == (6, 5, 11)

# A launch sorts ahead of a setup with a higher generic score.
assert selected_r009[0].symbol == launch.symbol
```

- [x] **Step 2: Verify quota tests fail**

Run: `.venv/bin/pytest tests/test_next_session_candidates.py -k value_reversion_quota -q`

Expected: FAIL because `_apply_value_reversion_quota` does not exist.

- [x] **Step 3: Implement R009 ranking and quota selection**

Add `_rank_value_reversion_candidates` that greedily chooses by this tuple:

```python
(
    _is_value_reversion_launch(context),
    _value_reversion_setup_quality(context, launch=launch),
    sector_not_selected,
    _action_rank_score(candidate),
)
```

The sector-diversity term comes after launch state and quality, so it only
breaks otherwise equivalent R009 candidates. Then add:

```python
def _apply_value_reversion_quota(
    *,
    general_candidates: list[NextSessionCandidate],
    value_reversion_candidates: list[NextSessionCandidate],
    context_by_symbol: dict[str, dict[str, Any]],
    limit: int,
) -> tuple[list[NextSessionCandidate], list[NextSessionCandidate]]:
    selected_r009 = _rank_value_reversion_candidates(
        value_reversion_candidates,
        context_by_symbol=context_by_symbol,
        limit=min(VALUE_REVERSION_RESERVED_LIMIT, max(0, limit)),
    )
    general_limit = max(0, limit - len(selected_r009))
    selected_general = general_candidates[:general_limit]
    return [*selected_general, *selected_r009], selected_r009
```

Do not fill unused general capacity with a sixth R009 candidate.

- [x] **Step 4: Verify pure selector tests pass**

Run: `.venv/bin/pytest tests/test_next_session_candidates.py -k value_reversion_quota -q`

Expected: PASS.

### Task 3: Integrate the quota before final persistence

**Files:**
- Modify: `services/engine/research_pool/candidates.py`
- Test: `tests/test_next_session_candidates.py`

- [x] **Step 1: Add an end-to-end 10+5 discovery test**

Extend the existing 15-candidate cap fixture with seven R009 setup securities.
Each setup receives positive PE/PB and the existing R009 setup fields. Assert:

```python
assert len(result["candidates"]) == 15
assert sum(item["selected_rule_id"] == "R009" for item in result["candidates"]) == 5
assert sum(item["selected_rule_id"] != "R009" for item in result["candidates"]) == 10
assert result["selection_funnel"]["value_reversion_qualified"] == 7
assert result["selection_funnel"]["value_reversion_selected"] == 5
assert result["selection_funnel"]["value_reversion_ranked_out"] == 2
assert result["selection_funnel"]["general_selected"] == 10
assert result["written"] == 15
assert "rank:15" in {
    tag for item in items for tag in item["tags"] if tag.startswith("rank:")
}
```

- [x] **Step 2: Verify discovery still excludes R009 when general slots fill**

Run: `.venv/bin/pytest tests/test_next_session_candidates.py -k caps_daily_list_to_fifteen -q`

Expected: FAIL because current observation selection gives R009 no remaining
slots.

- [x] **Step 3: Apply quota to complete qualified R009 sets**

After existing general mode selection and ordering:

```python
value_reversion_candidates = [
    item
    for item in [*formal_candidates, *observation_candidates]
    if item.selected_rule_id == "R009"
]
general_candidates = [item for item in selected if item.selected_rule_id != "R009"]
selected, selected_value_reversion = _apply_value_reversion_quota(
    general_candidates=general_candidates,
    value_reversion_candidates=value_reversion_candidates,
    context_by_symbol=context_by_symbol,
    limit=requested_limit,
)
selected = sorted(
    selected,
    key=lambda item: (
        {
            "formal_strategy": 3,
            "observation": 2,
            "potential_watch": 1,
            "exploration": 0,
        }.get(item.selection_mode, 0),
        _sector_first_final_rank_score(item, final_score_fn),
    ),
    reverse=True,
)
selected = _surface_fresh_potential_after_crowded_sector(selected)
```

Deduplicate R009 by symbol before selection. Recalculate the final funnel keys:

```python
selection_funnel.update(
    {
        "value_reversion_qualified": len(value_reversion_candidates),
        "value_reversion_selected": len(selected_value_reversion),
        "value_reversion_ranked_out": (
            len(value_reversion_candidates) - len(selected_value_reversion)
        ),
        "general_selected": len(selected) - len(selected_value_reversion),
        "selected": len(selected),
    }
)
```

Use the clamped `requested_limit`, so caller limits below 15 remain honored and
the default remains 15.

- [x] **Step 4: Verify quota integration and existing value tests pass**

Run: `.venv/bin/pytest tests/test_next_session_candidates.py -k 'caps_daily_list_to_fifteen or value_reversion' -q`

Expected: PASS.

### Task 4: Regression and delivery

**Files:**
- Modify: `docs/superpowers/plans/2026-07-29-value-reversion-ranking-quota.md`

- [x] **Step 1: Run candidate and notification regressions**

Run: `.venv/bin/pytest tests/test_next_session_candidates.py tests/test_notifications.py tests/test_jobs_pipeline.py -q`

Expected: PASS.

- [x] **Step 2: Run the complete suite**

Run: `.venv/bin/pytest -q`

Expected: all tests pass; the known SQLAlchemy warning may remain.

- [x] **Step 3: Run static and diff checks**

Run:

```bash
.venv/bin/ruff check services/engine/research_pool/candidates.py tests/test_next_session_candidates.py
git diff --check
git status --short
```

Expected: no new lint or whitespace errors and only planned files modified.

- [x] **Step 4: Mark the plan complete, commit, and push main**

Change completed checkboxes to `[x]`, then run:

```bash
git add \
  docs/superpowers/plans/2026-07-29-value-reversion-ranking-quota.md \
  services/engine/research_pool/candidates.py \
  tests/test_next_session_candidates.py
git commit -m "feat: reserve value reversion candidate slots"
git push origin main
```

Do not run live selection, DingTalk, replay, recovery, or historical jobs.
