# Startup State Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an auditable four-state startup lifecycle from after-close screening through intraday confirmation/invalidation, paper-plan gating, notifications, Web display, and 1/3/5-day outcomes.

**Architecture:** Add one pure startup-state resolver and make after-close and intraday callers supply evidence to it. Reuse `ResearchSignalLedger` as the event store, existing `TradePlan.status` for invalidated unexecuted plans, and the current notification dispatcher; no new database table or dependency is required.

**Tech Stack:** Python 3.12, SQLAlchemy, FastAPI/Pydantic, pytest, React 19, TypeScript, Vite.

---

## File Map

- Create `services/engine/intraday/startup_state.py`: canonical keys, labels, evidence/result dataclasses, pure transition resolver.
- Create `tests/test_startup_state.py`: resolver contract and edge cases.
- Modify `services/engine/research_pool/candidates.py`: after-close states, candidate field, persisted state tag.
- Modify `services/engine/intraday/candidates.py`: canonical intraday state derived after all evidence and final tiering.
- Modify `services/engine/research_signal_ledger.py`: latest-state lookup, lifecycle event builder, state-level deduplication.
- Modify `services/jobs/tasks.py`: pass sustained sectors into scheduled discovery, persist transitions, cancel invalid plans, notify after commit.
- Modify `services/engine/plans/repository.py`: cancel planned rows for invalidated startup candidates.
- Modify `services/engine/paper/realtime.py`: block startup-governed entries until confirmation.
- Modify `services/notifications/dispatcher.py`: format and dispatch confirmation/invalidation events only.
- Modify `services/engine/intraday/outcomes.py`: consume persisted lifecycle events and aggregate state outcomes/conversions.
- Modify `services/engine/tracking/startup.py`: read canonical state tags and four-state evidence.
- Modify `apps/api/app/routers/workspace.py`: expose lifecycle evidence and conversion metrics.
- Modify `apps/web/src/api.ts`: canonical lifecycle response types.
- Modify `apps/web/src/App.tsx`: render state, evidence, invalidation, and next conditions without label inference.
- Modify focused backend and frontend tests named below.

### Task 1: Canonical Pure State Resolver

**Files:**
- Create: `services/engine/intraday/startup_state.py`
- Create: `tests/test_startup_state.py`

- [ ] **Step 1: Write failing resolver tests**

```python
from datetime import date, datetime

from services.engine.intraday.startup_state import StartupEvidence, resolve_startup_state


def evidence(**overrides):
    values = {
        "trade_date": date(2026, 7, 22),
        "as_of": datetime(2026, 7, 22, 10, 30),
        "individual_supportive": True,
        "volume_confirmed": True,
        "sector_sustained": True,
        "sector_strength_holding": False,
        "formal_eligible": True,
        "market_risk_off": False,
        "hard_risk_reasons": (),
    }
    values.update(overrides)
    return StartupEvidence(**values)


def test_confirmation_requires_all_three_evidence_groups():
    assert resolve_startup_state("probing", evidence()).state == "confirmed"
    assert resolve_startup_state("probing", evidence(sector_sustained=False)).state == "probing"
    assert resolve_startup_state("probing", evidence(volume_confirmed=False)).state == "probing"
    assert resolve_startup_state("probing", evidence(market_risk_off=True)).state == "invalidated"


def test_invalidation_is_terminal_for_same_trade_date():
    result = resolve_startup_state("invalidated", evidence())
    assert result.state == "invalidated"
    assert result.transitioned is False


def test_missing_sector_before_1030_does_not_invalidate():
    result = resolve_startup_state(
        "probing",
        evidence(as_of=datetime(2026, 7, 22, 9, 45), sector_sustained=False),
    )
    assert result.state == "probing"
    assert "等待10:30板块持续扩散确认" in result.next_conditions
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/pytest -q tests/test_startup_state.py`

Expected: collection fails because `services.engine.intraday.startup_state` does not exist.

- [ ] **Step 3: Implement the minimal resolver**

