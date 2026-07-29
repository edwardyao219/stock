# Value Reversion Intraday Lifecycle Design

## Goal

Turn an `R009 [均值回归] 价值蓄势` setup found after close into a visible
intraday lifecycle on the next trading day:

`价值蓄势 -> 启动试探 -> 启动确认 / 启动失效`

Discovery remains independent of market regime. Market and sector conditions
may change actionability, but they must not hide a valid R009 setup or erase a
technical launch confirmation.

## Chosen Approach

Reuse the existing intraday candidate flow, startup event ledger, and DingTalk
transition notifications. Add one explicit `value_reversion` confirmation path
to the startup state resolver rather than creating a second lifecycle system.

The alternatives were rejected for these reasons:

- Persisting numeric price and amount baselines in string tags would make the
  tag format a fragile data protocol.
- Scanning historical daily bars during every intraday snapshot would repeat
  work already performed by daily feature computation.
- A separate R009 state machine would duplicate transition, persistence, and
  notification behavior.

## Daily Baseline Data

Daily feature computation adds three values to `StockFeatureDaily.features`:

- `recent_high_3d`: highest price of the latest three completed sessions.
- `recent_low_3d`: lowest price of the latest three completed sessions.
- `previous_amount_ma5`: average amount of the five sessions preceding the
  current feature row.

Candidate persistence adds the semantic tag
`candidate_pool:value_reversion_setup` only when R009 matched as a contracted
setup rather than an already completed daily launch. Numeric baselines remain
in structured feature data.

Intraday discovery loads the latest feature row before the current trading day
for all tracked R009 symbols in one query. Missing or non-positive baselines
leave the item in setup observation and expose a data-waiting next condition;
they never manufacture confirmation.

## Intraday Signal

Only candidates tagged `candidate_pool:value_reversion_setup` use this path.
The latest quote is evaluated against the completed-day baseline without using
future data.

### Amount Pace

Use A-share elapsed trading minutes across `09:30-11:30` and `13:00-15:00`.
Lunch contributes no elapsed minutes. The projected full-day amount ratio is:

`quote.amount / elapsed_session_fraction / previous_amount_ma5`

Confirmation is not allowed before 10:30, so the earliest evaluated fraction
is at least 25% of the trading session. The initial controlled-volume boundary
reuses R009's daily range: `1.15 <= projected ratio <= 2.20`. Historical replay
will calibrate the pace curve later; this change does not add time-of-day
parameters without evidence.

### State Rules

- `preheat`: quote is below 98% of `recent_high_3d`, or required baseline data
  is unavailable.
- `probing`: quote reaches at least 98% of the platform high, but confirmation
  is too early or one of price, range-position, or amount conditions is absent.
- `confirmed`: at or after 10:30, day change is 1.5%-8.5%, price is at or above
  `recent_high_3d`, quote range position is at least 0.65, and projected amount
  ratio is 1.15-2.20.
- `invalidated`: price falls below `recent_low_3d`, or an existing hard
  individual risk appears, including an overextended move, distribution,
  fading strength, downside pressure, or volume expansion on weakness. A
  confirmed state remains confirmed unless a hard individual risk later
  appears.

R009 confirmation evidence is strategy-specific: platform breakout,
controlled amount expansion, and strong intraday range position. Its next
conditions name the missing price, amount, time, or data requirement.

## Market And Sector Policy

R009 technical state does not require sector expansion and is not invalidated
solely by market risk-off. This follows the existing rule that every market
regime participates in discovery.

After state resolution:

- A confirmed R009 setup can become a formal intraday candidate when no hard
  risk or market risk-off flag is present.
- In risk-off conditions it remains a visible observation confirmation.
- Sector strength continues to affect score and context, but sector weakness
  alone does not cancel a stock-specific value-reversion breakout.

## Persistence And Notifications

The existing `startup_tracked`, `startup_stage`, signal ledger, deduplication,
and post-commit notification flow remain unchanged. R009 setup candidates set
`startup_tracked=true`, so only new `confirmed` and `invalidated` transitions
are persisted and sent. Preheat and probing snapshots remain silent.

No live selection, DingTalk, replay, recovery, or historical job is run while
deploying this code.

## Tests

- Daily features expose the three structured baseline values.
- Candidate persistence tags an R009 setup for tracking but does not tag an
  already launched R009 candidate as a new setup.
- An R009 setup below the platform remains preheat.
- Approaching or breaking the platform before 10:30 remains probing.
- A post-10:30 controlled-volume breakout becomes confirmed and carries
  R009-specific evidence.
- Missing baseline data cannot confirm.
- Excessive or weak volume expansion invalidates the setup.
- Market risk-off keeps a technical confirmation visible but non-formal.
- Existing startup strategies retain their sector-based confirmation rules.
- Candidate, startup-state, notification, pipeline, and full regression tests
  remain green.

## Non-Goals

- No historical or industry-relative valuation percentile in this change.
- No R009-specific ranking capacity in this change.
- No minute-bar replay or calibrated nonlinear volume curve in this change.
- No automated trading or position creation from an intraday confirmation.
