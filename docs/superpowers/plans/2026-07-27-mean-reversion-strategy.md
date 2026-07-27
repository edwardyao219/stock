# Mean Reversion Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `R008 [均值回归] 超跌修复` to formal candidate selection with confirmation-based trade parameters and a prominent strategy label in next-session, intraday, and DingTalk candidate views.

**Architecture:** Reuse the existing declarative rule evaluator and candidate lifecycle. Dispatch only `R008` through a narrow mean-reversion candidate gate, persist its human-readable rule name with the candidate, and carry the existing rule identity through intraday APIs to shared web-label helpers.

**Tech Stack:** Python 3.11, Pydantic, SQLAlchemy, pytest, React 19, TypeScript, Vite.

---

### Task 1: Define the R008 rule

**Files:**
- Modify: `tests/test_trade_plan_generator.py`
- Modify: `services/engine/rules/seed_rules.py`

- [x] **Step 1: Write the failing rule-definition test**

```python
def test_mean_reversion_rule_has_conservative_oversold_bounds() -> None:
    rule = next(item for item in MVP_RULES if item.id == "R008")
    conditions = {(item.feature, item.op, item.value) for item in rule.entry.all}

    assert rule.name == "[均值回归] 超跌修复"
    assert rule.status.value == "testing"
    assert ("rsi_14", ">=", 20) in conditions
    assert ("rsi_14", "<=", 38) in conditions
    assert ("distance_to_ma20", ">=", -0.12) in conditions
    assert ("distance_to_ma20", "<=", -0.04) in conditions
    assert rule.time_exit.max_holding_days == 8
    assert "mean-reversion" in rule.tags
```

- [x] **Step 2: Run the test and verify RED**

Run: `pytest tests/test_trade_plan_generator.py::test_mean_reversion_rule_has_conservative_oversold_bounds -q`

Expected: FAIL because no rule has id `R008`.

- [x] **Step 3: Add the minimal declarative rule**

Add this rule to `MVP_RULES`:

```python
StrategyRule(
    id="R008",
    name="[均值回归] 超跌修复",
    strategy_type=StrategyType.SWING,
    status=RuleStatus.TESTING,
    description="寻找偏离MA20且短线超卖、但跌势已开始收敛的个股，次日站回短均线后参与修复。",
    entry=ConditionGroup(all=[
        Condition(feature="fundamental_verdict", op="!=", value="weak"),
        Condition(feature="rsi_14", op=">=", value=20),
        Condition(feature="rsi_14", op="<=", value=38),
        Condition(feature="distance_to_ma20", op=">=", value=-0.12),
        Condition(feature="distance_to_ma20", op="<=", value=-0.04),
        Condition(feature="return_5d", op=">=", value=-0.15),
        Condition(feature="return_5d", op="<=", value=-0.04),
        Condition(feature="return_20d", op=">=", value=-0.22),
        Condition(feature="ma20_slope_20d", op=">=", value=-0.03),
        Condition(feature="max_drawdown_20d", op=">=", value=-0.22),
        Condition(feature="close_position_in_range", op=">=", value=0.45),
        Condition(feature="volume_trap_risk_score", op="<=", value=65),
        Condition(feature="is_st", op="==", value=False),
        Condition(feature="is_suspended", op="==", value=False),
    ]),
    trigger=ConditionGroup(all=[Condition(field="price", op=">=", ref="entry_trigger_price")]),
    stop=StopRule(type="composite", params={"atr_multiple": 1.5, "structure_ref": "support_level", "mode": "tighter"}),
    take_profit=TakeProfitRule(type="target_then_trailing", params={"first_target_ref": "ma10", "second_target_ref": "ma20", "drawdown_from_high_pct": 0.05}),
    time_exit=TimeExitRule(max_holding_days=8, exit_if_no_new_high_days=4),
    position=PositionRule(base_position_pct=0.04, max_position_pct=0.08),
    tags=["mean-reversion", "oversold-repair", "swing"],
),
```

- [x] **Step 4: Run the focused test and verify GREEN**

