# Value Reversion Ranking Quota Design

## Goal

Keep the next-session candidate list at no more than 15 stocks while reserving
space for value-reversion discovery:

- Up to 10 general candidates when five R009 candidates qualify.
- Up to 5 `R009 [均值回归] 价值蓄势` candidates.
- General candidates backfill unused R009 capacity so the list can still reach
  15 when fewer than five R009 candidates qualify.

The quota must improve R009 visibility without weakening R009 eligibility,
hard safety filters, or actionability gates.

## Selection Model

The existing pipeline continues to build and rank formal, observation,
potential, and exploration candidates. Before final output, selection is split
into two buckets:

1. The R009 bucket receives every qualified R009 formal or observation
   candidate before normal slot truncation.
2. The general bucket uses the existing selected candidates after excluding
   R009.
3. Select at most five R009 candidates.
4. Fill the remaining capacity, up to 15 total, from the general bucket.
5. Apply the existing final actionability ordering after the two buckets are
   combined.

This produces 10 general plus 5 R009 when both buckets have enough candidates.
If only two R009 candidates qualify, the result may contain 13 general plus two
R009 candidates. If only six general candidates qualify, the system still
selects no more than five R009 candidates and may return fewer than 15 rather
than lowering quality.

The final list is always capped at 15, including potential and exploration
candidates. R009 is not allowed to exceed five merely because another bucket
has unused capacity.

## R009 Quality Ranking

R009 candidates are ranked independently from the generic trend-oriented
score. Confirmed R009 launches rank ahead of contracted setups. Candidates in
the same launch/setup state use a 100-point setup-quality score:

- Valuation, 20 points:
  - 20 when both `0 < PE <= 25` and `0 < PB <= 3` hold.
  - 15 when only one of the two preferred valuation limits holds while the
    candidate still satisfies R009 eligibility.
- Three-day platform compactness, 25 points:
  - 25 at or below 6% range.
  - 18 above 6% and at or below 9%.
  - 10 above 9% and at or below the 12% rule boundary.
- Amount contraction, 25 points:
  - 25 when the 3-day/preceding-5-day amount ratio is 0.35-0.60.
  - 18 when it is 0.20-0.75 but outside the preferred band.
  - 10 below 0.20, avoiding an automatic preference for extremely illiquid
    contraction.
- Pullback depth, 15 points:
  - 15 when distance from the 60-day high is -30% to -12%.
  - 8 elsewhere inside the R009 rule boundary.
- Short stability, 10 points:
  - 10 when absolute 3-day return is at most 3%.
  - 5 elsewhere inside the 6% setup boundary.
- MA20 proximity, 5 points:
  - 5 when distance to MA20 is -10% to 8%.
  - 2 elsewhere inside the R009 rule boundary.

Platform and contraction scoring use current setup fields for a setup candidate
and prior-setup fields for a confirmed launch. Valuation, pullback, and MA20
components use the current context in both states. Because the current 3-day
return already includes the launch day, a confirmed launch receives the neutral
five-point short-stability value. Existing candidate score and risk flags remain
unchanged and act as tie-breakers. The dedicated score does not turn an
observation into a formal candidate.

## Market And Safety Policy

- Market regime changes actionability, not R009 discovery or its five-slot
  ceiling.
- Existing positive-PE, PE/PB, drawdown, platform, contraction, ST,
  suspension, overheat, volume-trap, and weak-fundamental filters remain
  mandatory.
- A candidate blocked by hard safety filters cannot enter the R009 bucket.
- No lower-quality stock is added solely to fill the fifth R009 slot.
- Existing sector balancing is retained as a tie-breaker, but it cannot remove
  every otherwise qualified R009 candidate from the reserved bucket.

## Diagnostics And Presentation

The selection funnel adds:

- `value_reversion_qualified`
- `value_reversion_selected`
- `value_reversion_ranked_out`
- `general_selected`

Existing `selected`, formal, observation, potential, and exploration counts
remain available. Persisted ranks are assigned after the final 15-stock list is
formed, so web, intraday, and DingTalk consumers see consistent ranks.

No new UI or notification format is needed. R009 already carries the prominent
`均值回归` badge and full strategy name.

## Tests

- Fifteen or more general candidates plus five or more R009 candidates produce
  exactly 10 general and five R009 selections.
- Two qualified R009 candidates allow general candidates to backfill to 15.
- Seven qualified R009 candidates still select only five.
- Six general candidates and eight R009 candidates return at most 11 rather
  than selecting a sixth R009 candidate.
- A confirmed R009 launch ranks before an otherwise stronger setup.
- A tighter, controlled-contraction setup ranks above a loose or extremely
  illiquid R009 setup despite lower generic trend and volume scores.
- R009 observation candidates remain discoverable in every market regime.
- The final candidate list never exceeds 15.
- With no R009 candidates, existing general ordering fills up to 15 unchanged.
- Funnel counters and persisted rank tags match the final list.

## Non-Goals

- No historical or industry-relative valuation percentile in this change.
- No threshold calibration from historical replay in this change.
- No change to R008 ranking or eligibility.
- No live selection, DingTalk, replay, recovery, or historical job during
  deployment.