```python
from dataclasses import dataclass
from datetime import date, datetime, time

STARTUP_LABELS = {
    "preheat": "启动预热",
    "probing": "启动试探",
    "confirmed": "启动确认",
    "invalidated": "启动失效",
}


@dataclass(frozen=True)
class StartupEvidence:
    trade_date: date
    as_of: datetime
    individual_supportive: bool
    volume_confirmed: bool
    sector_sustained: bool
    sector_strength_holding: bool
    formal_eligible: bool
    market_risk_off: bool
    hard_risk_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class StartupDecision:
    state: str
    label: str
    confirmation_evidence: tuple[str, ...]
    invalidation_reasons: tuple[str, ...]
    next_conditions: tuple[str, ...]
    transitioned: bool


def resolve_startup_state(prior_state: str | None, evidence: StartupEvidence) -> StartupDecision:
    prior = prior_state if prior_state in STARTUP_LABELS else "preheat"
    if prior == "invalidated":
        state = "invalidated"
        invalidation = evidence.hard_risk_reasons
    elif evidence.market_risk_off or evidence.hard_risk_reasons:
        state = "invalidated"
        invalidation = evidence.hard_risk_reasons or ("市场风险阀门关闭",)
    elif (
        evidence.as_of.time() >= time(10, 30)
        and evidence.sector_sustained
        and evidence.individual_supportive
        and (evidence.volume_confirmed or evidence.sector_strength_holding)
        and evidence.formal_eligible
    ):
        state = "confirmed"
        invalidation = ()
    else:
        state = "probing" if prior == "probing" or evidence.individual_supportive else "preheat"
        invalidation = ()
    confirmation = (
        ("板块持续扩散", "个股量价承接", "市场风险阀门允许")
        if state == "confirmed"
        else ()
    )
    next_conditions: list[str] = []
    if state not in {"confirmed", "invalidated"}:
        if evidence.as_of.time() < time(10, 30):
            next_conditions.append("等待10:30板块持续扩散确认")
        elif not evidence.sector_sustained:
            next_conditions.append("等待板块持续扩散")
        if not evidence.individual_supportive:
            next_conditions.append("等待个股价格承接")
        if not (evidence.volume_confirmed or evidence.sector_strength_holding):
            next_conditions.append("等待量能或板块强度确认")
        if not evidence.formal_eligible:
            next_conditions.append("等待盘中风险条件解除")
    return StartupDecision(
        state=state,
        label=STARTUP_LABELS[state],
        confirmation_evidence=confirmation,
        invalidation_reasons=invalidation,
        next_conditions=tuple(next_conditions),
        transitioned=state != prior,
    )
```

- [ ] **Step 4: Run resolver tests and verify GREEN**

Run: `.venv/bin/pytest -q tests/test_startup_state.py`

Expected: all tests pass.

- [ ] **Step 5: Commit the resolver**

```bash
git add services/engine/intraday/startup_state.py tests/test_startup_state.py
git commit -m "feat: define startup state transitions"
```

### Task 2: After-Close And Intraday Integration

**Files:**
- Modify: `services/engine/research_pool/candidates.py`
- Modify: `services/engine/intraday/candidates.py`
- Modify: `tests/test_next_session_candidates.py`
- Modify: `tests/test_intraday_candidates.py`

- [ ] **Step 1: Write failing after-close and intraday contract tests**

Add assertions that after-close startup candidates contain `startup_signal_state` in `{"preheat", "probing"}`, never `confirmed`, and persist `startup_state:<state>`. Update intraday fixtures to expect canonical `startup_stage` values and add one test where individual strength without sustained sector remains `probing`.

```python
assert candidate["startup_signal_state"] == "probing"
assert candidate["startup_signal_label"] == "启动试探"
assert "startup_state:probing" in stock_tags["002558"]

assert live["startup_stage"] == "probing"
assert live["selection_tier"] == "watch"
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/pytest -q tests/test_next_session_candidates.py::test_discover_next_session_candidates_marks_t_minus_one_startup_preheat tests/test_intraday_candidates.py -k startup`

Expected: failures for missing canonical state fields and old labels/stages.

- [ ] **Step 3: Restrict after-close classification**

Change `_startup_signal_profile()` to return `state`, `score`, `label`, and `reasons`. Use only:

```python
state = "probing" if score >= 70.0 else "preheat"
label = STARTUP_LABELS[state]
```

Add `startup_signal_state` to `NextSessionCandidate`, serialized candidate payloads, and tags:

```python
if item.startup_signal_state:
    tags.append(f"startup_state:{item.startup_signal_state}")
```

Remove the uncommitted after-close branches that produce confirmation or invalidation.

