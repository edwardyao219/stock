# Value Reversion Earnings Sustainability Design

## Goal

Strengthen `R009 [均值回归] 价值蓄势` so it distinguishes repeatable operating
earnings from reported profit driven by one-off items. Clearly unsustainable
earnings block R009. Otherwise, earnings quality changes ranking and is shown
prominently without excluding stocks merely because financial evidence is
incomplete.

The change also estimates a conservative value-reversion range from normalized
earnings and the stock's own historical valuation. The range is research
evidence, not a price target or return promise.

Keep the existing R009 technical setup, launch confirmation, market-independent
discovery, and 10-general-plus-5-R009 quota.

## Scope

This change includes:

- making Tushare structured statements the primary financial source and
  AkShare the field-level fallback;
- removing daily valuation ownership from the financial snapshot path so a
  quarter-end valuation cannot overwrite a report;
- retaining the latest eight reports that were public as of the selection date;
- ingesting the minimum additional earnings-quality evidence;
- producing an explainable sustainability score and grade;
- using the grade as an R009 exclusion and ranking factor;
- estimating a bounded, stock-relative value range;
- exposing prominent sustainability and valuation-space labels in candidate
  surfaces and DingTalk reasons;
- preserving point-in-time behavior in candidate replay.

This change does not build a general three-statement analysis platform, add
industry-relative valuation, promise that any stock will double, or
automatically run financial sync, selection, replay, or notification jobs
during deployment.

## Financial And Valuation Ownership

`FundamentalSnapshot` currently uses `(symbol, report_date)` as its unique key.
That allows a daily valuation written on a quarter-end date to collide with a
financial report for the same date. The valuation upsert can then replace the
financial `available_date` and `extra_json`, making an unpublished report look
available at quarter end and introducing look-ahead bias.

Keep `FundamentalSnapshot` as the canonical quarterly financial table and stop
writing AkShare daily valuations into it. Tushare `daily_basic`, already stored
in `TushareDailyBasic`, is the canonical source for current and historical PE,
PB, market capitalization, and turnover context.

- Financial rows use the report's actual announcement date as
  `available_date`.
- Strategy context receives current PE/PB from the existing exact-date
  `TushareDailyBasic` loader.
- Three-year valuation history reads positive PE observations directly from
  `TushareDailyBasic`.
- Legacy pure-valuation rows may remain physically present in
  `fundamental_snapshots`, but financial loaders ignore rows without financial
  evidence and no application path writes new valuation rows there.
- Financial sync explicitly clears legacy PE/PB/dividend values on a report
  row so a formerly mixed row becomes financial-only.

Add these nullable numeric fields to financial snapshots:

- `operating_revenue`
- `parent_net_profit`
- `deducted_parent_net_profit`
- `operating_cash_flow`

## Dual-Source Financial Ingestion

Use the existing generic Tushare proxy client to request, by symbol:

- `fina_indicator` for announcement date, deducted parent profit, YoY growth,
  ROE, margins, and debt ratio;
- `income` for operating revenue and parent net profit;
- `cashflow` for operating cash flow.

Tushare is the primary source for each canonical field. The existing AkShare
financial-analysis endpoint plus AkShare profit and cash-flow statement
endpoints fill only fields or report periods missing from Tushare. A fallback
value must never replace a non-null Tushare value or an earlier trustworthy
Tushare announcement date.

Every stored row records `source=tushare_proxy`, `source=akshare`, or
`source=merged`, plus field-level source names in `extra_json`. Absent or
invalid source values remain `None`; neither adapter may synthesize absolute
profit or cash values from growth percentages.

## Existing-Row Migration

Schema synchronization performs a deterministic, idempotent cleanup:

1. Add the four new nullable financial columns.
2. Leave pure legacy valuation rows unchanged; current code no longer reads or
   writes them.
3. A row containing both financial evidence and AkShare valuation metadata is
   treated as a polluted financial row. Clear PE, PB, and dividend yield.
4. If that mixed row has lost its real announcement date, the financial row
   uses the statutory disclosure deadline for that report period: April 30 for
   first-quarter reports, August 31 for half-year reports, October 31 for
   third-quarter reports, and April 30 of the following year for annual
   reports. It records `availability_quality=legacy_conservative_date`. This
   may make evidence available later than reality but must never make it
   available earlier.
5. A later normal Tushare or AkShare financial sync replaces the conservative
   date and metadata with the source announcement date.

The migration does not call AkShare or any other external service.

## Point-In-Time Financial History