Run: `pytest tests/test_trade_plan_generator.py::test_mean_reversion_rule_has_conservative_oversold_bounds -q`

Expected: PASS.

### Task 2: Build R008 confirmation, targets, and risk bounds

**Files:**
- Modify: `tests/test_trade_plan_generator.py`
- Modify: `services/engine/plans/generator.py`
- Modify: `services/engine/risk/trade_parameters.py`

- [x] **Step 1: Write a failing trade-plan test**

Create a valid mean-reversion context with `close=9.0`, `ma5=9.2`, `ma10=9.6`, `ma20=10.0`, `support_level=8.6`, `atr_14=0.2`, and all R008 rule fields. Generate one plan and assert:

```python
assert plan.rule_id == "R008"
assert plan.entry_trigger_price == 9.2
assert plan.max_gap_up_pct == 0.03
assert plan.take_profit_1 == 9.6
assert plan.take_profit_2 == 10.0
assert plan.position_size <= 0.08
assert plan.max_holding_days == 8
assert plan.entry_condition["trade_parameters"]["entry_reference_price"] == 9.2
```

- [x] **Step 2: Run the test and verify RED**

Run: `pytest tests/test_trade_plan_generator.py::test_mean_reversion_plan_uses_recovery_confirmation_and_mean_targets -q`

Expected: FAIL because `R008` still uses generic close, gap, targets, and position handling.

- [x] **Step 3: Implement the smallest R008 parameter branch**

In `build_trade_parameters`, add the entry branch and post-stop overrides:

```python
elif rule.id == "R008":
    ma5 = _float(context, "ma5", close) or close
    entry_reference_price = max(close, ma5)
    entry_reason = "mean_reversion_confirmation_reference"
```

```python
max_gap_up_pct = profile.max_gap_up_pct
if rule.id == "R008":
    ma10 = _float(context, "ma10")
    ma20 = _float(context, "ma20")
    take_profit_1 = ma10 if ma10 is not None and ma10 > entry_trigger_price else entry_trigger_price + risk_per_share
    take_profit_2 = ma20 if ma20 is not None and ma20 > take_profit_1 else take_profit_1 + risk_per_share * 0.5
    position_size_pct = min(position_size_pct, rule.position.max_position_pct)
    max_gap_up_pct = 0.03
```

Return `max_gap_up_pct=max_gap_up_pct`; all other rules retain the profile value.

- [x] **Step 4: Run focused generator tests**

Run: `pytest tests/test_trade_plan_generator.py -q`

Expected: all tests PASS.

- [x] **Step 5: Keep R008 risk bounds after learning adjustments**

Add a regression test with aggressive learning multipliers and verify R008 retains
its structure/ATR stop, MA10/MA20 targets, 8% position cap, and 8-day holding cap.

### Task 3: Admit R008 to formal candidate selection and persist its name

**Files:**
- Modify: `tests/test_next_session_candidates.py`
- Modify: `services/engine/research_pool/candidates.py`

- [x] **Step 1: Write failing range-market candidate tests**

Add an R008 feature fixture with low trend but all rule conditions satisfied. Monkeypatch `_market_regime_snapshot` to `range`, then assert the result contains a formal `R008` candidate and persisted tags include:

```python
assert candidate["selected_rule_id"] == "R008"
assert candidate["selected_rule_name"] == "[均值回归] 超跌修复"
assert candidate["selection_mode"] == "formal_strategy"
assert "rule:R008" in tags
assert "rule_name:[均值回归] 超跌修复" in tags
```

Add a parametrized test for `panic`, `weak_trend`, `rebound_unconfirmed`, and `unknown` asserting no formal `R008` candidate is returned.

- [x] **Step 2: Run both tests and verify RED**

Run: `pytest tests/test_next_session_candidates.py -k mean_reversion -q`

Expected: FAIL because the generic trend gate rejects the candidate and no rule-name tag is persisted.

- [x] **Step 3: Add a strategy-aware gate**

Add `"R008": 3.0` to `CANDIDATE_RULE_SCORE_BONUSES` and these helpers:

