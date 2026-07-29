# Value Reversion Earnings Sustainability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make R009 reject clearly non-repeatable profit, rank remaining candidates by point-in-time earnings quality and conservative valuation space, and expose the result visibly.

**Architecture:** Keep `FundamentalSnapshot` financial-only, populate it from Tushare structured statements with AkShare field-level fallback, and use the existing `TushareDailyBasic` table for current and historical valuation. Batch-load eight visible reports, calculate sustainability and value range in one focused module, then pass those outputs through the existing R009, persistence, API, web, and DingTalk paths.

**Tech Stack:** Python 3.12, SQLAlchemy 2, MySQL/SQLite, Tushare proxy, AkShare, FastAPI/Pydantic, React/TypeScript, pytest, Ruff, Vitest

---

### Task 1: Make financial ingestion Tushare-first

**Files:**
- Modify: `services/shared/models.py:541-561`
- Modify: `services/shared/sync_schema.py:9-86`
- Create: `services/engine/fundamental/tushare_client.py`
- Modify: `services/engine/fundamental/akshare_client.py:9-233`
- Modify: `services/engine/fundamental/repository.py:14-228`
- Modify: `services/engine/fundamental/sync.py:1-59`
- Modify: `services/engine/research_pool/manual_research.py:100-120`
- Modify: `services/jobs/pipeline.py:290-315`
- Create: `tests/test_fundamental_tushare.py`
- Modify: `tests/test_fundamental_akshare.py`
- Create: `tests/test_sync_schema.py`

- [ ] **Step 1: Write failing Tushare parser tests**

Fake `tushare_proxy_client.query()` for `fina_indicator`, `income`, and
`cashflow`. Require a merged report:

```python
def test_fetch_tushare_financial_snapshots_merges_three_statements(monkeypatch) -> None:
    rows = fetch_tushare_financial_snapshots("002558")
    assert rows[0]["report_date"] == "2026-03-31"
    assert rows[0]["available_date"] == "2026-04-25"
    assert rows[0]["revenue_growth"] == Decimal("2.217")
    assert rows[0]["operating_revenue"] == Decimal("1000")
    assert rows[0]["parent_net_profit"] == Decimal("300")
    assert rows[0]["deducted_parent_net_profit"] == Decimal("270")
    assert rows[0]["operating_cash_flow"] == Decimal("330")
    assert rows[0]["extra_json"]["source"] == "tushare_proxy"
```

Fixture fields are `ann_date`, `f_ann_date`, `end_date`, `q_sales_yoy`,
`q_profit_yoy`, `roe`, `grossprofit_margin`, `netprofit_margin`,
`debt_to_assets`, `profit_dedt`, `total_revenue`, `n_income_attr_p`, and
`n_cashflow_act`. Assert percentage fields divide by 100 and absolute values do
not.

- [ ] **Step 2: Run the test and verify failure**

```bash
.venv/bin/pytest tests/test_fundamental_tushare.py -q
```

Expected: FAIL because the adapter and four model fields do not exist.

- [ ] **Step 3: Add canonical financial fields**

Keep the existing `(symbol, report_date)` unique key and add:

```python
operating_revenue: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
parent_net_profit: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
deducted_parent_net_profit: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
operating_cash_flow: Mapped[Optional[Decimal]] = mapped_column(Numeric(24, 4))
```

Add the fields to `FUNDAMENTAL_FIELDS`. Financial upserts always write
`dividend_yield=None`, `pe_ttm=None`, and `pb=None`, including those columns in
the update list so a formerly mixed report row becomes financial-only.

- [ ] **Step 4: Implement the Tushare adapter**

Reuse the generic proxy:

```python
def fetch_tushare_financial_snapshots(symbol: str) -> list[dict[str, Any]]:
    ts_code = market_symbol(symbol)
    indicators = _query_rows("fina_indicator", {"ts_code": ts_code})
    incomes = _query_rows("income", {"ts_code": ts_code, "report_type": "1"})
    cashflows = _query_rows("cashflow", {"ts_code": ts_code, "report_type": "1"})
    return merge_tushare_financial_rows(symbol, indicators, incomes, cashflows)
```

Merge by `end_date`, choose `f_ann_date` before `ann_date`, retain one
consolidated row per report date, and record field sources in `extra_json`.
Invalid values remain `None`.

- [ ] **Step 5: Extend AkShare as fallback evidence**

Use the installed profit/cash-flow endpoints and merge by `REPORT_DATE`:

```python
def statement_market_symbol(symbol: str) -> str:
    code, exchange = market_symbol(symbol).split(".")
    return f"{exchange}{code}"


def merge_financial_statement_rows(
    indicators: list[dict[str, Any]],
    profits: list[dict[str, Any]],
    cashflows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = {
        str(row["REPORT_DATE"])[:10]: dict(row)
        for row in indicators
        if row.get("REPORT_DATE")
    }
    for statement_rows in (profits, cashflows):
        for row in statement_rows:
            report_date = str(row.get("REPORT_DATE") or "")[:10]
            if report_date in merged:
                merged[report_date].update(row)
    return [merged[key] for key in sorted(merged, reverse=True)]
```

Map `TOTAL_OPERATE_INCOME/TOTALOPERATEREVE`,
`PARENT_NETPROFIT/PARENTNETPROFIT`,
`DEDUCT_PARENT_NETPROFIT/KCFJCXSYJLR`, and `NETCASH_OPERATE`. Either optional
statement request may fail to an empty list without discarding indicator rows.

- [ ] **Step 6: Merge sources with Tushare precedence**

Add:

```python
def merge_financial_sources(
    primary: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    fallback_by_date = {str(row["report_date"]): row for row in fallback}
    merged = []
    for primary_row in primary:
        row = dict(primary_row)
        fallback_row = fallback_by_date.pop(str(row["report_date"]), {})
        for field in FUNDAMENTAL_FIELDS:
            if row.get(field) is None and fallback_row.get(field) is not None:
                row[field] = fallback_row[field]
        merged.append(row)
    merged.extend(fallback_by_date.values())
    return sorted(merged, key=lambda row: str(row["report_date"]), reverse=True)
```

For every report date, retain each non-null Tushare value and fill only its
missing fields from AkShare. Preserve the earlier trustworthy Tushare
announcement date. Set source to `tushare_proxy`, `akshare`, or `merged`.

Rename the application entry point to `sync_fundamentals`; retain the old
function as a compatibility wrapper. If Tushare is unavailable, use AkShare;
if AkShare fails after Tushare succeeds, store Tushare rows. Update pipeline
and manual research callers and remove `include_valuation=True`.

- [ ] **Step 7: Add idempotent legacy cleanup**

Test and implement:

```python
def _conservative_financial_available_date(report_date: date) -> date:
    return {
        3: date(report_date.year, 4, 30),
        6: date(report_date.year, 8, 31),
        9: date(report_date.year, 10, 31),
        12: date(report_date.year + 1, 4, 30),
    }[report_date.month]
```

Schema sync adds the four columns, then updates financial rows whose
`extra_json` source is `akshare.stock_value_em`: clear PE/PB/dividend, set the
conservative date, and replace metadata with
`source=legacy_mixed_snapshot` and
`availability_quality=legacy_conservative_date`. Pure valuation rows remain
untouched and are ignored by financial loaders. Running cleanup twice produces
the same state.

- [ ] **Step 8: Run focused regressions and commit**

```bash
.venv/bin/pytest tests/test_fundamental_tushare.py tests/test_fundamental_akshare.py tests/test_sync_schema.py -q
```

Expected: PASS.

```bash
git add services/shared/models.py services/shared/sync_schema.py services/engine/fundamental/tushare_client.py services/engine/fundamental/akshare_client.py services/engine/fundamental/repository.py services/engine/fundamental/sync.py services/engine/research_pool/manual_research.py services/jobs/pipeline.py tests/test_fundamental_tushare.py tests/test_fundamental_akshare.py tests/test_sync_schema.py
git commit -m "feat: ingest Tushare financial statements"
```

### Task 2: Load point-in-time histories

**Files:**
- Modify: `services/engine/fundamental/repository.py`
- Modify: `services/engine/plans/repository.py:196-271`
- Modify: `services/engine/plans/context.py:430-563`
- Test: `tests/test_fundamental_tushare.py`
- Test: `tests/test_plans_context_tushare.py`

- [ ] **Step 1: Add failing financial-history tests**

Create more than eight reports with announcement dates on both sides of the
requested date:

```python
history = load_fundamental_history_map(
    db, ["002558", "600415"], date(2026, 4, 20), limit=8
)
assert len(history["002558"]) == 8
assert all(item["available_date"] <= "2026-04-20" for item in history["002558"])
assert "600415" not in history
```

