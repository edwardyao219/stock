# After-Close Safe Recovery Design

## Goal

Detect a missed or failed 18:00 after-close workflow, safely restore market data, features, candidates and status, and notify the operator without duplicating paper trading, rule regression or candidate-stock messages.

## Scope

The design covers the existing Celery after-close task, status cache, DingTalk dispatch and after-close drawer. It does not add a new scheduler service, create a new page, or automatically replay historical paper trades.

## State Model

Each after-close run records an observable state in Redis for its trade date:

- `scheduled`: the after-close task has started and registered its heartbeat;
- `running`: a normal or recovery run is actively processing;
- `completed`: all required safe-recovery steps completed and the after-close status was written;
- `failed`: the run stopped with an error, preserving completed and missing steps.

The payload includes `last_heartbeat_at`, completed steps, missing steps, recovery attempt count, error summary and safe recovery URL. Redis unavailability remains fail-open for the core pipeline, but the task returns an explicit monitoring warning.

## Safe Recovery

Celery schedules guard tasks at 18:20 and 18:40. For the current trading day, each guard checks the after-close state and status cache. A guard starts recovery only when the normal workflow is absent or failed.

Recovery runs only:

1. full market sync;
2. market feature preparation;
3. daily candidate data gate;
4. candidate discovery and tracking snapshots;
5. structured after-close status write.

It does not run paper simulation, paper review, rule regression, backtest learning or daily mechanical review. A manual API endpoint accepts only the current or most recent open trading day and uses the same safe-recovery path.

## Notification Idempotency

Candidate-screening delivery uses an idempotency key built from trade date and candidate batch identifier. A recovery repeats the stock message only when the original candidate-discovery stage did not finish. Failed recovery alerts use a separate date-and-stage key, allowing one detailed DingTalk alert per failed stage each day.

An alert includes trade date, completed steps, missing steps, error text and the safe recovery URL. Empty candidate results still receive a result message when a recovery was required, so a silent zero-candidate day is distinguishable from a missed workflow.

## API and Web

The existing after-close status response adds scheduler health, heartbeat, completed/missing steps, recovery attempts and `safe_recovery_url`. The after-close drawer renders one compact `调度健康` row with `正常`, `恢复中` or `需人工处理`; it keeps detailed recovery information in the existing drawer rather than adding a page.

## Safety and Verification

- Every recovery uses per-date locks and recovery-attempt limits.
- All candidate, notification and recovery mutations have focused tests for duplicate calls.
- Tests cover normal completion, missing heartbeat, failed sync, skipped recovery outside allowed date range and an empty candidate batch.
- The API test verifies the status payload and safe recovery endpoint authorization window.
