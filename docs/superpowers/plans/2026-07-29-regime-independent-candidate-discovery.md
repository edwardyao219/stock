# Regime-Independent Candidate Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover up to 15 technically qualified candidates in every market regime while preserving market-driven ranking, `market_guard`, candidate tiers, and plan blocking.

**Architecture:** Remove market permission from candidate eligibility and use the clamped request limit as the only discovery capacity. Keep regime score adjustments and downstream tiering unchanged, then expose how many selected candidates are market-blocked through the existing funnel response and renderers.

**Tech Stack:** Python 3.12, SQLAlchemy, pytest, existing candidate discovery and notification pipeline.

---

### Task 1: Make technical strategy state independent of market regime

**Files:**
- Modify: `services/engine/research_pool/candidates.py`
- Modify: `tests/test_next_session_candidates.py`
- Modify: `tests/test_market_regime.py`

- [x] **Step 1: Add a failing cross-regime general-strategy test**

Add a helper that forces the market snapshot while using an R002 context whose
trend score passes R002 and the formal quality threshold but not the current
weak/panic market gates:

```python
def _run_forced_regime_strategy_discovery(monkeypatch, regime: str):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        candidate_module,
        "_candidate_data_evidence_risk",
        lambda db, feature_date: {"status": "ok", "reasons": []},
    )
    monkeypatch.setattr(
        candidate_module,
        "_market_regime_snapshot",
        lambda contexts, feature_date: MarketRegimeSnapshot(
            trade_date=feature_date.isoformat(),
            regime=regime,
            trend_score=50.0,
            breadth_score=50.0,
            emotion_score=50.0,
            volatility_score=50.0,
            risk_level="high" if regime in {"panic", "weak_trend"} else "medium",
        ),
    )
    with Session(engine) as db:
        db.add_all(
            [
                Security(
                    symbol="000001",
                    name="跨市场技术信号",
                    exchange="SZ",
                    industry="PCB",
                    is_active=True,
                ),
                _bar("000001"),
                _feature(
                    "000001",
                    trend_score=70,
                    relative_strength_score=65,
                    sector_strength_score=70,
                    volume_confirmation_score=60,
                    risk_score=28,
                ),
            ]
        )
        db.commit()
        return discover_next_session_candidates(
            db,
            feature_date="2026-06-24",
            next_trade_date="2026-06-25",
            pool_name="experiment",
            limit=15,
        )


@pytest.mark.parametrize(
    ("regime", "expected_plan_status"),
    [
        ("strong_trend", "planned"),
        ("range", "planned"),
        ("weak_trend", "market_guard"),
        ("panic", "market_guard"),
        ("rebound_unconfirmed", "market_guard"),
        ("unknown", "planned"),
    ],
)
def test_strategy_signal_remains_formal_in_every_market_regime(
    monkeypatch, regime, expected_plan_status
) -> None:
    result = _run_forced_regime_strategy_discovery(monkeypatch, regime)
    candidate = next(item for item in result["candidates"] if item["symbol"] == "000001")

    assert candidate["selected_rule_id"] == "R002"
    assert candidate["selection_mode"] == "formal_strategy"
    assert candidate["plan_availability"]["status"] == expected_plan_status
```

- [x] **Step 2: Change the existing R008 and R009 weak-regime expectations**

Replace the observation assertions with technical-state assertions. Panic,
weak trend, and unconfirmed rebound must be formal but market-blocked; unknown
must be formal and planned:

```python
@pytest.mark.parametrize(
    ("regime", "expected_plan_status"),
    [
        ("panic", "market_guard"),
        ("weak_trend", "market_guard"),
        ("rebound_unconfirmed", "market_guard"),
        ("unknown", "planned"),
    ],
)
def test_mean_reversion_candidate_keeps_technical_state_across_regimes(
    monkeypatch, regime, expected_plan_status
) -> None:
    result, _items = _run_mean_reversion_discovery(monkeypatch, regime)
    candidate = next(item for item in result["candidates"] if item["selected_rule_id"] == "R008")
    assert candidate["selection_mode"] == "formal_strategy"
    assert candidate["plan_availability"]["status"] == expected_plan_status


@pytest.mark.parametrize(
    ("regime", "expected_plan_status"),
    [
        ("panic", "market_guard"),
        ("weak_trend", "market_guard"),
        ("rebound_unconfirmed", "market_guard"),
        ("unknown", "planned"),
    ],
)
def test_value_reversion_launch_keeps_technical_state_across_regimes(
    monkeypatch, regime, expected_plan_status
) -> None:
    result, _items = _run_value_reversion_discovery(monkeypatch, regime, launch=True)
    candidate = next(item for item in result["candidates"] if item["selected_rule_id"] == "R009")
    assert candidate["selection_mode"] == "formal_strategy"
    assert candidate["plan_availability"]["status"] == expected_plan_status
```