Add `TushareDailyBasic` rows inside and outside three years. Assert
`load_valuation_pe_history_map` returns only positive, visible Tushare PE. Add
a legacy `FundamentalSnapshot.pe_ttm` value and assert it is ignored.

- [ ] **Step 2: Verify loaders are missing**

```bash
.venv/bin/pytest tests/test_fundamental_tushare.py -k 'history_map' -q
```

Expected: FAIL on missing imports.

- [ ] **Step 3: Implement batched loaders**

Implement `load_fundamental_history_map(db, symbols, as_of_date, *, limit=8)`
returning `dict[str, list[dict[str, Any]]]`, and
`load_valuation_pe_history_map(db, symbols, as_of_date, *, years=3)` returning
`dict[str, list[float]]`.

Financial history uses the financial-presence predicate and
`available_date <= as_of_date`, then groups and slices one ordered query.
Valuation history queries `TushareDailyBasic`, maps symbols with
`market_symbol`, requires positive PE, and bounds `trade_date` to the requested
three-year window.

- [ ] **Step 4: Merge history into strategy context**

`load_fundamental_context_map` and the single-symbol loader add
`fundamental_history` and stop merging legacy PE/PB from
`FundamentalSnapshot`. Current PE/PB continues to come from the existing
exact-date `TushareDailyBasic` context. Valuation history stays out of general
contexts and is loaded only for R009 matches in Task 4.

- [ ] **Step 5: Run context regressions and commit**

```bash
.venv/bin/pytest tests/test_fundamental_tushare.py tests/test_fundamental_akshare.py tests/test_plans_context_tushare.py -q
```

Expected: PASS, including existing query-count assertions.

```bash
git add services/engine/fundamental/repository.py services/engine/plans/repository.py services/engine/plans/context.py tests/test_fundamental_tushare.py tests/test_fundamental_akshare.py tests/test_plans_context_tushare.py
git commit -m "feat: load point-in-time financial history"
```

### Task 3: Score earnings sustainability and valuation space

**Files:**
- Create: `services/engine/fundamental/sustainability.py`
- Create: `tests/test_earnings_sustainability.py`
- Modify: `services/engine/plans/context.py:542-549`

- [ ] **Step 1: Write failing sustainability tests**

```python
def test_sustained_operating_earnings_grade_as_sustainable() -> None:
    result = assess_earnings_sustainability(
        giant_network_like_history(), analysis_framework="tech_growth_cycle"
    )
    assert result.grade == "sustainable"
    assert result.score >= 70
    assert result.earnings_quality_ratio == pytest.approx(0.9)


def test_positive_reported_profit_with_negative_deducted_profit_is_unsustainable() -> None:
    history = giant_network_like_history()
    history[0]["deducted_parent_net_profit"] = -1
    result = assess_earnings_sustainability(history)
    assert result.grade == "unsustainable"


def test_missing_deducted_or_annual_cash_evidence_stays_pending() -> None:
    assert assess_earnings_sustainability(incomplete_history()).grade == "pending"
```

Also test two deducted ratios below 0.50, two unsupported -30% profit declines,
two annual cash ratios below 0.30, one negative interim cash flow, banking cash
exemption, and the exact 70-point boundary.

- [ ] **Step 2: Verify tests fail**

```bash
.venv/bin/pytest tests/test_earnings_sustainability.py -q
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the immutable assessment**

Create frozen `EarningsSustainabilityAssessment` with `score: float`,
`grade: str`, `reasons: list[str]`, and
`earnings_quality_ratio: float | None`. Implement
`assess_earnings_sustainability(history, *, analysis_framework=None)` returning
that type.

Implement the four component formulas and hard conditions exactly as specified.
Invalid values are missing evidence; the pure function does not catch broad
exceptions.

- [ ] **Step 4: Write failing valuation tests**

```python
def test_conservative_value_range_caps_historical_pe() -> None:
    result = estimate_value_reversion_range(
        current_close=10,
        current_pe=10,
        earnings_quality_ratio=0.9,
        historical_pe=[*range(10, 40)] * 3 + [999],
    )
    assert result.fair_pe_low <= 25
    assert result.fair_pe_high <= 30
    assert result.fair_value_low == pytest.approx(22.5)
    assert result.conservative_upside_pct == pytest.approx(1.25)
    assert result.label == "near_double_valuation_space"


def test_value_range_requires_sixty_positive_observations() -> None:
    assert estimate_value_reversion_range(
        current_close=10, current_pe=10, earnings_quality_ratio=0.9,
        historical_pe=[10] * 59,
    ) is None
