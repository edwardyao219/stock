from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import desc, func, select

from services.engine.backtest.learning import generate_backtest_learning_report
from services.engine.backtest.sync import run_rules_backtest
from services.engine.features.sync import (
    compute_and_store_sector_features,
    compute_and_store_stock_features,
)
from services.engine.paper.learning import generate_paper_learning_report
from services.engine.paper.review import generate_paper_trade_reviews
from services.engine.paper.simulator import run_daily_paper_simulation
from services.engine.plans.sync import MAIN_TRADE_STRATEGY_TYPES, generate_and_store_trade_plans
from services.engine.research_pool.candidates import discover_next_session_candidates
from services.shared.database import SessionLocal
from services.shared.models import (
    DailyBar,
    PaperAccount,
    PaperPosition,
    SectorFeatureDaily,
    StockFeatureDaily,
    TradingCalendar,
)

HISTORICAL_REPLAY_PRESETS: dict[str, dict[str, object]] = {
    "may_focus": {
        "start_date": "2026-05-01",
        "end_date": "2026-05-31",
        "symbols": ["002837", "603083", "600183"],
        "account_name": "历史回放:5月去噪",
    },
    "june_hot_sectors": {
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "symbols": ["600183", "603083", "002837", "600519"],
        "account_name": "历史回放:6月热门板块",
    }
}
NOISE_REPLAY_SYMBOLS = {"000001"}


@dataclass(frozen=True)
class HistoricalReplayAccountSummary:
    initial_cash: float
    cash: float
    market_value: float
    equity: float
    total_return_pct: float
    realized_pnl: float
    open_positions: int
    closed_positions: int
    win_rate: float | None
    avg_closed_return_pct: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HistoricalReplayDayResult:
    trade_date: str
    next_trade_date: str | None
    feature_rows: int = 0
    sector_rows: int = 0
    contexts: int = 0
    candidates: int = 0
    plans: int = 0
    written_plans: int = 0
    opened: int = 0
    closed: int = 0
    skipped: int = 0
    paper_reviews: int = 0
    backtest_trades: int = 0
    paper_learning: int = 0
    backtest_learning: int = 0
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HistoricalReplayResult:
    start_date: str
    end_date: str
    account: str
    preset: str | None
    symbols: list[str]
    processed_days: int
    generated_plans: int
    opened: int
    closed: int
    skipped: int
    account_summary: HistoricalReplayAccountSummary
    days: list[HistoricalReplayDayResult]

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "account_summary": self.account_summary.to_dict(),
            "days": [item.to_dict() for item in self.days],
        }


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _sanitize_replay_symbols(symbols: list[str] | None) -> list[str]:
    clean_symbols: list[str] = []
    seen: set[str] = set()
    for symbol in symbols or []:
        clean_symbol = symbol.strip()
        if not clean_symbol or clean_symbol in NOISE_REPLAY_SYMBOLS:
            continue
        if clean_symbol in seen:
            continue
        seen.add(clean_symbol)
        clean_symbols.append(clean_symbol)
    return clean_symbols


def _available_trade_dates(start_date: date, end_date: date, symbols: list[str]) -> list[date]:
    with SessionLocal() as db:
        stmt = (
            select(DailyBar.trade_date)
            .where(DailyBar.trade_date >= start_date)
            .where(DailyBar.trade_date <= end_date)
            .group_by(DailyBar.trade_date)
            .order_by(DailyBar.trade_date)
        )
        if symbols:
            stmt = stmt.where(DailyBar.symbol.in_(symbols))
        dates = list(db.execute(stmt).scalars())
        if dates:
            return dates

        calendar_stmt = (
            select(TradingCalendar.trade_date)
            .where(TradingCalendar.trade_date >= start_date)
            .where(TradingCalendar.trade_date <= end_date)
            .where(TradingCalendar.is_open.is_(True))
            .order_by(TradingCalendar.trade_date)
        )
        return list(db.execute(calendar_stmt).scalars())


def _symbol_count_for_date(trade_date: date, symbols: list[str]) -> int:
    with SessionLocal() as db:
        stmt = select(func.count(func.distinct(DailyBar.symbol))).where(
            DailyBar.trade_date == trade_date
        )
        if symbols:
            stmt = stmt.where(DailyBar.symbol.in_(symbols))
        return int(db.execute(stmt).scalar_one() or 0)


def _feature_row_count_for_date(trade_date: date, symbols: list[str]) -> int:
    with SessionLocal() as db:
        stmt = select(func.count()).select_from(StockFeatureDaily).where(
            StockFeatureDaily.trade_date == trade_date
        )
        if symbols:
            stmt = stmt.where(StockFeatureDaily.symbol.in_(symbols))
        return int(db.execute(stmt).scalar_one() or 0)


