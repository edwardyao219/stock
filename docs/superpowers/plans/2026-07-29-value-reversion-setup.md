# Value Reversion Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover low-valuation pullbacks during contracted consolidation and upgrade them only after controlled volume confirmation.

**Architecture:** Extend the existing daily feature JSON with six rolling setup measurements, then add `R009 [均值回归] 价值蓄势` to the declarative rules. Candidate discovery treats setup matches as observation and confirmed launches as formal only in safe regimes, while reusing existing rule-name propagation and UI labels.

**Tech Stack:** Python 3.12, SQLAlchemy, pytest, existing declarative rule evaluator.

---

### Task 1: Add consolidation and contraction features

**Files:**
- Modify: `services/engine/features/daily.py`
- Test: `tests/test_daily_features.py`

- [x] Add a failing feature test with a contracted three-day base followed by a controlled breakout.
- [x] Assert `consolidation_range_3d`, `prior_consolidation_range_3d`, `amount_contraction_3d_vs_5d`, `prior_amount_contraction_3d_vs_5d`, `distance_to_60d_high`, and `breakout_from_prior_3d_high`.
- [x] Run `pytest tests/test_daily_features.py -k value_reversion -q` and verify the new keys fail.
- [x] Compute the six values from the existing rolling highs, lows, closes, and rebased amount history.
- [x] Re-run the focused feature test and `tests/test_daily_features.py`.

### Task 2: Add the declarative value-reversion rule

**Files:**
- Modify: `services/engine/rules/seed_rules.py`
- Modify: `services/engine/risk/trade_parameters.py`
- Modify: `services/engine/plans/generator.py`
- Test: `tests/test_trade_plan_generator.py`

- [x] Add a failing test asserting `R009` is a testing swing rule named `[均值回归] 价值蓄势`, includes the value/setup/trigger boundaries, and uses mean-reversion risk limits.
- [x] Add a failing plan test asserting a confirmed R009 launch uses a short-mean confirmation reference, no more than 8% position, and an 8-day holding limit.
- [x] Run both R009 tests and verify they fail because the rule is absent.
- [x] Add the minimal nested declarative conditions from the approved design.
- [x] Reuse the R008 confirmation/target/risk handling for R009.
- [x] Re-run the focused rule and plan tests.

### Task 3: Route setup and launch candidates

**Files:**
- Modify: `services/engine/research_pool/candidates.py`
- Test: `tests/test_next_session_candidates.py`

- [x] Add a shared fixture that builds an R009 setup or launch context with current PE/PB.
- [x] Add a failing test showing a contracted Giant-Network-like setup enters observation with the value-reversion reason.
- [x] Add a failing test showing a Small-Commodity-City-like launch enters formal selection in a range regime.
- [x] Add failing tests showing unsafe regimes retain the launch as observation and high-PB/no-PE contexts do not match R009.
- [x] Run `pytest tests/test_next_session_candidates.py -k value_reversion -q` and verify the failures.
- [x] Add `_is_value_reversion_match()` and `_is_value_reversion_launch()` using the R009 rule fields.
- [x] Route R009 launch matches through the safe-regime formal gate and all other R009 matches through observation.
- [x] Add explicit setup/launch reasons while retaining existing selected-rule tags.
- [x] Re-run the focused candidate tests.

### Task 4: Regression and delivery

- [x] Run `pytest tests/test_daily_features.py tests/test_trade_plan_generator.py tests/test_next_session_candidates.py tests/test_intraday_candidates.py tests/test_notifications.py -q`.
- [x] Run the full suite with `pytest -q`.
- [x] Run `git diff --check` and review the complete diff against the design.
- [x] Commit with `feat: add value reversion setup signals`.
- [x] Push `main` without running selection, DingTalk, replay, or recovery jobs.
