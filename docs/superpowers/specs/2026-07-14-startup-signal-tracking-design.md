# Startup Signal Tracking Design

## Goal

Make startup signals unmistakable in the candidate workflow and show two separate, non-forward-looking measures: historical 5/10/20-trading-day performance for comparable signals and the current candidate's realised return since its signal date.

## Scope

The feature applies only to automatic candidates tagged as `candidate_pool:startup_preheat` or `candidate_pool:expansion_confirm`. Manual-focus stocks and ordinary candidate tiers remain unchanged.

## Existing Building Blocks

- Candidate generation already emits startup score, label, reasons, signal date and startup/expansion tags.
- Candidate walk-forward replay already produces raw and guarded 5/10/20-day forward-return summaries by candidate scope and startup-signal bucket.
- Workspace responses already expose tags, source, rank, score and candidate tier data to the web client.
- Daily bars provide a current candidate's realised close-to-close return without using future prices.

## Design

### Signal Classification

`candidate_pool:startup_preheat` maps to the visible state `启动观察`. It is a watch-only state and never implies an entry recommendation.

`candidate_pool:expansion_confirm` maps to `启动确认`. This records that price-volume and sector expansion have confirmed the move, but existing risk gates still determine whether it can enter an action tier.

The backend derives a signal date from the candidate's current automatic batch tags. Missing or invalid dates yield no tracking row rather than borrowing a prior candidate date.

### Startup Tracking API

Add one read-only startup-tracking endpoint that accepts the current automatic startup candidate symbols and returns one row per symbol. A row contains:

- symbol, signal type, signal date, score, label and reasons;
- current realised return from signal-date close to latest available close;
- elapsed trading days and progress for 5/10/20 days;
- historical results for the same signal type and each horizon: completed sample count, win rate, median raw return and median guarded return.

Historical summaries use only completed walk-forward observations whose signal date is before the latest observation used by the report. The endpoint never uses future prices to enrich a live candidate and does not participate in ranking, plan generation or confidence scoring.

The response is cached using the existing candidate replay cache pattern. A missing cache or insufficient completed history returns an explicit empty statistic rather than a fabricated percentage.

### Current Return

For each live startup candidate, load the exact signal-date daily bar and latest daily bar at or after the signal date. `realised_return = latest_close / signal_close - 1`. The field is `null` if either bar is unavailable. Horizon status is `进行中` until the relevant number of subsequent trading dates exists, then `已完成`.

### Web Presentation

The candidate area adds a compact `启动追踪` strip only when startup rows exist. It shows the state badge first:

- yellow `启动观察` with startup score and up to two reasons;
- green `启动确认` with confirmation date and reasons.

Each row has two explicitly labelled groups:

- `历史验证`: 5/10/20-day sample count, win rate and median return;
- `当前跟踪`: realised return since signal date and each horizon's completion state.

The existing candidate-tier grouping exposes a separate startup filter/count. The after-close drawer displays counts for `启动观察` and `启动确认`; it does not duplicate detailed tracking rows.

## Error Handling

- Empty startup candidate set returns an empty list and the web hides the strip.
- No completed replay sample displays `样本不足`, not zero return or zero win rate.
- Missing signal-date or latest bar displays `数据待补` for current performance.
- API failure preserves the existing candidate list and displays a compact tracking-load error only in the startup strip.

## Verification

- Backend tests cover tag classification, strict signal-date bars, 5/10/20 progress and no-data behaviour.
- Replay tests prove historical statistics exclude incomplete/future observations.
- API tests cover an empty response and a mixed preheat/confirmed response.
- Web source tests cover visible Chinese state labels and separation of historical versus current performance.
- Run focused backend tests, frontend type/source checks and production build.
