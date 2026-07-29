# Value Reversion Setup Design

## Goal

Add a separate value-reversion route for reasonably valued stocks that have
pulled back, stabilized on contracting turnover, and then started with
controlled volume. Keep `R008` unchanged as the deeper oversold-repair route.

## Signal Model

`R009 [均值回归] 价值蓄势` uses the existing current valuation context. A stock
is value-eligible when fundamentals are not weak and either `0 < PE <= 25` or
`0 < PB <= 3`.

The shared price boundary requires an 8%-35% drawdown from the rolling 60-day
high, a 20-day return between -25% and 18%, and a price no more than 15% below
or 12% above MA20.

The route has two states:

- Setup observation: 3-day range no greater than 12%, 3-day return between
  -6% and 6%, and 3-day average turnover amount no greater than 75% of the
  preceding 5-day average.
- Launch confirmation: the preceding 3-day range and amount contraction meet
  the setup limits, current amount is 1.15-2.2 times the preceding 5-day
  average, daily return is 1.5%-8.5%, the close is in the top 35% of the daily
  range, and it closes at or above the preceding 3-day high.

## Candidate Behavior

A setup match enters the observation pool with an explicit value-reversion
reason. A launch confirmation can enter the formal pool in strong-trend,
rebound, or range regimes. In panic, weak-trend, rebound-unconfirmed, or
unknown regimes it remains visible as observation. Market state therefore
changes actionability, not discovery.

The rule name starts with `[均值回归]`, so the existing intraday, web, and
DingTalk strategy labeling remains visible without adding another UI concept.

## Guardrails

- Do not classify loss-making/high-PB examples as value reversion merely
  because price fell.
- Keep ST, suspension, overheat, and volume-trap filters.
- Do not loosen `R008` or existing trend rules.
- Do not run live selection or notification jobs as part of deployment.
- Use absolute PE/PB thresholds first. Add historical or industry percentiles
  only after replay evidence shows that the simpler boundary is inadequate.

## Tests

- Daily features expose current/prior 3-day range, amount contraction,
  distance from the 60-day high, and prior-platform breakout.
- A Giant-Network-like contracted pullback remains an observation candidate.
- A Small-Commodity-City-like volume launch becomes formal in a range market.
- The same launch remains observable in unsafe regimes.
- An Innovation-Medical-like high-PB context does not match the value route.
- Existing mean-reversion, candidate, plan, intraday, and notification tests
  remain green.