```

- [ ] **Step 5: Implement bounded valuation and context fallback**

Create immutable `ValueReversionRange`. Use `statistics.median` plus a linear
percentile helper, 5% trimming, 25/30 PE caps, quality ratio bounds 0-1, the
60-observation minimum, and the 80% label.

After normal fundamental assessment, call the sustainability evaluator and
merge `to_context()`. Catch only `TypeError`, `ValueError`, and
`ArithmeticError` per symbol and return `pending_earnings_assessment` with a
concise reason.

- [ ] **Step 6: Run regressions and commit**

```bash
.venv/bin/pytest tests/test_earnings_sustainability.py tests/test_plans_context_tushare.py -q
```

Expected: PASS.

```bash
git add services/engine/fundamental/sustainability.py services/engine/plans/context.py tests/test_earnings_sustainability.py tests/test_plans_context_tushare.py
git commit -m "feat: assess earnings sustainability"
```

### Task 4: Apply sustainability and valuation to R009

**Files:**
- Modify: `services/engine/rules/seed_rules.py:266-366`
- Modify: `services/engine/research_pool/candidates.py:232-321,1210-1259,1803-1868,2336-2383,2678-2776,2960-3535`
- Modify: `services/engine/fundamental/repository.py`
- Test: `tests/test_trade_plan_generator.py`
- Test: `tests/test_next_session_candidates.py`

- [ ] **Step 1: Add failing R009 eligibility and rank tests**

Require `earnings_sustainability_grade != "unsustainable"`. Prove
unsustainable cannot match, pending remains eligible, and candidates at the
same technical stage order as sustainable, general, pending. Preserve the
existing launch-before-setup assertion.

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/test_trade_plan_generator.py tests/test_next_session_candidates.py -k 'value_reversion' -q
```

- [ ] **Step 3: Add eligibility and rank tuple**

```python
EARNINGS_GRADE_RANK = {
    "unsustainable": 0, "pending": 1, "general": 2, "sustainable": 3,
}
```

Rank by launch, grade, sustainability score, conservative upside, setup
quality, sector diversity, and action rank.

- [ ] **Step 4: Calculate valuation only for R009 matches**

Precompute rule matches, collect eligible R009 symbols, batch-load their
Tushare PE histories once with the effective feature date, and merge the
returned range's `to_context()` output. Skip the query when no R009
matches. Missing ranges use `valuation_space_label="pending"` and no prices.

- [ ] **Step 5: Extend candidate and persistence contracts**

Add optional candidate fields for sustainability score/grade/reasons, fair
values, upside percentages, and label. Insert Chinese grade and valuation
reasons for R009. Persist and replace these tag prefixes:

```text
earnings_grade: earnings_score: earnings_reason:
fair_value_low: fair_value_high:
valuation_upside_low: valuation_upside_high: valuation_space:
```

- [ ] **Step 6: Run regressions and commit**

```bash
.venv/bin/pytest tests/test_trade_plan_generator.py tests/test_next_session_candidates.py -q
```

```bash
git add services/engine/rules/seed_rules.py services/engine/research_pool/candidates.py services/engine/fundamental/repository.py tests/test_trade_plan_generator.py tests/test_next_session_candidates.py
git commit -m "feat: rank R009 by sustainable earnings"
```

### Task 5: Expose prominent labels

**Files:**
- Modify: `services/engine/workspace/repository.py:130-175,638-735,980-1080`
- Modify: `apps/api/app/routers/workspace.py:148-181,529-576,693-735`
- Modify: `services/engine/intraday/candidates.py:45-75,1745-1788`
- Modify: `services/notifications/dispatcher.py:1380-1463`
- Modify: `apps/web/src/api.ts:591-639,730-771,1700-1730`
- Modify: `apps/web/src/App.tsx:420-470,2240-2303,3030-3080`
- Modify: `apps/web/src/styles.css:921-980`
- Test: `tests/test_workspace_api.py`
- Test: `tests/test_intraday_candidates.py`
- Test: `tests/test_notifications.py`
- Test: `apps/web/src/stockTracking.test.ts`

- [ ] **Step 1: Add failing backend contract tests**

Persist sustainability and valuation tags, then assert workspace, intraday,
and notification payloads contain:

```text
财报：盈利可持续 / 评分 82.0
估值：接近翻倍估值空间 / 保守空间 +85.0%
```

