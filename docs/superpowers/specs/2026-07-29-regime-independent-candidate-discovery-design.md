# Regime-Independent Candidate Discovery Design

## Goal

Discover up to 15 technically qualified next-session candidates in every market
regime without weakening hard safety or quality filters. Market conditions may
change ranking and actionability, but must not erase an otherwise valid stock
signal.

## Current Problem

Candidate discovery currently mixes two decisions:

1. whether a stock has a valid technical or strategy signal;
2. whether the current market permits a trade plan.

`_passes_market_regime_gate` and `_regime_candidate_limit` remove or truncate
general candidates before the existing `plan_availability`, market-stress tier,
and `core_action` guards run. In weak, panic, or unconfirmed-rebound regimes,
the system can therefore miss valid signals even though downstream execution
is already independently blocked.

## Selected Approach

Separate discovery from execution.

- Discovery uses strategy conditions, hard safety filters, mode-specific
  quality filters, and the existing 15-candidate cap.
- Market regime remains an input to score adjustments, weak-market ranking,
  reasons, candidate tiers, and plan availability.
- Only downstream `core_action` candidates may generate plans. Existing
  market-stress logic may reduce that tier to zero, and `market_guard` remains
  authoritative for non-actionable candidates.

No second candidate list or new UI surface is introduced.

## Discovery Flow

For each feature context:

1. Apply the existing hard safety filter. ST stocks, suspended stocks, weak
   fundamentals, invalid prices, severe overheat, volume traps, and excessive
   20-day extension remain excluded.
2. Evaluate strategy rules without a market-regime gate.
3. Classify the technical state:
   - An R009 contracted setup remains `observation`.
   - An R009 volume launch is `formal_strategy` in every regime.
   - An R008 or general rule match that passes its existing formal quality
     filter is `formal_strategy` in every regime.
   - Observation, potential-watch, and exploration paths continue to require
     their existing quality filters, but no longer require regime permission.
4. Apply the existing regime score delta and weak-market ranking preferences.
   These affect order, not eligibility.
5. Select at most the clamped requested limit, which remains 15 by default.
6. Apply the existing R009 reservation: no more than five R009 candidates,
   with general candidates backfilling unused R009 capacity.

The final result still returns fewer than 15 when fewer than 15 stocks satisfy
the technical and safety requirements.

## Limits And Response Contract

- `requested_limit` continues to report the caller value.
- `effective_limit` becomes the clamped discovery limit in the range 1 to 15.
- The regime-derived candidate limit is removed from discovery rather than
  renamed or retained as dead advisory logic.
- Candidate tiers retain their existing maximum of three `core_action` items
  and their independent market-stress limits.
- The selection funnel adds `market_guard_selected`, counted after final plan
  availability is assigned, so operators can distinguish discovered signals
  from market-blocked signals.

## Actionability Guardrails

- `plan_availability.status == "market_guard"` remains mandatory for formal
  candidates in panic, weak-trend, unconfirmed-rebound, or `risk_off` states.
- Candidate tiering continues to move market-blocked items into `watch_wait`.
- Plan generation continues to consume only `core_action` formal candidates.
- Data evidence blocks, rule-entry checks, startup confirmation, and paper-entry
  gates are unchanged.
- Notifications may contain more observation candidates, but their market guard
  and tier labels remain visible. No notification is sent during development.

## Copy Updates

Market notes must describe the new boundary accurately:

- Weak trend: keep screening high-quality signals, but execute conservatively.
- Panic: keep technical signals visible, but do not open new positions.
- Unconfirmed rebound: keep repair signals visible and wait for confirmation.
- Unknown: rank conservatively without suppressing discovery.

## Testing

- The same technically qualified general strategy candidate remains discoverable
  across strong, range, weak, panic, and unconfirmed-rebound regimes.
- Weak-market formal candidates are marked `market_guard` and do not become
  `core_action` plan inputs.
- An R009 launch remains `formal_strategy` in weak regimes while its plan is
  market-blocked; an R009 setup remains observation-only.
- A weak-market fixture with at least 15 qualified stocks returns 15 candidates.
- Low-quality and hard-safety failures remain excluded in every regime.
- The existing 10-general plus 5-R009 quota remains intact.
- Candidate, notification, job-pipeline, trade-plan, and full regression suites
  remain green.

## Non-Goals

- No threshold loosening or new factor weights.
- No change to the five-slot R009 ceiling.
- No UI redesign, schema migration, new dependency, live selection, DingTalk
  notification, replay, recovery, or historical job.