- [ ] **Step 4: Resolve intraday state after final tiering**

Keep raw individual price/volume scoring local, but replace old display stages with `preheat`/`probing`. After market risks, sustained sectors, and final tier are known, construct `StartupEvidence` and call `resolve_startup_state()` exactly once. Populate:

```python
startup_stage=decision.state
startup_label=decision.label
startup_reason="；".join(
    decision.invalidation_reasons
    or decision.confirmation_evidence
    or decision.next_conditions
)
```

Add `startup_tracked` to the candidate payload when tags contain `candidate_pool:startup_preheat`. Do not persist or notify candidates for which it is false.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `.venv/bin/pytest -q tests/test_startup_state.py tests/test_next_session_candidates.py tests/test_intraday_candidates.py`

Expected: all tests pass.

- [ ] **Step 6: Commit integration**

```bash
git add services/engine/research_pool/candidates.py services/engine/intraday/candidates.py tests/test_next_session_candidates.py tests/test_intraday_candidates.py
git commit -m "feat: unify startup candidate states"
```

### Task 3: Persist Transitions And Fix Scheduled Evidence

**Files:**
- Modify: `services/engine/research_signal_ledger.py`
- Modify: `services/jobs/tasks.py`
- Modify: `tests/test_research_signal_ledger.py`
- Modify: `tests/test_jobs_pipeline.py`

- [ ] **Step 1: Write failing event deduplication tests**

```python
created = record_startup_state_signals(db, [confirmed_event, confirmed_event_retry])
db.commit()

assert [item["signal_type"] for item in created] == ["startup_confirmed"]
assert db.scalar(select(func.count()).select_from(ResearchSignalLedger)) == 1
```

Add a scheduled-task test that patches `discover_intraday_candidates` and asserts its 10:30 call receives the snapshot's confirmed-sector set before candidate events are built.

- [ ] **Step 2: Run event/task tests and verify RED**

Run: `.venv/bin/pytest -q tests/test_research_signal_ledger.py -k startup tests/test_jobs_pipeline.py -k intraday_market_turn`

Expected: missing `record_startup_state_signals` and missing sustained-sector argument.

- [ ] **Step 3: Add state-event lookup and recording**

Implement:

```python
STARTUP_EVENT_SOURCE = "startup_state"


def latest_startup_states(db, *, signal_date, symbols, as_of=None) -> dict[str, str]:
    if not symbols:
        return {}
    stmt = (
        select(ResearchSignalLedger)
        .where(ResearchSignalLedger.source == STARTUP_EVENT_SOURCE)
        .where(ResearchSignalLedger.signal_date == signal_date)
        .where(ResearchSignalLedger.symbol.in_(symbols))
        .order_by(ResearchSignalLedger.signal_time)
    )
    if as_of is not None:
        stmt = stmt.where(ResearchSignalLedger.signal_time <= _plain_datetime(as_of))
    states: dict[str, str] = {}
    for row in db.execute(stmt).scalars():
        state = row.signal_type.removeprefix("startup_")
        if state in {"preheat", "probing", "confirmed", "invalidated"}:
            states[row.symbol] = state
    return states


def record_startup_state_signals(db, signals) -> list[dict[str, Any]]:
    eligible = [item for item in signals if item.get("source") == STARTUP_EVENT_SOURCE]
    if not eligible:
        return []
    dates = {_plain_datetime(item["signal_time"]).date() for item in eligible}
    symbols = {str(item["symbol"]) for item in eligible}
    signal_types = {str(item["signal_type"]) for item in eligible}
    existing = set(
        db.execute(
            select(
                ResearchSignalLedger.signal_date,
                ResearchSignalLedger.symbol,
                ResearchSignalLedger.signal_type,
            )
            .where(ResearchSignalLedger.source == STARTUP_EVENT_SOURCE)
            .where(ResearchSignalLedger.signal_date.in_(dates))
            .where(ResearchSignalLedger.symbol.in_(symbols))
            .where(ResearchSignalLedger.signal_type.in_(signal_types))
        ).all()
    )
    created: list[dict[str, Any]] = []
    for item in eligible:
        key = (
            _plain_datetime(item["signal_time"]).date(),
            str(item["symbol"]),
            str(item["signal_type"]),
        )
        if key in existing:
            continue
        existing.add(key)
        created.append(item)
    record_research_signals(db, created)
    return created
```