Add a batched repository loader that returns, for each requested symbol, at
most the latest eight rows containing financial evidence and satisfying
`available_date <= as_of_date`. Order reports newest first by `report_date`;
availability controls whether a report may be seen, while report date controls
financial sequence. Legacy valuation-only rows are excluded by the existing
financial-presence predicate.

Candidate context retains the existing latest financial keys and adds a compact
`fundamental_history` list containing only the fields required by the
sustainability evaluator. Replay and live discovery use the same loader and
the feature date as `as_of_date`.

## Sustainability Assessment

Produce the following context values:

- `earnings_sustainability_score`: `0-100`
- `earnings_sustainability_grade`: `sustainable`, `general`, `pending`, or
  `unsustainable`
- `earnings_sustainability_reasons`: ordered human-readable evidence
- `earnings_quality_ratio`: the usable deducted-profit ratio, when available

The score has four transparent components:

| Component | Weight | Evidence |
| --- | ---: | --- |
| Growth continuity | 35 | Positive revenue and parent-profit YoY growth across the latest four reports, with consecutive deterioration penalized |
| Deducted-profit quality | 30 | Deducted parent profit divided by parent profit across the latest two usable reports |
| Cash conversion | 20 | Operating cash flow divided by parent profit, primarily across the latest two annual reports |
| Operating stability | 15 | Annualized ROE and gross-margin stability across comparable available reports |

Each component returns its weighted score plus reasons. A missing component
contributes half of its weight to the displayed raw score but sets an evidence
coverage flag. This neutral treatment prevents missing data from behaving like
either strong or weak evidence.

Use these fixed component boundaries, clamping every component to its stated
weight:

- Growth continuity uses up to the latest four reports. Revenue contributes
  `15 * positive_revenue_growth_count / usable_revenue_growth_count`; parent
  profit contributes
  `20 * positive_profit_growth_count / usable_profit_growth_count`. A side with
  fewer than three usable observations is missing. Subtract five points when
  the latest three usable profit-growth observations have deteriorated in
  sequence.
- Deducted-profit quality uses the median of the latest two positive-parent-
  profit ratios. A median of at least `0.90`, `0.70`, or `0.50` contributes
  30, 24, or 15 points respectively; a lower positive median contributes zero.
  Fewer than two usable ratios makes this component missing.
- Cash conversion uses the median of the latest two positive-parent-profit
  annual-report ratios. A median of at least `1.00`, `0.70`, or `0.30`
  contributes 20, 15, or 8 points respectively; a lower median contributes
  zero. Fewer than two usable annual ratios makes this component missing.
- Operating stability uses up to four reports. Median annualized ROE of at
  least `15%`, `10%`, or `5%` contributes 8, 6, or 3 points. A gross-margin
  spread no greater than 5 or 10 percentage points contributes 7 or 4 points.
  Each side with fewer than three usable observations contributes half of its
  own sub-weight and marks that evidence side missing.

Apply these hard, explainable `unsustainable` conditions:

- the latest parent profit is positive but latest deducted parent profit is
  non-positive;
- deducted profit is below 50% of parent profit in both of the latest two
  usable reports;
- profit growth is at most `-30%` in two consecutive reports and revenue
  growth is non-positive in both reports;
- for a non-financial company, cash conversion is below `0.30` in both of the
  latest two usable annual reports.

A single negative interim cash-flow observation never hard-blocks R009.
Companies using the existing `banking_compound` analysis framework do not use
the ordinary-company cash-conversion condition.

When no hard condition fires:

- `pending`: fewer than four visible reports, or deducted-profit or annual
  cash-conversion evidence is unavailable;
- `sustainable`: required evidence is available and score is at least `70`;
- `general`: required evidence is available and score is below `70`.

The grade precedes the numeric score in the rank key, so a high neutral-default
`pending` score cannot outrank a `general` candidate.

## R009 Eligibility And Ranking

Keep all existing R009 valuation, pullback, consolidation, contraction, and
launch conditions. Add only this eligibility condition:

`earnings_sustainability_grade != "unsustainable"`

Missing history therefore produces `pending` and remains eligible. The R009
reserved bucket stays capped at five and general candidates still backfill
unused R009 capacity.

Within the R009 bucket, rank by:

1. confirmed volume launch before contracted setup;
2. sustainability grade (`sustainable`, `general`, `pending`);
3. sustainability score within the same grade;
4. conservative valuation upside when available;
5. existing R009 setup-quality score;
6. existing sector-diversity preference and action rank.

This ordering preserves actionability while improving the fundamental quality
of candidates at the same technical stage.

## Conservative Valuation Range

Calculate a value range only when current close, positive current PE, a usable
deducted-profit ratio, and enough historical valuation observations exist.

