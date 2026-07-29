# Value Reversion Intraday Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Track an after-close R009 setup intraday and upgrade a controlled platform breakout to a visible confirmation without letting market regime suppress discovery.

**Architecture:** Store three structured platform baselines in the existing daily feature JSON and mark only R009 setup candidates with a semantic pool tag. Intraday discovery bulk-loads those baselines, calculates time-adjusted amount pace, and feeds a value-reversion confirmation path into the existing startup state resolver, ledger, and notification flow.

**Tech Stack:** Python 3.12, SQLAlchemy, pytest, existing research-pool and intraday startup modules.

---

### Task 1: Persist completed-day R009 baselines

**Files:**
- Modify: `services/engine/features/daily.py`
- Test: `tests/test_daily_features.py`

- [x] **Step 1: Extend the value-reversion feature test**

Add these assertions to `test_compute_stock_daily_features_adds_value_reversion_setup_metrics`:

```python
assert latest["recent_high_3d"] == 10.9
assert latest["recent_low_3d"] == 9.9
assert latest["recent_amount_ma5"] == 770.0
```

- [x] **Step 2: Verify the test fails for missing keys**

Run: `.venv/bin/pytest tests/test_daily_features.py -k value_reversion_setup_metrics -q`

Expected: FAIL with `KeyError: 'recent_high_3d'`.

- [x] **Step 3: Add the three values to the feature JSON**

Reuse `high_3d` and `low_3d`, and calculate the exact next-day amount baseline
in `compute_stock_daily_features`:

```python
recent_amount_ma5 = _average(amounts[-5:])
"recent_high_3d": high_3d,
"recent_low_3d": low_3d,
"recent_amount_ma5": recent_amount_ma5,
```

- [x] **Step 4: Verify the focused feature tests pass**

Run: `.venv/bin/pytest tests/test_daily_features.py -k 'value_reversion or basic_values' -q`

Expected: PASS.

### Task 2: Mark only contracted R009 setups for next-day tracking

**Files:**
- Modify: `services/engine/research_pool/candidates.py`
- Test: `tests/test_next_session_candidates.py`

- [x] **Step 1: Add setup and launch tag assertions**

In the existing R009 setup test assert:

```python
assert "candidate_pool:value_reversion_setup" in items[0]["tags"]
```

In the launch test retain the returned pool items and assert:

```python
assert "candidate_pool:value_reversion_setup" not in items[0]["tags"]
```

- [x] **Step 2: Verify the setup assertion fails**

Run: `.venv/bin/pytest tests/test_next_session_candidates.py -k 'value_reversion_contracted_setup or value_reversion_volume_launch' -q`

Expected: the setup test fails because the semantic tag is absent.

- [x] **Step 3: Persist the semantic setup tag**

While building candidate tags, reuse `_is_value_reversion_launch` and the
existing `context_by_symbol` entry:

```python
if (
    item.selected_rule_id == "R009"
    and not _is_value_reversion_launch(context_by_symbol[item.symbol])
):
    tags.append("candidate_pool:value_reversion_setup")
```

No numeric baseline is written into tags.

- [x] **Step 4: Verify focused candidate persistence tests pass**

Run: `.venv/bin/pytest tests/test_next_session_candidates.py -k value_reversion -q`

Expected: PASS.

### Task 3: Add a value-reversion path to the startup resolver

**Files:**
- Modify: `services/engine/intraday/startup_state.py`
- Test: `tests/test_startup_state.py`

- [x] **Step 1: Add failing resolver tests**

Add tests proving that the new path confirms without sector expansion, ignores
market risk-off as a technical invalidation, retains hard-risk invalidation,
and preserves the old sector path:

```python
def test_value_reversion_confirmation_does_not_require_sector_or_market_gate() -> None:
    result = resolve_startup_state(
        "probing",
        _evidence(
            confirmation_path="value_reversion",
            confirmation_ready=True,
            sector_sustained=False,
            formal_eligible=False,
            market_risk_off=True,
        ),
    )

    assert result.state == "confirmed"
    assert result.confirmation_evidence == (
        "突破近3日平台",
        "成交额温和放大",
        "日内价格位置偏强",
    )


def test_value_reversion_hard_risk_still_invalidates() -> None:
    result = resolve_startup_state(
        "confirmed",
        _evidence(
            confirmation_path="value_reversion",
            confirmation_ready=True,
            hard_risk_reasons=("跌破近3日平台低点",),
        ),
    )

    assert result.state == "invalidated"
```

- [x] **Step 2: Verify the tests fail on the new evidence fields**

Run: `.venv/bin/pytest tests/test_startup_state.py -q`

Expected: FAIL because `StartupEvidence` does not accept
`confirmation_path` or `confirmation_ready`.

- [x] **Step 3: Extend the resolver without changing its default path**

Add defaulted fields:

```python
confirmation_path: str = "sector_startup"
confirmation_ready: bool = False
pending_conditions: tuple[str, ...] = ()
```

For `value_reversion`, only hard risks invalidate; confirmation requires
`as_of >= 10:30` and `confirmation_ready`. Use the three R009 evidence labels
above and return `pending_conditions` while preheat or probing. Keep every
existing `sector_startup` condition and message unchanged.

- [x] **Step 4: Verify resolver regressions pass**

Run: `.venv/bin/pytest tests/test_startup_state.py -q`

Expected: PASS.

### Task 4: Calculate and expose the R009 intraday lifecycle

