# Startup State Loop Design

## Goal

Unify after-close startup screening and intraday startup decisions into one four-state lifecycle that is evidence-based, prevents premature execution, records state transitions, sends only actionable notifications, and supports outcome analysis without future data.

## Scope

This design covers startup-oriented candidates and their intraday lifecycle:

- after-close startup classification;
- intraday confirmation and invalidation;
- research event persistence;
- unexecuted paper-plan guarding and cancellation;
- DingTalk confirmation and invalidation notifications;
- Web presentation;
- 1/3/5-day outcome analysis.

It does not add strategy factors, tune thresholds against recent returns, introduce automatic brokerage orders, or refactor unrelated large modules.

## Canonical States

The internal state keys and Chinese labels are:

| Key | Label | Meaning |
| --- | --- | --- |
| `preheat` | 启动预热 | A startup context exists, but individual price/volume support is incomplete. |
| `probing` | 启动试探 | Individual price/volume is improving, but sector or market confirmation is incomplete. |
| `confirmed` | 启动确认 | Sector expansion, individual support, and the market risk gate all permit confirmation. |
| `invalidated` | 启动失效 | A hard risk, overheat/trap condition, or post-confirmation sector weakening invalidates the startup. |

Chinese labels are presentation values. Decisions, persistence, tests, and API contracts use the canonical keys.

## Transition Rules

After-close discovery may emit only `preheat` or `probing`. It must never emit `confirmed`, because the next session's sector expansion, individual support, and market risk evidence do not yet exist.

Intraday transitions are evaluated from snapshots available at the evaluation time:

```text
preheat -> probing -> confirmed -> invalidated
    |          |             |
    +----------+-------------+-> invalidated
```

The resolver may keep a state unchanged. It may skip directly from `preheat` to `confirmed` when every confirmation condition is present at the first eligible checkpoint. It must not downgrade `probing` to `preheat` merely because a later snapshot is inconclusive.

`invalidated` is terminal for the trade date. The symbol may begin again from `preheat` on a later trading date.

## Evidence Rules

### After Close

The existing startup profile remains a low-dimensional score derived from sector warming, trend, relative strength, volume, position, risk, overheat, and volume-trap evidence.

- `probing`: startup score is at least the existing 70-point threshold and no hard risk is present.
- `preheat`: the startup context exists but the probing threshold is not met.
- A hard risk does not create an intraday `invalidated` event after close. It prevents the candidate from becoming a startup candidate through the existing safety filters and records risk evidence in the candidate explanation.

### Intraday Confirmation

`confirmed` requires all of the following:

- the current checkpoint is 10:30 or later;
- the candidate sector is in the persisted set of sustained startup sectors;
- the individual state is supportive (`strong_continuation` or `gap_down_repair`);
- volume is confirmed, or persisted sector feedback shows strength holding;
- the market is not `risk_off`;
- no hard risk flags are present;
- the candidate qualifies for the existing formal intraday tier.

The scheduled 10:30 snapshot must pass persisted confirmed sectors into candidate discovery before state resolution. Candidate bindings and research events must use that gated result.

### Intraday Invalidation

`invalidated` is emitted when any of these conditions is present:

- distribution, fading, downside pressure, or volume expansion on weakness;
- intraday overextension;
- market `risk_off`;
- sustained sector confirmation was previously present but the sector later weakens;
- an equivalent existing hard-risk flag blocks the formal intraday tier.

Before the first confirmation-eligible checkpoint, absence of a sustained sector is incomplete evidence, not invalidation.

## Components

### State Resolver

A focused engine module owns canonical constants, labels, the immutable decision result, and the pure transition function. It receives the prior state plus already-computed evidence and returns:

- current state and label;
- confirmation evidence;
- invalidation reasons;
- next observation conditions;
- whether a state transition occurred.

The resolver does not query the database, send notifications, or mutate plans.

### After-Close Integration

After-close discovery maps its profile to `preheat` or `probing` and persists the canonical state in existing candidate tags. Existing startup score and reason tags remain available for compatibility, while the state key becomes the authoritative value.

### Intraday Integration