Keep `test_value_reversion_contracted_setup_enters_observation` unchanged.

- [x] **Step 3: Verify the new technical-state tests fail**

Run:

```bash
.venv/bin/pytest tests/test_next_session_candidates.py -k 'remains_formal_in_every_market_regime or keeps_technical_state_across_regimes' -q
```

Expected: FAIL because weak and panic regimes currently downgrade or replace
the formal strategy candidates.

- [x] **Step 4: Remove regime permission from candidate eligibility**

In `services/engine/research_pool/candidates.py`:

- Delete `_passes_market_regime_gate`.
- Remove its direct unit test and import from `tests/test_market_regime.py`.
- Remove the `regime` argument from `_passes_formal_candidate_selection` and
  `_passes_mean_reversion_candidate_filters`.
- Make R008 depend on hard safety only, R009 formal state depend on hard safety
  plus `_is_value_reversion_launch`, and general formal state depend on
  `_passes_candidate_filters`.
- Remove `_passes_market_regime_gate` calls from the long-horizon formal,
  observation, and potential-watch branches.

The formal selector becomes:

```python
def _passes_formal_candidate_selection(
    context: dict[str, Any],
    matches: list[CandidateStrategyMatch],
    *,
    score_delta: float,
) -> bool:
    if _is_mean_reversion_match(matches):
        return _passes_hard_safety_filters(context)
    if _is_value_reversion_match(matches):
        return _passes_hard_safety_filters(context) and _is_value_reversion_launch(context)
    return _passes_candidate_filters(context, score_delta=score_delta)
```

Update `_regime_note` so weak, panic, unconfirmed-rebound, and unknown copy says
screening continues while execution remains conservative.

- [x] **Step 5: Verify technical-state tests pass**

Run:

```bash
.venv/bin/pytest tests/test_next_session_candidates.py tests/test_market_regime.py -k 'regime or mean_reversion or value_reversion' -q
```

Expected: PASS; R009 setups remain observation-only and hard safety remains unchanged.

### Task 2: Use the full discovery limit and count market-blocked selections

**Files:**
- Modify: `services/engine/research_pool/candidates.py`
- Modify: `tests/test_next_session_candidates.py`

- [x] **Step 1: Add a failing panic-market capacity test**

Create 18 technically qualified R002 stocks, force a panic snapshot, and assert:

```python
assert len(result["candidates"]) == 15
assert result["effective_limit"] == 15
assert result["selection_funnel"]["market_guard_selected"] == 15
assert all(
    item["selection_mode"] == "formal_strategy"
    and item["plan_availability"]["status"] == "market_guard"
    for item in result["candidates"]
)
```

Use `limit=99` to prove the public maximum remains 15. Give each stock an R002
context with `trend_score=86`, `relative_strength_score=75`,
`sector_strength_score=75`, `volume_confirmation_score=66`, `risk_score=24`,
and the existing safe defaults.

- [x] **Step 2: Verify the capacity test fails**

Run:

```bash
.venv/bin/pytest tests/test_next_session_candidates.py -k panic_market_uses_full_discovery_limit -q
```

Expected: FAIL because the current panic cap is three and the funnel has no
`market_guard_selected` field.

- [x] **Step 3: Remove the regime-derived discovery capacity**

Delete `_regime_candidate_limit` and its direct test/import. In
`discover_next_session_candidates`, replace the regime-derived call with:

```python
requested_limit = max(1, min(limit, CANDIDATE_DEFAULT_LIMIT))
effective_limit = requested_limit
```