def _sector_row_count_for_date(trade_date: date) -> int:
    with SessionLocal() as db:
        stmt = select(func.count()).select_from(SectorFeatureDaily).where(
            SectorFeatureDaily.trade_date == trade_date
        )
        return int(db.execute(stmt).scalar_one() or 0)


def _account_name(base_name: str, *, start_date: str, end_date: str) -> str:
    clean_name = base_name.strip() or "历史回放"
    if clean_name != "历史回放":
        return clean_name
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"历史回放:{start_date}~{end_date}:{run_id}"


def _latest_close(db, symbol: str, end_date: date) -> Decimal | None:
    stmt = (
        select(DailyBar.close)
        .where(DailyBar.symbol == symbol)
        .where(DailyBar.trade_date <= end_date)
        .order_by(desc(DailyBar.trade_date))
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def _account_summary(
    *,
    account_name: str,
    initial_cash: Decimal,
    end_date: date,
) -> HistoricalReplayAccountSummary:
    with SessionLocal() as db:
        account = db.execute(
            select(PaperAccount).where(PaperAccount.name == account_name)
        ).scalar_one_or_none()
        if account is None:
            cash = initial_cash
            market_value = Decimal("0")
            closed_positions: list[PaperPosition] = []
            open_positions: list[PaperPosition] = []
        else:
            cash = Decimal(account.cash)
            closed_positions = list(
                db.execute(
                    select(PaperPosition)
                    .where(PaperPosition.account_id == account.id)
                    .where(PaperPosition.status == "closed")
                ).scalars()
            )
            open_positions = list(
                db.execute(
                    select(PaperPosition)
                    .where(PaperPosition.account_id == account.id)
                    .where(PaperPosition.status == "open")
                ).scalars()
            )
            market_value = Decimal("0")
            for position in open_positions:
                close = _latest_close(db, position.symbol, end_date) or position.entry_price
                market_value += Decimal(close) * Decimal(position.quantity)

    equity = cash + market_value
    realized_pnl = sum(Decimal(position.pnl or 0) for position in closed_positions)
    closed_returns = [
        float(position.pnl_pct)
        for position in closed_positions
        if position.pnl_pct is not None
    ]
    wins = [value for value in closed_returns if value > 0]
    return HistoricalReplayAccountSummary(
        initial_cash=float(initial_cash),
        cash=float(cash),
        market_value=float(market_value),
        equity=float(equity),
        total_return_pct=float(equity / initial_cash - Decimal("1")) if initial_cash > 0 else 0.0,
        realized_pnl=float(realized_pnl),
        open_positions=len(open_positions),
        closed_positions=len(closed_positions),
        win_rate=(len(wins) / len(closed_returns) if closed_returns else None),
        avg_closed_return_pct=(
            sum(closed_returns) / len(closed_returns) if closed_returns else None
        ),
    )


def _discover_candidates_and_generate_plans(
    *,
    trade_date: str,
    next_trade_date: str,
    symbols: list[str],
    limit: int,
    use_learning_adjustments: bool,
) -> tuple[dict, dict[str, int | str]]:
    with SessionLocal() as db:
        discovery = discover_next_session_candidates(
            db,
            feature_date=trade_date,
            next_trade_date=next_trade_date,
            pool_name="experiment",
            symbols=symbols,
            limit=limit,
            min_universe_size=0,
        )
        db.commit()

    formal_symbols = [
        item["symbol"]
        for item in discovery.get("candidates", [])
        if item.get("selection_mode") == "formal_strategy"
    ]
    plan_result = generate_and_store_trade_plans(
        plan_date=trade_date,
        trade_date=next_trade_date,
        feature_date=discovery.get("feature_date") or trade_date,
        symbols=formal_symbols,
        limit=len(formal_symbols),
        use_learning_adjustments=use_learning_adjustments,
    )
    return discovery, plan_result


def run_historical_replay(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    symbols: list[str] | None = None,
    preset: str | None = None,
    account_name: str = "历史回放",
    initial_cash: Decimal = Decimal("1000000"),
    limit: int = 30,
    use_learning_adjustments: bool = True,
    generate_learning: bool = True,
    dry_run: bool = False,
) -> HistoricalReplayResult:
    """Replay historical days as if each day were a real trading session.

    The replay intentionally uses the existing paper trading engine, but isolates
    results in a separate paper account so research output does not mix with the
    current live paper simulation account.
    """
    preset_config = HISTORICAL_REPLAY_PRESETS.get(preset, {}) if preset else {}
    if preset and preset not in HISTORICAL_REPLAY_PRESETS:
        raise ValueError(f"Unsupported historical replay preset: {preset}")

    effective_start_date = start_date or str(preset_config.get("start_date") or "")
    effective_end_date = end_date or str(preset_config.get("end_date") or "")
    if not effective_start_date or not effective_end_date:
        raise ValueError("start_date and end_date are required for historical replay")

    parsed_start = _parse_date(effective_start_date)
    parsed_end = _parse_date(effective_end_date)
    if parsed_end < parsed_start:
        raise ValueError("end_date must be greater than or equal to start_date")

    preset_symbols = list(preset_config.get("symbols") or [])
    clean_symbols = _sanitize_replay_symbols(symbols if symbols is not None else preset_symbols)
    if not clean_symbols:
        raise ValueError("at least one symbol is required for historical replay")

    trade_dates = _available_trade_dates(parsed_start, parsed_end, clean_symbols)
    day_results: list[HistoricalReplayDayResult] = []
    resolved_account_name = account_name
    if preset and account_name == "历史回放" and preset_config.get("account_name"):
        resolved_account_name = str(preset_config["account_name"])
    account = _account_name(
        resolved_account_name,
        start_date=effective_start_date,
        end_date=effective_end_date,
    )
    effective_limit = max(1, min(limit, len(clean_symbols)))

    compute_and_store_stock_features(
        symbols=clean_symbols,
        start_date=parsed_start,
        end_date=parsed_end,
    )
    compute_and_store_sector_features(
        start_date=parsed_start,
        end_date=parsed_end,
    )

    for index, current_date in enumerate(trade_dates):
        next_date = trade_dates[index + 1] if index + 1 < len(trade_dates) else None
        current_date_text = current_date.isoformat()
        next_date_text = next_date.isoformat() if next_date else None

        messages: list[str] = []
        opened = 0
        closed = 0
        skipped = 0
        if not dry_run:
            paper_result = run_daily_paper_simulation(
                trade_date=current_date_text,
                account_name=account,
                initial_cash=initial_cash,
                symbols=clean_symbols,
                allowed_strategy_types=MAIN_TRADE_STRATEGY_TYPES,
            )
            opened = paper_result.opened
            closed = paper_result.closed
            skipped = paper_result.skipped
            messages.extend(paper_result.messages[:20])

        paper_reviews = 0
        backtest_trades = 0
        paper_learning = 0
        backtest_learning = 0
        if generate_learning and not dry_run:
            paper_reviews = generate_paper_trade_reviews(current_date_text)
            paper_learning = generate_paper_learning_report(current_date_text)
            backtest_result = run_rules_backtest(
                symbols=clean_symbols,
                end_date=current_date,
                run_date=current_date,
                persist=True,
            )
            backtest_trades = int(backtest_result["trade_count"])
            backtest_learning = generate_backtest_learning_report(current_date_text)

        contexts = 0
        candidates = 0
        plans = 0
        written_plans = 0
        if next_date is not None:
            discovery, plan_result = _discover_candidates_and_generate_plans(
                trade_date=current_date_text,
                next_trade_date=next_date_text,
                symbols=clean_symbols,
                limit=effective_limit,
                use_learning_adjustments=use_learning_adjustments,
            )
            contexts = int(discovery.get("universe_size", plan_result.get("contexts", 0)) or 0)
            candidates = len(discovery.get("candidates", []))
            plans = int(plan_result["plans"])
            written_plans = int(plan_result["written"])
            messages.append(
                f"{current_date_text} 盘后筛选 {candidates} 只候选，"
                f"生成 {written_plans} 条 {next_date_text} 交易计划。"
            )

        symbol_count = _symbol_count_for_date(current_date, clean_symbols)
        if symbol_count < len(clean_symbols):
            messages.insert(
                0,
                f"{current_date_text} 本地日线覆盖 {symbol_count}/{len(clean_symbols)} 只股票。",
            )

        day_results.append(
            HistoricalReplayDayResult(
                trade_date=current_date_text,
                next_trade_date=next_date_text,
                feature_rows=_feature_row_count_for_date(current_date, clean_symbols),
                sector_rows=_sector_row_count_for_date(current_date),
                contexts=contexts,
                candidates=candidates,
                plans=plans,
                written_plans=written_plans,
                opened=opened,
                closed=closed,
                skipped=skipped,
                paper_reviews=paper_reviews,
                backtest_trades=backtest_trades,
                paper_learning=paper_learning,
                backtest_learning=backtest_learning,
                messages=messages,
            )
        )

    return HistoricalReplayResult(
        start_date=effective_start_date,
        end_date=effective_end_date,
        account=account,
        preset=preset,
        symbols=clean_symbols,
        processed_days=len(day_results),
        generated_plans=sum(item.written_plans for item in day_results),
        opened=sum(item.opened for item in day_results),
        closed=sum(item.closed for item in day_results),
        skipped=sum(item.skipped for item in day_results),
        account_summary=_account_summary(
            account_name=account,
            initial_cash=initial_cash,
            end_date=parsed_end,
        ),
        days=day_results,
    )