**Files:**
- Modify: `services/engine/intraday/candidates.py`
- Test: `tests/test_intraday_candidates.py`

- [x] **Step 1: Add an R009 candidate fixture with structured baselines**

Create a local helper in `tests/test_intraday_candidates.py` that persists:

```python
_candidate(
    "600415",
    rank=5,
    score=66,
    rule_id="R009",
    rule_name="[均值回归] 价值蓄势",
)
```

Append `candidate_pool:value_reversion_setup` to its tags and add a
`StockFeatureDaily` row for the preceding session with:

```python
features={
    "recent_high_3d": 10.40,
    "recent_low_3d": 9.80,
    "recent_amount_ma5": 1_000_000.0,
}
```

Extend the existing `_quote` test helper with an `amount` keyword and pass it
through to `RealtimeQuote.amount`; keep its current default unchanged.

- [x] **Step 2: Add failing lifecycle tests**

Cover these quotes and expected states:

```python
# 09:55, near the platform: probing, never confirmed early
price="10.30", high="10.35", low="10.00", amount="250000"

# 10:30, controlled breakout: confirmed
price="10.55", high="10.60", low="10.00", amount="350000"

# 10:30, missing StockFeatureDaily row: preheat with data condition

# 10:30, price below 9.80: invalidated
price="9.70", high="10.10", low="9.65", amount="300000"
```

For the controlled breakout assert:

```python
assert candidate["startup_tracked"] is True
assert candidate["startup_stage"] == "confirmed"
assert candidate["selected_rule_id"] == "R009"
assert "value_reversion_platform_breakout" in candidate["support_flags"]
assert "value_reversion_controlled_amount" in candidate["support_flags"]
assert candidate["startup_confirmation_evidence"] == [
    "突破近3日平台",
    "成交额温和放大",
    "日内价格位置偏强",
]
```

Also pass a market risk-off payload and assert the technical state remains
`confirmed` while `selection_tier != "formal"`.

- [x] **Step 3: Verify the new intraday tests fail**

Run: `.venv/bin/pytest tests/test_intraday_candidates.py -k value_reversion -q`

Expected: FAIL because R009 setup tracking and baseline evaluation are absent.

- [x] **Step 4: Bulk-load candidate baselines**

Import `StockFeatureDaily` and add `_latest_stock_feature_map`, following the
existing sector-feature latest-date query pattern. It must return only rows
with `trade_date < current trade_date` for requested symbols.

- [x] **Step 5: Add minimal amount-pace and signal helpers**

Add `_session_elapsed_fraction(as_of)` for the two A-share sessions and a
small immutable result for `_value_reversion_signal`. The signal must:

```python
projected_amount_ratio = quote.amount / elapsed_fraction / recent_amount_ma5
platform_approached = quote.price >= recent_high_3d * Decimal("0.98")
platform_broken = quote.price >= recent_high_3d
range_strong = _range_position(quote.price, quote.high, quote.low) >= 0.65
controlled_amount = Decimal("1.15") <= projected_amount_ratio <= Decimal("2.20")
confirmation_ready = platform_broken and range_strong and controlled_amount and 0.015 <= day_change <= 0.085
```

Missing baselines return preheat evidence with `等待日线平台与成交额基准`.
Price below `recent_low_3d` returns hard risk `跌破近3日平台低点`.

- [x] **Step 6: Integrate only tagged R009 setup candidates**

Set `startup_tracked` when either the existing startup-preheat tag or the new
R009 setup tag is present. For R009 setups, pass `confirmation_path`,
`confirmation_ready`, and pending conditions into `resolve_startup_state`.
Keep the generic volume signal and all non-R009 startup behavior unchanged.

After resolution, a confirmed R009 signal may be formal only when no
`market_risk_off` or hard-risk flag exists. Do not let missing sector expansion
downgrade its technical state.

- [x] **Step 7: Verify intraday and notification-adjacent tests pass**

Run: `.venv/bin/pytest tests/test_intraday_candidates.py tests/test_startup_state.py tests/test_notifications.py tests/test_research_signal_ledger.py -q`

Expected: PASS.

### Task 5: Regression and delivery

**Files:**
- Modify: `docs/superpowers/plans/2026-07-29-value-reversion-intraday-lifecycle.md`

- [x] **Step 1: Run focused R009 regressions**

Run: `.venv/bin/pytest tests/test_daily_features.py tests/test_next_session_candidates.py tests/test_intraday_candidates.py tests/test_startup_state.py -q`

Expected: PASS.

- [x] **Step 2: Run the complete suite**

Run: `.venv/bin/pytest -q`

Expected: all tests pass; the known SQLAlchemy warning may remain.

- [x] **Step 3: Check and review the diff**

Run: `git diff --check && git status --short`

Expected: no whitespace errors and only the planned files are modified.

- [x] **Step 4: Mark this plan complete and commit**

Change completed checkboxes to `[x]`, then run:

```bash
git add \
  docs/superpowers/plans/2026-07-29-value-reversion-intraday-lifecycle.md \
  services/engine/features/daily.py \
  services/engine/research_pool/candidates.py \
  services/engine/intraday/startup_state.py \
  services/engine/intraday/candidates.py \
  tests/test_daily_features.py \
  tests/test_next_session_candidates.py \
  tests/test_startup_state.py \
  tests/test_intraday_candidates.py
git commit -m "feat: track value reversion launches intraday"
git push origin main
```

Do not run live selection, DingTalk, replay, recovery, or historical jobs.