Intraday candidate discovery computes raw individual, sector, volume, feedback, and market evidence first. It then invokes the state resolver once, after all evidence is assembled. The returned state supplies the API's startup fields and cannot disagree with the final selection tier.

The latest same-day state comes from persisted startup events when available. Otherwise, the after-close candidate tag supplies the initial state. Candidates outside the startup pool may display a derived state, but they do not create startup lifecycle events or affect plans.

### Event Persistence

The existing `ResearchSignalLedger` stores lifecycle events with source `startup_state` and signal types `startup_preheat`, `startup_probing`, `startup_confirmed`, and `startup_invalidated`.

Event identity is one row per source, signal date, symbol, and signal type. Recording retries must return only newly created transition events so downstream notifications are idempotent. Evidence JSON stores the prior state, reasons, next conditions, selection tier, sector signal, market status, and snapshot checkpoint.

No new table is introduced.

### Plan And Paper Execution

The plan guard applies only to candidates tagged as startup lifecycle candidates. Unrelated formal strategies keep their existing execution behavior.

- `preheat` and `probing`: unexecuted startup plans cannot open a paper position.
- `confirmed`: the startup gate no longer blocks an otherwise valid plan; existing strategy and risk rules still apply.
- `invalidated`: unexecuted startup plans become `cancelled` and retain an invalidation reason in their plan evidence or risk notes.
- Executed plans and open positions are never cancelled retroactively. Existing position risk management continues unchanged.

Confirmation does not guarantee plan generation. A candidate still needs an eligible strategy plan and all existing entry conditions.

### Notifications

DingTalk consumes only newly persisted `startup_confirmed` and `startup_invalidated` events.

A confirmation message contains symbol/name, sector, confirmation evidence, current price, and the reminder that confirmation still requires the existing plan trigger. An invalidation message contains symbol/name, sector, invalidation reasons, and the unexecuted-plan result.

`preheat` and `probing` never send DingTalk messages. Historical replay and recovery paths never send lifecycle notifications.

### Web And API

Workspace startup responses expose:

- canonical state and Chinese label;
- state time;
- confirmation evidence;
- invalidation reasons;
- next observation conditions;
- plan availability.

The candidate list, startup tracking strip, and intraday snapshot panel all use this same payload. The UI does not infer state from labels.

### Outcomes

Outcome analysis uses persisted lifecycle events rather than the first raw `starting` or `accelerating` snapshot. It reports by state for 1/3/5 trading-day horizons:

- sample count;
- win rate and average return;
- maximum gain and maximum drawdown;
- probing-to-confirmed conversion rate;
- confirmed-to-invalidated rate.

Signal prices and timestamps come from the first persisted transition event. Future bars are used only for outcome evaluation and never for signal decisions.

## Error Handling

- Missing or unhealthy market/sector evidence fails closed: confirmation is withheld and the next condition explains the missing evidence.
- Missing quotes prevent event creation because no auditable signal price exists.
- Ledger retries do not duplicate events or notifications.
- Notification failure does not roll back the signal event or plan-state transaction; it is reported through existing notification results.
- Historical APIs remain readable when legacy event keys are present, but all new writes use canonical keys.

## Testing

Implementation follows test-driven development. Required tests cover:

- after-close classification never produces `confirmed`;
- pure transition behavior, including terminal same-day invalidation and next-day reset;
- 10:30 scheduled discovery receives sustained sectors before resolving states;
- confirmation requires sector, individual, and market evidence together;
- incomplete evidence remains preheat/probing instead of invalidating early;
- event persistence deduplicates by date, symbol, and state;
- only newly created confirmation/invalidation events notify;
- startup plan execution is blocked before confirmation and cancelled on invalidation;
- unrelated strategy plans remain unaffected;
- outcome aggregation uses four-state events and 1/3/5-day horizons;
- API and Web render the canonical payload without label inference.

Focused tests run before the complete backend suite and frontend build.

## Delivery Order

1. Canonical state resolver and unit tests.
2. After-close and intraday integration, including the scheduled 10:30 evidence fix.
3. Ledger transitions and idempotent notification dispatch.
4. Startup-only plan guard and invalidation cancellation.
5. Event-based outcomes and API payload.
6. Web presentation and full regression verification.

