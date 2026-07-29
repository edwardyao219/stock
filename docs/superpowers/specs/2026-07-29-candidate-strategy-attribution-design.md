# Candidate Strategy Attribution Design

## Goal

Make candidate walk-forward results reflect the current discovery algorithm and
attribute each result to the strategy that selected it. This provides reliable
evidence for later R008, R009, general-strategy, and 10-plus-5 quota calibration
without changing live candidate thresholds or rankings in this change.

## Current Problem

The candidate replay has two evidence gaps:

1. Candidate discovery caches still use `candidate-v5-startup-signal`. Recent
   mean-reversion, value-reversion, quota, ranking, and regime-independent
   discovery changes can therefore reuse discoveries produced by older logic.
2. Live discovery already returns `selected_rule_id` and `selected_rule_name`,
   but `WalkForwardCandidate` drops both fields. Replay summaries can group by
   selection mode and sector style, but cannot compare R008, R009, and general
   strategies using the actual candidates that entered the final list.

The existing daily rule regression is not a substitute. It evaluates rule
signals directly, while candidate walk-forward replay evaluates the complete
discovery, ranking, quota, and execution-guard path.

## Selected Approach

Extend the existing candidate walk-forward model and summaries.

- Preserve the selected rule identity when converting a discovery item into a
  `WalkForwardCandidate`.
- Reuse the existing raw and guarded return calculations and `_return_summary`.
- Add rule-level counts, horizon summaries, and monthly horizon summaries to
  the existing replay payload.
- Extend the existing monthly-shard merger to merge the new summaries.
- Increment both discovery and replay-effect cache versions so old payloads are
  ignored without deleting them.

No separate replay engine, endpoint, database table, or scoring service is
introduced.

## Candidate Contract

`WalkForwardCandidate` adds two optional fields:

- `selected_rule_id`
- `selected_rule_name`

The values come directly from each final discovery candidate. Optional defaults
keep tests and callers that construct replay candidates manually compatible.

A missing or blank rule ID is normalized to the stable key `unmatched`, with
the display name `未匹配策略`. This keeps observation, potential, and
exploration candidates visible in attribution totals rather than silently
dropping them.

## Summary Contract

`summarize_walk_forward_replay` adds:

- `rule_counts`: a stable list of `rule_id`, `rule_name`, and `count` objects.
- `rule_horizons`: horizon to rule ID to raw and guarded return summaries.
- `monthly_rule_horizons`: horizon to month to rule ID to raw and guarded
  return summaries.

Each raw or guarded summary keeps the existing fields:

- `sample_count`
- `avg_return`
- `win_rate`
- `total_return`

Rule IDs are sorted for deterministic payloads. When candidates with the same
rule ID contain different display names, the first non-empty name in replay
order is used; the rule ID remains authoritative.

The rule counts cover every non-noise replay candidate. Horizon sample counts
may be lower when future prices are unavailable, matching existing summary
semantics.

## Data Flow

1. Historical candidate discovery returns the final capped and quota-adjusted
   candidate list.
2. Replay copies the final candidate's selected rule identity into
   `WalkForwardCandidate` before calculating forward returns.
3. The existing raw and guarded returns are grouped by normalized rule ID.
4. Overall, style, selection-mode, startup, and new rule summaries are emitted
   together from the same candidate population.
5. API replay-effect responses expose the additional fields through the
   existing payload and merge them when monthly cached shards are used.

This attribution does not read future prices during discovery. Future prices
remain confined to the existing outcome-evaluation step.

## Cache Invalidation

Increment `CANDIDATE_DISCOVERY_CACHE_VERSION` to a value that identifies the
current strategy-attribution discovery generation and still fits the existing
32-character database column.

Increment `CANDIDATE_REPLAY_EFFECT_CACHE_VERSION` because the aggregate payload
schema gains rule-level fields. File and database cache loaders already require
an exact version match, so old rows and files become unreachable without a
destructive cleanup or migration.

The change must not force a replay during deployment. New results are computed
only when an existing replay caller runs later.

## Shard Merging

The existing replay-effect API can merge monthly summary shards. Its merger
must include the new rule fields:

- add rule counts by normalized rule ID;
- merge raw and guarded summaries using their sample counts, total returns, and
  implied winning observations, following the existing summary merger pattern;
- retain deterministic rule names and ordering;
- preserve each month's rule summary under `monthly_rule_horizons`.

Merging must produce the same rule-level totals as summarizing the equivalent
unsharded candidate population.

## Guardrails

- No live candidate score, filter, threshold, plan availability, or 10-plus-5
  quota changes.
- No automatic promotion or demotion based on small samples.
- No replacement of the existing rule-regression or learning systems.
- No cache deletion or database migration.
- No new dependency.

## Testing

- Discovery items transfer selected rule ID and name into replay candidates.
- R008, R009, a general rule, and unmatched candidates produce separate counts.
- Rule-level raw and guarded 5-, 10-, and 20-day summaries match the existing
  return-summary semantics.
- Monthly rule summaries keep months and rule IDs separate.
- Monthly shard merging matches an equivalent unsharded summary.
- Missing rule fields remain compatible and appear under `unmatched`.
- Both cache versions change, and the discovery cache version remains within
  the database column limit.
- Existing walk-forward, replay API, job-pipeline, and full regression suites
  remain green.

## Non-Goals

- No live or historical replay execution during development or deployment.
- No DingTalk notification, candidate selection, recovery, or historical job.
- No threshold calibration, dynamic quota, valuation percentile, or new volume
  factor in this change.
- No frontend redesign; existing replay payload consumers may adopt the new
  fields later.