Pending displays `财报持续性待确认` and no invented fair range.

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/test_workspace_api.py tests/test_intraday_candidates.py tests/test_notifications.py -k 'earnings or valuation_space' -q
```

- [ ] **Step 3: Parse tags into API contracts**

Use existing `_tag_text`, `_tag_texts`, and `_tag_number` once in workspace and
intraday repositories. Add nullable score, grade, reasons, fair values, upside,
and label to repository dataclasses and Pydantic responses. Older rows stay
valid.

- [ ] **Step 4: Add DingTalk lines**

After the existing rule line, append the translated grade/score and optional
valuation-space/upside line. Reuse the existing message and dispatch; add no
second notification.

- [ ] **Step 5: Add web labels and tests**

Extend TypeScript types and fixture defaults. Add pure label helpers and assert
the candidate row/detail render `盈利可持续` and a separate
`接近翻倍估值空间` pill. Use compact green and amber variants of the existing
strategy pill; pending uses neutral styling. Add no page, card, or modal.

- [ ] **Step 6: Run presentation regressions and commit**

```bash
.venv/bin/pytest tests/test_workspace_api.py tests/test_intraday_candidates.py tests/test_notifications.py -q
```

```bash
cd apps/web && npm test -- --run
```

```bash
git add services/engine/workspace/repository.py apps/api/app/routers/workspace.py services/engine/intraday/candidates.py services/notifications/dispatcher.py apps/web/src/api.ts apps/web/src/App.tsx apps/web/src/styles.css tests/test_workspace_api.py tests/test_intraday_candidates.py tests/test_notifications.py apps/web/src/stockTracking.test.ts
git commit -m "feat: display R009 earnings quality"
```

### Task 6: Invalidate caches and verify the system

**Files:**
- Modify: `services/engine/backtest/walk_forward.py:40`
- Modify: `apps/api/app/routers/rules.py:45`
- Modify: `services/engine/features/market_regime_repository.py:83`
- Modify: `services/engine/research_signal_ledger.py:25`
- Test: `tests/test_walk_forward_replay.py`
- Test: `tests/test_strategy_fit_api.py`
- Test: `tests/test_market_regime.py`
- Test: `tests/test_research_signal_ledger.py`

- [ ] **Step 1: Add failing cache and future-report tests**

```python
assert walk_forward.CANDIDATE_DISCOVERY_CACHE_VERSION == "candidate-v7-earnings-quality"
assert rules.CANDIDATE_REPLAY_EFFECT_CACHE_VERSION == "candidate-replay-effect-v6"
```

Add a walk-forward assertion that a report announced after the replay date is
absent while an earlier report produces the expected grade.

- [ ] **Step 2: Verify failure**

```bash
.venv/bin/pytest tests/test_walk_forward_replay.py tests/test_strategy_fit_api.py tests/test_market_regime.py tests/test_research_signal_ledger.py -k 'cache_version or future_report' -q
```

- [ ] **Step 3: Bump coupled cache readers**

Use `candidate-v7-earnings-quality` in walk-forward discovery, market-regime
backfill, and research-signal history. Use `candidate-replay-effect-v6` in the
API. Never interpret v6 discovery as pending-grade evidence.

- [ ] **Step 4: Run focused and complete verification**

```bash
.venv/bin/pytest tests/test_walk_forward_replay.py tests/test_strategy_fit_api.py tests/test_market_regime.py tests/test_research_signal_ledger.py -q
```

```bash
.venv/bin/ruff check services apps/api tests
.venv/bin/pytest -q
```

```bash
cd apps/web && npm test -- --run && npm run build
```

```bash
git diff --check
```

Expected: all commands exit 0 and `git diff --check` prints nothing.

- [ ] **Step 5: Commit and push main**

```bash
git add services/engine/backtest/walk_forward.py apps/api/app/routers/rules.py services/engine/features/market_regime_repository.py services/engine/research_signal_ledger.py tests/test_walk_forward_replay.py tests/test_strategy_fit_api.py tests/test_market_regime.py tests/test_research_signal_ledger.py docs/superpowers/plans/2026-07-29-value-reversion-earnings-sustainability.md
git commit -m "feat: invalidate earnings-quality replay caches"
git push origin main
```

Do not run `services.shared.sync_schema`, Tushare/AkShare financial sync, live
selection, candidate recovery, historical replay, or any DingTalk dispatch
command during implementation verification.