1. Load positive `TushareDailyBasic.pe_ttm` observations from the three years
   ending on the selection date. Require at least 60 observations.
2. Remove non-positive values and trim the outer 5% on each side before taking
   the median and 75th percentile.
3. Derive reported TTM EPS as `current_close / current_pe`.
4. Derive normalized EPS as reported TTM EPS multiplied by the deducted-profit
   ratio, bounded to `0.00-1.00`. This prevents one-off income from increasing
   normalized earnings and does not inflate a weak positive ratio.
5. Set the lower fair PE to the trimmed historical median capped at `25`.
6. Set the upper fair PE to the trimmed historical 75th percentile capped at
   `30`, but never below the lower fair PE.
7. Multiply normalized EPS by the lower and upper fair PE values to produce the
   range and relative upside.

The caps prevent a stock's own historical bubble from becoming the valuation
anchor. If the conservative lower bound is at least 80% above current close,
add `near_double_valuation_space` and display `接近翻倍估值空间`. The accompanying
reason must state the calculated lower-bound percentage and that it is an
earnings-and-valuation reversion estimate, not a forecast.

If any required evidence is missing, omit the range and display
`估值空间待确认`; do not substitute a generic industry multiple.

## Candidate Contract And Presentation

Carry these fields through the next-session candidate, persisted research-pool
tags/evidence, workspace API, and web API:

- sustainability score, grade, and reasons;
- fair-value lower and upper estimates;
- conservative and upper upside percentages;
- valuation-space label.

Display one prominent grade label:

- `盈利可持续`
- `盈利持续性一般`
- `财报持续性待确认`

An unsustainable stock is excluded from R009, so the R009 candidate UI does not
need an unsustainable badge. Candidate details show the component reasons and
the valuation assumptions. When present, `接近翻倍估值空间` is a separate
high-contrast label.

DingTalk reuses the candidate strategy and reason lines. It includes the grade
label and any valuation-space label, without adding a second notification or a
buy recommendation.

## Failure Behavior

- Missing source columns, incomplete histories, and invalid numeric values
  produce absent evidence rather than an exception.
- An evaluator error is isolated per symbol, records a concise reason, and
  defaults that symbol to `pending`; it must not fail the whole selection run.
- Invalid ratios and extreme or insufficient PE histories do not produce a
  valuation range.
- No single interim cash-flow result hard-blocks a candidate.
- Financial-sector contexts remain exempt from ordinary-company cash coverage.
- Live selection and replay share the same point-in-time functions so fallback
  behavior cannot diverge.

## Replay And Cache Compatibility

Walk-forward discovery loads financial reports and valuation observations only
through the replay date. It must never use the current sustainability grade or
current valuation history for an older replay date.

Bump every serialized candidate-discovery or replay cache version affected by
the expanded context and candidate contract. Older cache payloads must be
treated as stale rather than silently interpreted as `pending` evidence.

Do not run historical replay as part of implementation or deployment.

## Tests

Add focused tests proving:

- Tushare financial parsing maps the three statement payloads, four new values,
  and the source announcement date;
- AkShare fills a missing field without replacing a non-null Tushare field;
- current and historical valuation reads `TushareDailyBasic`, not legacy
  valuation values in `FundamentalSnapshot`;
- the legacy mixed-row cleanup is idempotent, clears valuation fields, and uses
  a conservative date;
- the batch loader returns at most eight reports and excludes reports not yet
  announced as of the requested date;
- a Giant-Network-like history with sustained profit, strong deducted-profit
  coverage, and cash support grades as sustainable;
- positive reported profit with non-positive deducted profit grades as
  unsustainable and cannot match R009;
- two periods of weak deducted-profit coverage or severe unsupported decline
  trigger the documented hard conditions;
- one negative interim cash-flow period does not hard-block a candidate;
- incomplete histories grade as pending and remain R009-eligible;
- a banking context ignores ordinary cash-conversion hard conditions;
- R009 ranking keeps launches first, then prefers stronger sustainability at
  the same technical stage, and preserves the 10-plus-5 quota;
- the three-year PE calculation trims outliers, applies caps, and emits the
  near-double label only when conservative upside is at least 80%;
- insufficient valuation history omits the range;
- candidate API, web, persistence, and DingTalk reasons expose the expected
  labels;
- historical replay cannot observe a future report or valuation point;
- existing R008, R009 technical, intraday lifecycle, candidate, plan,
  notification, and replay tests remain green.

## Deployment Guardrails

Implementation may update schema and application code, but it must not trigger
live selection, financial backfill, candidate recovery, historical replay, or
DingTalk notification. A later explicitly scheduled financial sync can replace
conservative legacy dates with source announcement dates before production
calibration.
