# Candidate Discovery And Funnel Design

## Goal

Expose where stocks are removed during candidate selection before changing any
candidate threshold or execution quota.

## Scope

- Keep the existing regime-derived `effective_limit` and current discovery
  behavior unchanged.
- Return a `selection_funnel` summary with the universe size and rejection
  counts for hard safety, no rule match, formal qualification, regime gate,
  and ranking truncation.
- Surface the same summary in the after-close pipeline logs.

## Design

Candidate discovery already builds four mode-specific lists. The new summary
will count hard-safety rejections, rule matches, mode-qualified candidates,
mode quota truncation, and final selections. This keeps the existing
`selection_mode` contract and notification safety rules unchanged.

The discovery loop will count the first applicable reason for each context
that does not reach a candidate list. A separate ranking count will record
otherwise eligible candidates omitted by mode quotas. The returned structure
will be a compact dictionary, so API, jobs, and callers can consume it without
schema migration.

## Guardrails

- No candidate is upgraded to `formal_strategy` by this work.
- No live run, notification, or historical replay is triggered by this work.
- Funnel counts are diagnostic only and never affect ranking.

## Tests

- The result reports deterministic funnel counts for hard safety rejection,
  mode qualification, and ranking truncation.
- Existing candidate and pipeline tests remain green.
