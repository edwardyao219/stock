# Runtime Reliability Design

## Goal

Make scheduled research results trustworthy and maintainable without changing any stock-selection rule, triggering historical tasks, or deleting existing logs.

## Scope

1. Mark an empty feature computation as a warning before plan generation can report a misleading success.
2. Record the duration and outcome of rule-regression work in the existing job status surface.
3. Extend scheduler health with explicit timeout and failed-task state where existing status data allows it.
4. Provide a dry-run-first local log-retention command that only handles files under `logs/`.
5. Replace production `datetime.utcnow()` calls with a shared naive-UTC helper to retain database semantics.

## Approaches Considered

- Change stock-selection thresholds: rejected because the observed problem is missing data, not candidate quality.
- Rewrite Celery logging with rotating handlers: rejected because prefork workers would write concurrently to the same rotating file. A standalone maintenance command is deterministic and does not disturb running workers.
- Optimize rule regression before measuring it: rejected. First persist duration and outcome; later optimization can target the measured bottleneck.

## Design

`_compute_features_step` will return `warning` whenever a nonzero requested universe produces zero stock features. The pipeline continues so its existing candidate data gate emits the precise blocking reasons, but the step result can no longer be mistaken for usable data.

The rule-regression task records start and finish metadata in the existing Redis-backed status cache. Scheduler status uses the same payload to distinguish running, completed, failed, and overdue work without enqueueing any recovery work.

`services.jobs.log_maintenance` will list or archive only explicitly named files below `logs/`. Default operation is dry-run; removal requires an explicit retention flag. It is not invoked by Celery or launchd in this change.

`services.shared.time.now_utc()` returns a timezone-naive datetime representing the current UTC moment. Existing database `DateTime` columns currently store naive UTC values, so each replacement keeps the stored value format unchanged.

## Testing

Tests cover the zero-feature warning, status duration fields, log-maintenance dry-run selection, and naive UTC contract. Existing pipeline, API, and realtime quote tests provide regression coverage.
