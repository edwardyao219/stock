# Strong Benchmark Sample Funnel Design

## Goal

Show how strong-start benchmark signals mature into 1, 3, and 5 trading-day
samples, while separating normal waiting from unusable data. Unusable samples
must never affect returns, win rates, failure rates, the 20-sample policy gate,
candidate weights, or buy rules.

## Trading-Day Rule

Use the distinct dates already present in the full-market `DailyBar` table as
the local trading calendar. For each signal date, day 1, 3, and 5 mean the
exact first, third, and fifth market trading dates after the signal date.

For each horizon:

- `completed`: the signal-day close and exact target-day close both exist;
- `waiting`: the target market trading date has not arrived in `DailyBar`;
- `unavailable`: the market reached the target date, but the signal-day or
  target-day leader bar is missing. This includes suspension and incomplete
  leader data because the stored data cannot distinguish them reliably.

Never substitute a later leader bar for a missing target-day bar.

## Backend Shape

The outcome loader queries the relevant distinct market dates once, then looks
up leader bars by exact date. Existing `sample_count` remains the completed
count for compatibility. The funnel covers only `strong_benchmark` outcomes
within the existing latest-120-outcome evidence window. The API exposes that
window limit so the displayed total is not mistaken for an all-time count.

Each horizon summary adds:

- `total_signal_count`;
- `completed_count`;
- `waiting_count`;
- `unavailable_count`;
- `unavailable_reasons`, grouped into `missing_signal_close` and
  `missing_target_close`.

The top-level summary adds `window_limit: 120`.

Only `completed` values feed average return, win rate, failure rate, and
`eligible_for_policy`.

## API And Page

`GET /market/mainline-outcome-summary` exposes the additional funnel fields on
each horizon. The sector page keeps the current compact strip and adds one
scannable line:

`总信号 N / 1日 成熟A 等待B 异常C / 3日 ... / 5日 ...`

When unavailable samples exist, append their reason counts. Do not add another
card or change the existing policy warning.

## Error Handling

An empty market calendar leaves outcomes waiting rather than treating them as
losses. When the signal date exists in the market calendar but the leader's
signal-day close is missing, every horizon is immediately unavailable. With a
valid signal close, a missing target close becomes unavailable only after that
target market date exists. All counts are recalculated from stored data, so a
later data repair automatically moves a sample from unavailable to completed.

## Verification

Tests must prove:

- a missing third-day bar is unavailable and the fourth-day bar is not used;
- a future fifth-day target remains waiting;
- unavailable samples do not enter return statistics or the 20-sample gate;
- the API exposes funnel counts and reasons;
- the page displays total, completed, waiting, and unavailable counts without
  overflow on desktop and mobile widths.