Keep mode ranking, the final overall cap, and the R009 10+5 quota unchanged.

After assigning final `plan_availability`, add:

```python
selection_funnel["market_guard_selected"] = sum(
    item.plan_availability.get("status") == "market_guard" for item in selected
)
```

- [x] **Step 4: Verify capacity, hard-safety, and quota behavior**

Run:

```bash
.venv/bin/pytest tests/test_next_session_candidates.py -k 'panic_market_uses_full_discovery_limit or hard_safety or caps_daily_list_to_fifteen or value_reversion_quota' -q
```

Expected: PASS with a final maximum of 15 and no sixth R009 candidate.

### Task 3: Render discovered-versus-market-guarded counts

**Files:**
- Modify: `services/jobs/pipeline.py`
- Modify: `services/notifications/dispatcher.py`
- Modify: `tests/test_jobs_pipeline.py`
- Modify: `tests/test_notifications.py`

- [x] **Step 1: Add failing funnel rendering assertions**

Add `"market_guard_selected": 3` to the existing funnel fixtures in
`test_discover_next_session_candidates_step_dispatches_screening_summary` and
the candidate notification summary test. Assert both rendered strings include:

```python
assert "市场风控观察 3" in text
```

Keep the existing `test_discover_next_session_candidates_step_does_not_plan_blocked_core`
assertions that `core_action == []` and generated plan symbols are empty.

- [x] **Step 2: Verify renderer tests fail**

Run:

```bash
.venv/bin/pytest tests/test_jobs_pipeline.py tests/test_notifications.py -k 'screening_summary or format_candidate_screening_text_contains_reasons or does_not_plan_blocked_core' -q
```

Expected: FAIL only on the missing market-guard count; the existing plan-block
test remains green.

- [x] **Step 3: Append the guard count to both funnel renderers**

In `_candidate_funnel_detail` and `_append_candidate_selection_funnel`, render:

```python
f"最终入池 {int(funnel.get('selected') or 0)}，"
f"市场风控观察 {int(funnel.get('market_guard_selected') or 0)}。"
```

The `.get(..., 0)` compatibility keeps older stored payloads readable.

- [x] **Step 4: Verify funnel rendering and plan blocking**

Run:

```bash
.venv/bin/pytest tests/test_jobs_pipeline.py tests/test_notifications.py -k 'candidate or screening or blocked_core' -q
```

Expected: PASS; risk-off formal candidates remain visible but generate zero
plans when no core action is permitted.

### Task 4: Regression and delivery

**Files:**
- Modify: `docs/superpowers/plans/2026-07-29-regime-independent-candidate-discovery.md`

- [x] **Step 1: Run focused cross-module regressions**

Run:

```bash
.venv/bin/pytest tests/test_next_session_candidates.py tests/test_market_regime.py tests/test_notifications.py tests/test_jobs_pipeline.py tests/test_trade_plan_generator.py -q
```

Expected: PASS.

- [x] **Step 2: Run the complete suite**

Run:

```bash
.venv/bin/pytest -q
```

Expected: all tests pass; the existing SQLAlchemy `cache_ok` warning may remain.

- [x] **Step 3: Run static and diff checks**

Run:

```bash
.venv/bin/ruff check --ignore E501 services/engine/research_pool/candidates.py services/jobs/pipeline.py services/notifications/dispatcher.py tests/test_next_session_candidates.py tests/test_market_regime.py tests/test_jobs_pipeline.py tests/test_notifications.py
git diff --check
git status --short
```

Expected: no new lint or whitespace errors. Full Ruff without `--ignore E501`
may still report the pre-existing long line in `candidates.py`.

- [x] **Step 4: Mark this plan complete, commit, and push main**

Change completed checkboxes to `[x]`, then run:

```bash
git add docs/superpowers/plans/2026-07-29-regime-independent-candidate-discovery.md services/engine/research_pool/candidates.py services/jobs/pipeline.py services/notifications/dispatcher.py tests/test_next_session_candidates.py tests/test_market_regime.py tests/test_jobs_pipeline.py tests/test_notifications.py
git commit -m "feat: decouple candidate discovery from market regime"
git push origin main
```

Do not run live selection, DingTalk, replay, recovery, or historical jobs.