Change startup lifecycle event types to canonical keys and include prior state, evidence, invalidation reasons, and next conditions in `evidence_json`. Keep mainline signals on the existing generic recording path.

- [ ] **Step 4: Fix scheduled snapshot evidence ordering**

In `capture_intraday_market_turn_snapshot_task`, derive confirmed sectors from the newly built market snapshot first, then call candidate discovery once:

```python
cross_day = snapshot.get("cross_day_mainline")
confirmed_sectors = {
    str(sector).strip()
    for sector in (
        cross_day.get("confirmed_sectors")
        if isinstance(cross_day, dict) and cross_day.get("status") == "观察确认"
        else []
    )
    if str(sector).strip()
}
candidate_result = discover_intraday_candidates(
    db,
    trade_date=trade_date,
    pool_name="experiment",
    limit=50,
    include_growth_board=False,
    as_of=current_time,
    sustained_startup_sectors=confirmed_sectors,
)
```

Remove the branch that only passes confirmed sectors when `candidate_result is None`. Persist newly created lifecycle events in the same database transaction as the market snapshot.

- [ ] **Step 5: Run event/task tests and verify GREEN**

Run: `.venv/bin/pytest -q tests/test_research_signal_ledger.py tests/test_jobs_pipeline.py -k 'startup or intraday_market_turn'`

Expected: all selected tests pass.

- [ ] **Step 6: Commit event flow**

```bash
git add services/engine/research_signal_ledger.py services/jobs/tasks.py tests/test_research_signal_ledger.py tests/test_jobs_pipeline.py
git commit -m "feat: persist startup state events"
```

### Task 4: Gate And Cancel Startup Plans

**Files:**
- Modify: `services/engine/plans/repository.py`
- Modify: `services/engine/paper/realtime.py`
- Modify: `tests/test_trade_plan_repository.py`
- Modify: `tests/test_realtime_quotes.py`

- [ ] **Step 1: Write failing plan behavior tests**

Create three cases using real in-memory SQLAlchemy rows:

```python
assert startup_plan_gate(db, probing_plan, as_of=quote_time).allowed is False
assert startup_plan_gate(db, confirmed_plan, as_of=quote_time).allowed is True

cancelled = cancel_invalidated_startup_plans(
    db,
    trade_date="2026-07-22",
    symbols={"600001"},
    reason="板块转弱",
)
assert cancelled == 1
assert planned.status == "cancelled"
assert executed.status == "executed"
assert unrelated.status == "planned"
```

- [ ] **Step 2: Run plan tests and verify RED**

Run: `.venv/bin/pytest -q tests/test_trade_plan_repository.py tests/test_realtime_quotes.py -k startup`

Expected: missing gate/cancellation helpers.

- [ ] **Step 3: Implement startup-only plan helpers**

Use active `ResearchPoolItem` tags to determine whether a symbol belongs to the startup lifecycle. Query the latest same-day lifecycle event for that symbol.

```python
@dataclass(frozen=True)
class StartupPlanGate:
    tracked: bool
    state: str | None
    allowed: bool
    reason: str | None


def startup_plan_gate(db, plan: TradePlan, *, as_of: datetime) -> StartupPlanGate:
    item = db.execute(
        select(ResearchPoolItem)
        .where(ResearchPoolItem.symbol == plan.symbol)
        .where(ResearchPoolItem.status == "active")
        .order_by(ResearchPoolItem.updated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    tags = [str(tag) for tag in (item.tags_json or {}).get("tags", [])] if item else []
    if "candidate_pool:startup_preheat" not in tags:
        return StartupPlanGate(False, None, True, None)
    state = latest_startup_states(
        db,
        signal_date=plan.trade_date,
        symbols={plan.symbol},
        as_of=as_of,
    ).get(plan.symbol)
    if state is None:
        state = next(
            (
                tag.removeprefix("startup_state:")
                for tag in tags
                if tag.startswith("startup_state:")
            ),
            "preheat",
        )
    reason = None if state == "confirmed" else f"启动状态为{STARTUP_LABELS[state]}"
    return StartupPlanGate(True, state, state == "confirmed", reason)
```

- Return no startup gate for symbols without `candidate_pool:startup_preheat`.
- Allow only `confirmed`.
- On `invalidated`, update only `TradePlan.status == "planned"` for the current trade date and tracked symbols.
- Preserve executed/skipped/cancelled plans and all plans for untracked symbols.