```python
def _is_mean_reversion_match(matches: list[CandidateStrategyMatch]) -> bool:
    return bool(matches and matches[0].rule_id == "R008")


def _passes_mean_reversion_candidate_filters(
    context: dict[str, Any], *, regime: str
) -> bool:
    return regime in {"strong_trend", "rebound", "range"} and _passes_hard_safety_filters(
        context
    )
```

The selected `R008` match already proves the declarative rule conditions; do not duplicate those thresholds in the candidate gate.

Compute `mean_reversion_match = _is_mean_reversion_match(matches)` and make the formal branch gate expression:

```python
(
    _passes_mean_reversion_candidate_filters(context, regime=market_regime.regime)
    if mean_reversion_match
    else _passes_market_regime_gate(
        context, regime=market_regime.regime, selection_mode="formal_strategy"
    ) and _passes_candidate_filters(context, score_delta=score_delta)
)
```

- [x] **Step 4: Persist and clean `rule_name:`**

Add `"rule_name:"` to `CANDIDATE_TAG_PREFIXES` and persist:

```python
if item.selected_rule_id:
    tags.append(f"rule:{item.selected_rule_id}")
if item.selected_rule_name:
    tags.append(f"rule_name:{item.selected_rule_name}")
```

- [x] **Step 5: Run candidate tests and verify GREEN**

Run: `pytest tests/test_next_session_candidates.py -k 'mean_reversion or writes_strong_candidates' -q`

Expected: all selected tests PASS and the existing R002 behavior is unchanged.

### Task 4: Carry rule identity into intraday candidates

**Files:**
- Modify: `tests/test_intraday_candidates.py`
- Modify: `tests/test_workspace_api.py`
- Modify: `services/engine/intraday/candidates.py`
- Modify: `apps/api/app/routers/workspace.py`
- Modify: `apps/web/src/api.ts`

- [x] **Step 1: Write a failing intraday propagation test**

Extend the test pool-item helper with `rule:R008` and `rule_name:[均值回归] 超跌修复`, discover intraday candidates, then assert:

```python
assert item["selected_rule_id"] == "R008"
assert item["selected_rule_name"] == "[均值回归] 超跌修复"
```

- [x] **Step 2: Run the test and verify RED**

Run: `pytest tests/test_intraday_candidates.py -k carries_candidate_rule_identity -q`

Expected: FAIL because the intraday dataclass has no rule fields.

- [x] **Step 3: Add nullable generic rule fields**

Add these nullable fields to the Python dataclass, response model, and TypeScript interface:

```python
selected_rule_id: str | None
selected_rule_name: str | None
```

```typescript
selected_rule_id: string | null;
selected_rule_name: string | null;
```

Parse tags with one local helper and pass the results to `IntradayCandidate`:

```python
def _tag_value(tags: list[str], prefix: str) -> str | None:
    return next((tag[len(prefix):] for tag in tags if tag.startswith(prefix)), None)

tags = [str(tag) for tag in (item.tags_json or {}).get("tags", [])]
selected_rule_id=_tag_value(tags, "rule:"),
selected_rule_name=_tag_value(tags, "rule_name:"),
```

- [x] **Step 4: Run engine and API tests**

Run: `pytest tests/test_intraday_candidates.py tests/test_workspace_api.py -q`

Expected: all tests PASS.

### Task 5: Render a prominent mean-reversion label

**Files:**
- Modify: `apps/web/src/stockLabels.ts`
- Modify: `apps/web/src/stockLabels.test.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/styles.css`

- [x] **Step 1: Write failing label-helper tests**

Export helpers that read `rule_name:` from workspace tags and return `均值回归` only when the selected rule id is `R008` or the rule name starts with `[均值回归]`. Assert R002 returns `null` and R008 returns the full strategy name plus the short badge label.

```typescript
const meanReversionCandidate = {
  symbol: "600001",
  manual_tags: ["rule:R008", "rule_name:[均值回归] 超跌修复"],
};
assertEqual(candidateRuleName(meanReversionCandidate.manual_tags), "[均值回归] 超跌修复", "候选显示规则名");
assertEqual(meanReversionLabel("R008", "[均值回归] 超跌修复"), "均值回归", "R008显示醒目标记");
assertEqual(meanReversionLabel("R002", "强势板块缩量回踩"), null, "其他规则不显示均值回归");
```

