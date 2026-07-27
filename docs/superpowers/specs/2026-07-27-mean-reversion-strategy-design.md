# Mean Reversion Strategy Design

## Goal

Add an independent technical mean-reversion strategy that can participate in the existing next-session and intraday candidate flows while remaining visibly distinguishable from trend-following candidates.

The strategy is research status (`TESTING`) but is eligible for normal candidate selection, trade-plan generation, paper execution, backtesting, and per-rule performance reporting.

## Non-goals

- Do not reinterpret or broaden `R002`; it remains a strong-trend pullback strategy.
- Do not add a valuation-reversion strategy in this change. Historical PE/PB percentiles and industry-relative valuation evidence will be designed separately as `R009`.
- Do not create a second candidate pipeline or a new strategy framework.
- Do not trigger live screening, DingTalk delivery, recovery, or historical replay during development.

## Strategy Rule

Create `R008 [均值回归] 超跌修复` as a swing rule with `TESTING` status.

The daily entry snapshot must meet all of these conditions:

- The security is not ST and is not suspended.
- `fundamental_verdict` is not `weak`.
- `rsi_14` is between 20 and 38.
- `distance_to_ma20` is between -12% and -4%.
- `return_5d` is between -15% and -4%.
- `return_20d` is at least -22%.
- `ma20_slope_20d` is at least -3%, preventing a steeply falling mean from being treated as support.
- `max_drawdown_20d` is at least -22%.
- `close_position_in_range` is at least 0.45, requiring visible stabilization instead of buying the session low.
- `volume_trap_risk_score` is at most 65.

The next-session trigger is the existing calculated `entry_trigger_price`. For `R008`, its reference price is `max(close, ma5)` so the plan requires a short-term recovery confirmation. A gap above 3% invalidates entry.

The stop remains the tighter of ATR and recent structural support, bounded by the existing risk profile. Position size is capped at 8%. The first recovery target is MA10 when it is above entry, otherwise one risk unit; the second target is MA20 when it is above the first target, otherwise another half risk unit. The maximum holding period is eight trading days.

## Candidate Integration

The current formal-candidate filter assumes a trend strategy and rejects low-trend, below-MA20 securities. Add one narrow strategy-aware branch:

- Existing rules continue through the current formal-candidate and market-regime gates unchanged.
- A candidate whose selected rule is `R008` uses a dedicated mean-reversion gate based on the rule conditions and hard safety filters.
- `R008` is evaluated in every market regime so valid oversold-repair signals are not
  hidden by the market classifier.
- In `strong_trend`, `rebound`, and `range`, a valid `R008` match may enter the formal
  candidate pool.
- In `panic`, `weak_trend`, `rebound_unconfirmed`, and `unknown`, the same match is
  retained as an `observation` candidate with its `R008` identity and visible
  `均值回归` label.
- Observation-mode `R008` candidates do not generate trade plans or become executable
  paper entries. The market regime changes actionability, not signal discovery.
- It receives a small rule score bonus so it participates in normal ranking, but it gets no reserved slot and cannot bypass sector balancing or the global candidate limit.

This keeps mean reversion inside the existing candidate lifecycle, avoids missed signals,
and does not weaken trend-rule filters or risk-state execution controls.

## Visible Strategy Marking

Persist both `rule:R008` and `rule_name:[均值回归] 超跌修复` on selected research-pool items. The generic `rule_name:` tag is reusable for every rule and lets the UI display a human-readable name without a hard-coded rule map.

For next-session candidates:

- Show a high-contrast `均值回归` pill in the stock row.
- Show `策略 [均值回归] 超跌修复` before the generic pool mode in the detail panel.

For intraday candidates:

- Carry nullable `selected_rule_id` and `selected_rule_name` fields from the research-pool tags through the engine dataclass, workspace API, and web API type.
- Show the same `均值回归` pill beside the existing candidate-tier pill.

For DingTalk candidate messages, reuse the existing rule-name line. Because the rule name starts with `[均值回归]`, no separate notification format or duplicate line is required.

## Backward Compatibility

- Existing research-pool items may not have `rule_name:`. Both API fields remain nullable and the UI simply omits the pill.
- Existing strategy priorities, rule filters, notification text, and trade parameters remain unchanged unless the selected rule is `R008`.
- The new rule remains independently disableable through the existing rule list and independently measurable through rule-level backtest and paper reports.

## Testing

Use test-first development for each behavior:

- Rule-definition tests assert the exact `R008` entry bounds, status, holding period, and tag.
- Candidate tests prove an eligible `R008` snapshot can become a formal candidate in a range market despite failing the trend filter.
- Candidate tests prove the same snapshot remains visible as an `R008` observation
  candidate in panic, weak, unconfirmed-rebound, and unknown regimes while producing
  no executable plan.
- Trade-parameter tests prove short-mean confirmation, 3% gap protection, MA10/MA20 recovery targets, position cap, and holding period.
- Persistence tests prove the human-readable `rule_name:` tag is stored and old tag cleanup does not leave stale rule names.
- Intraday engine/API tests prove rule identity survives from the research-pool item to the response.
- Web tests prove `R008` renders as an obvious `均值回归` label while unrelated rules remain unchanged.
- Notification tests prove the existing DingTalk rule line contains `[均值回归] 超跌修复`.
- Run focused Python and web tests first, followed by the repository's full verification commands before committing implementation.

## Rollout And Measurement

The initial implementation did not run live jobs. This approved follow-up reruns the
current after-close screening once after verification so the updated discovery behavior
is reflected in the candidate pool and DingTalk. Backtest and paper results remain
separate from other rules. Promotion beyond `TESTING`, parameter relaxation, or the
future `R009` valuation strategy requires accumulated out-of-sample evidence; it is not
automatic in this change.