- [ ] **Step 4: Apply the gate before realtime entry execution**

In `_execute_realtime_entry`, evaluate the startup gate before trigger-price execution. Return a `paper_entry_deferred` alert for preheat/probing. For invalidated states, cancel the plan and return an invalidation alert. Do not change open-position exit behavior.

- [ ] **Step 5: Run plan and realtime tests and verify GREEN**

Run: `.venv/bin/pytest -q tests/test_trade_plan_repository.py tests/test_realtime_quotes.py tests/test_paper_trade_review.py`

Expected: all tests pass.

- [ ] **Step 6: Commit plan gating**

```bash
git add services/engine/plans/repository.py services/engine/paper/realtime.py tests/test_trade_plan_repository.py tests/test_realtime_quotes.py
git commit -m "feat: gate startup paper plans"
```

### Task 5: Notify Only New Confirmation And Invalidation Events

**Files:**
- Modify: `services/notifications/dispatcher.py`
- Modify: `services/jobs/tasks.py`
- Modify: `tests/test_notifications.py`
- Modify: `tests/test_jobs_pipeline.py`

- [ ] **Step 1: Write failing notification tests**

```python
text = format_startup_state_event_text([confirmed, invalidated])
assert "启动确认" in text
assert "启动失效" in text
assert "启动预热" not in text
assert "启动试探" not in text

assert dispatch_startup_state_events([preheat, probing]) == []
```

Add a task retry test proving an already persisted confirmation produces no second dispatcher call.

- [ ] **Step 2: Run notification tests and verify RED**

Run: `.venv/bin/pytest -q tests/test_notifications.py -k startup tests/test_jobs_pipeline.py -k startup_notification`

Expected: formatter/dispatcher do not exist.

- [ ] **Step 3: Implement minimal formatter and dispatcher**

Filter to `startup_confirmed` and `startup_invalidated`. Format symbol/name, sector, price, reasons, and the existing-plan reminder. Reuse `_send_text`; do not add a channel or delivery framework.

- [ ] **Step 4: Dispatch after transaction commit**

In the scheduled snapshot task, commit market snapshot, events, and plan cancellations first. Then dispatch only the list returned by `record_startup_state_signals`. Include notification results in the task response without turning delivery failure into a database rollback.

- [ ] **Step 5: Run notification/task tests and verify GREEN**

Run: `.venv/bin/pytest -q tests/test_notifications.py tests/test_jobs_pipeline.py -k 'startup or intraday_market_turn'`

Expected: all selected tests pass.

- [ ] **Step 6: Commit notifications**

```bash
git add services/notifications/dispatcher.py services/jobs/tasks.py tests/test_notifications.py tests/test_jobs_pipeline.py
git commit -m "feat: notify startup state changes"
```

### Task 6: Event-Based Outcomes And Workspace API

**Files:**
- Modify: `services/engine/intraday/outcomes.py`
- Modify: `services/engine/tracking/startup.py`
- Modify: `apps/api/app/routers/workspace.py`
- Modify: `tests/test_intraday_startup_outcomes.py`
- Modify: `tests/test_startup_tracking.py`
- Modify: `tests/test_workspace_api.py`

- [ ] **Step 1: Write failing outcome/API tests**

Insert probing, confirmed, and invalidated ledger rows with known prices and later bars. Assert:

```python
assert report["state_summary"]["confirmed"][1]["sample_count"] == 1
assert report["probing_to_confirmed_rate"] == 0.5
assert report["confirmed_to_invalidated_rate"] == 1.0
assert response.state == "invalidated"
assert response.invalidation_reasons == ["板块转弱"]
assert response.next_conditions == []
```

- [ ] **Step 2: Run outcome/API tests and verify RED**

Run: `.venv/bin/pytest -q tests/test_intraday_startup_outcomes.py tests/test_startup_tracking.py tests/test_workspace_api.py -k startup`

Expected: missing state summary, conversion fields, and lifecycle response properties.

- [ ] **Step 3: Read lifecycle events in outcomes**

Query `ResearchSignalLedger.source == "startup_state"` up to `current_time`. Use the first event per date/symbol/state as the signal observation and existing daily-bar logic for 1/3/5-day return, gain, and drawdown metrics. Compute conversions from distinct date/symbol paths.