- [x] **Step 2: Run the TypeScript test and verify RED**

Run: `node --experimental-strip-types apps/web/src/stockLabels.test.ts`

Expected: FAIL because the helpers do not exist.

- [x] **Step 3: Implement and render shared labels**

Add these helpers to `stockLabels.ts`:

```typescript
export function candidateRuleName(tags: string[]) {
  const tag = tags.find((item) => item.startsWith("rule_name:"));
  return tag ? tag.slice("rule_name:".length) : null;
}

export function meanReversionLabel(ruleId?: string | null, ruleName?: string | null) {
  return ruleId === "R008" || ruleName?.startsWith("[均值回归]") ? "均值回归" : null;
}
```

Use `candidateRuleName(stock.manual_tags)` before generic pool modes in `candidateStrategyText`. In intraday and next-session rows render:

```tsx
<i className="strategy-pill mean-reversion">均值回归</i>
```

only when `meanReversionLabel(...)` returns a value.

Add this restrained high-contrast CSS without altering other pills:

```css
.strategy-pill {
  border: 1px solid #d8a0a0;
  border-radius: 4px;
  display: inline-flex;
  font-size: 11px;
  font-style: normal;
  font-weight: 700;
  line-height: 1;
  margin-left: 6px;
  padding: 3px 6px;
  white-space: nowrap;
}

.strategy-pill.mean-reversion {
  background: #fff1f0;
  border-color: #d88b86;
  color: #9f2f2a;
}
```

- [x] **Step 4: Run web tests and build**

Run: `node --experimental-strip-types apps/web/src/stockLabels.test.ts`

Run: `npm --prefix apps/web run build`

Expected: both commands PASS.

### Task 6: Verify notifications, regressions, and repository state

**Files:**
- Modify: `tests/test_notifications.py`

- [x] **Step 1: Add and run a DingTalk format regression test**

Pass an R008 candidate to the existing candidate notification formatter and assert:

```python
assert "规则：R008 [均值回归] 超跌修复" in text
```

Run: `pytest tests/test_notifications.py -k mean_reversion -q`

Expected: PASS without production notification changes; the rule-name prefix provides the prominent marker.

- [x] **Step 2: Run focused verification**

Run: `pytest tests/test_trade_plan_generator.py tests/test_next_session_candidates.py tests/test_intraday_candidates.py tests/test_workspace_api.py tests/test_notifications.py -q`

Expected: all tests PASS.

- [x] **Step 3: Run full verification**

Run: `pytest -q`

Run: `ruff check --select F,B <modified Python files>`

Run: `node --experimental-strip-types apps/web/src/stockLabels.test.ts`

Run: `npm --prefix apps/web run build`

Expected: every scoped command exits 0. Full-repository Ruff debt is outside this change.

- [ ] **Step 4: Inspect and commit only scoped changes**

Run: `git diff --check` and `git status --short`.

Commit the implementation with:

```bash
git add services/engine/rules/seed_rules.py services/engine/risk/trade_parameters.py \
  services/engine/plans/generator.py services/engine/research_pool/candidates.py \
  services/engine/intraday/candidates.py \
  apps/api/app/routers/workspace.py apps/web/src/api.ts apps/web/src/stockLabels.ts \
  apps/web/src/stockLabels.test.ts apps/web/src/App.tsx apps/web/src/styles.css \
  tests/test_trade_plan_generator.py tests/test_next_session_candidates.py \
  tests/test_intraday_candidates.py tests/test_workspace_api.py tests/test_notifications.py \
  docs/superpowers/plans/2026-07-27-mean-reversion-strategy.md
git commit -m "feat: add mean reversion candidate strategy"
```

- [ ] **Step 5: Push main without running live jobs**

Run: `git push origin main`

Expected: push succeeds, or the exact network error is reported while the local commit remains intact.
