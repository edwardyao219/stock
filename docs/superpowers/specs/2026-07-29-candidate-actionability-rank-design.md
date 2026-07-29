# Candidate Actionability Rank Design

## Goal

Prevent stale trade plans and pre-tier ranks from making rejected candidates
look or behave like actionable candidates.

## Design

For automatic candidates with an ISO date tag, the workspace will only attach
trade plans whose `plan_date` matches that candidate batch date. Manual-only
workspace items keep the existing latest-plan behavior.

After candidate tiers are built, the pipeline will rewrite persisted `rank:`
tags in this order: `core_action`, `sector_watch`, `watch_wait`, then
`risk_reject`. Existing order inside each tier remains stable. The same rank is
already consumed by the workspace, intraday scoring, and paper entry quality,
so no new ranking field is introduced.

## Guardrails

- No selection threshold, strategy score, or plan-generation rule changes.
- No historical plans are deleted or modified.
- No selection, notification, or recovery task is triggered by deployment.

## Tests

- A stale plan cannot override a current risk-reject candidate status.
- Tier application replaces old ranks with actionability-ordered ranks.
- Workspace, pipeline, intraday, and paper-entry tests remain green.