If no canonical events exist for a requested legacy date, retain the current raw-snapshot fallback for `starting` and `accelerating` so old history remains readable.

- [ ] **Step 4: Extend tracking and response models**

Read `startup_state:` tags and latest lifecycle event evidence. Add state time, confirmation evidence, invalidation reasons, next conditions, and plan availability to the startup tracking response. Keep legacy tags readable but never infer canonical state from Chinese label text.

- [ ] **Step 5: Run outcome/API tests and verify GREEN**

Run: `.venv/bin/pytest -q tests/test_intraday_startup_outcomes.py tests/test_startup_tracking.py tests/test_workspace_api.py`

Expected: all tests pass.

- [ ] **Step 6: Commit API/outcomes**

```bash
git add services/engine/intraday/outcomes.py services/engine/tracking/startup.py apps/api/app/routers/workspace.py tests/test_intraday_startup_outcomes.py tests/test_startup_tracking.py tests/test_workspace_api.py
git commit -m "feat: report startup lifecycle outcomes"
```

### Task 7: Render Canonical Lifecycle In Web

**Files:**
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/intradayStartupSignal.test.mjs`
- Modify: `apps/web/src/startupTrackingPanel.test.mjs`

- [ ] **Step 1: Write failing frontend contract tests**

Assert the API interface contains `state`, `confirmation_evidence`, `invalidation_reasons`, and `next_conditions`; assert `App.tsx` renders those fields and does not compare Chinese labels to determine state.

- [ ] **Step 2: Run frontend tests and verify RED**

Run: `cd apps/web && node src/intradayStartupSignal.test.mjs && node src/startupTrackingPanel.test.mjs`

Expected: assertions fail for missing lifecycle fields.

- [ ] **Step 3: Update types and rendering**

Use canonical state for CSS tone. In the startup tracking strip and intraday snapshot rows, render the label plus at most one evidence/reason line and one next-condition line. Preserve compact layout and avoid a new page or nested card.

- [ ] **Step 4: Run frontend tests and build**

Run: `cd apps/web && node src/intradayStartupSignal.test.mjs && node src/startupTrackingPanel.test.mjs && npm run build`

Expected: tests pass and Vite build succeeds.

- [ ] **Step 5: Commit Web integration**

```bash
git add apps/web/src/api.ts apps/web/src/App.tsx apps/web/src/intradayStartupSignal.test.mjs apps/web/src/startupTrackingPanel.test.mjs
git commit -m "feat: display startup lifecycle"
```

### Task 8: Regression, Runtime Hygiene, And Handoff

**Files:**
- Modify: `.gitignore`
- Modify: `docs/AI_HANDOFF_2026-07-22.md`

- [ ] **Step 1: Ignore local runtime artifacts**

Add exactly:

```gitignore
.stock-dev.sqlite
dump.rdb
```

- [ ] **Step 2: Run focused backend regression**

Run:

```bash
.venv/bin/pytest -q \
  tests/test_startup_state.py \
  tests/test_next_session_candidates.py \
  tests/test_intraday_candidates.py \
  tests/test_research_signal_ledger.py \
  tests/test_jobs_pipeline.py \
  tests/test_trade_plan_repository.py \
  tests/test_realtime_quotes.py \
  tests/test_notifications.py \
  tests/test_intraday_startup_outcomes.py \
  tests/test_startup_tracking.py \
  tests/test_workspace_api.py
```

Expected: zero failures.

- [ ] **Step 3: Run complete verification**

Run:

```bash
.venv/bin/pytest -q
cd apps/web && npm run build
git diff --check
```

Expected: complete backend suite passes, frontend build succeeds, and diff check is empty.

- [ ] **Step 4: Check worker activity before restart**

Run: `.venv/bin/celery -A services.jobs.celery_app.celery_app inspect active --timeout=2`

Expected: no active jobs. If jobs are active, do not restart the worker.

- [ ] **Step 5: Update handoff with evidence**

Record the implemented lifecycle, actual test totals, build result, latest real data date inspected, commit hashes, and remaining sample-size risk. Do not include credentials, tokens, webhook URLs, SQLite data, or Redis data.

- [ ] **Step 6: Commit hygiene and handoff**

```bash
git add .gitignore docs/AI_HANDOFF_2026-07-22.md
git commit -m "docs: hand off startup state loop"
```
