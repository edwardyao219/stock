from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select

from services.engine.plans.context import load_sector_feature_map
from services.shared.database import SessionLocal
from services.shared.models import (
    BacktestTradeRecord,
    DailyBar,
    PaperTradeReview,
    Security,
    StockFeatureDaily,
    TradePlan,
)

NOISE_SUMMARY_SYMBOLS = {"000001"}


@dataclass(frozen=True)
class FactorInsight:
    factor_id: str
    factor_name: str
    factor_type: str
    sample_count: int
    win_rate: float | None
    avg_return: float | None
    profit_factor: float | None
    max_drawdown: float | None = None
    return_stability: float | None = None
    robustness_score: float | None = None
    prev_month_avg_return: float | None = None
    stability: str = "unknown"
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MonthlyTradeSummary:
    month: str
    paper_review_count: int
    backtest_trade_count: int
    winning_reviews: int
    losing_reviews: int
    total_pnl: float
    avg_review_return: float | None
    avg_backtest_return: float | None
    top_symbols: list[dict[str, object]]
    top_rules: list[dict[str, object]]
    content_md: str = ""
    factor_insights: list[dict[str, object]] = field(default_factory=list)
    sector_opportunities: list[dict[str, object]] = field(default_factory=list)
    excluded_symbols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _float(value: Decimal | None) -> float:
    return float(value or 0)


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _profit_factor(values: list[float]) -> float:
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return gross_profit / gross_loss if gross_loss else gross_profit


def _max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        if peak > 0:
            worst = min(worst, equity / peak - 1.0)
    return worst


def _return_stability(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = variance ** 0.5
    if std == 0:
        return abs(mean)
    return abs(mean) / std


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _robustness_score(
    *,
    sample_count: int,
    avg_return: float | None,
    profit_factor: float | None,
    max_drawdown: float | None,
    return_stability: float | None,
) -> float | None:
    if sample_count < 5:
        return None
    if avg_return is None or profit_factor is None or max_drawdown is None or return_stability is None:
        return None
    return avg_return * 220.0 + profit_factor * 12.0 + return_stability * 8.0 + max_drawdown * 20.0


def _month_range(month: str) -> tuple[date, date]:
    year, month_num = month.split("-")
    start = date(int(year), int(month_num), 1)
    if month_num == "12":
        end = date(int(year), 12, 31)
    else:
        end = date(int(year), int(month_num) + 1, 1) - timedelta(days=1)
    return start, end


def _previous_month(month: str) -> str:
    start, _ = _month_range(month)
    previous = start - timedelta(days=1)
    return previous.strftime("%Y-%m")


def _factor_rules() -> list[tuple[str, str, str, Callable[[dict[str, Any]], bool]]]:
    return [
        (
            "core_entry",
            "核心入场",
            "support",
            lambda context: (
                float(context.get("trend_score") or 0) >= 70
                and float(context.get("relative_strength_score") or 0) >= 65
                and float(context.get("sector_strength_score") or 0) >= 60
                and float(context.get("volume_confirmation_score") or context.get("volume_score") or 0)
                >= 55
            ),
        ),
        (
            "trend_relative",
            "趋势+相对强度",
            "support",
            lambda context: (
                float(context.get("trend_score") or 0) >= 70
                and float(context.get("relative_strength_score") or 0) >= 65
            ),
        ),
        (
            "sector_strength",
            "板块强度",
            "support",
            lambda context: float(context.get("sector_strength_score") or 0) >= 65,
        ),
        (
            "volume_confirmation",
            "量能确认",
            "support",
            lambda context: float(
                context.get("volume_confirmation_score") or context.get("volume_score") or 0
            ) >= 58,
        ),
        (
            "overheat_filter",
            "不过热/低诱多",
            "filter",
            lambda context: (
                float(context.get("overheat_score") or 0) <= 72
                and float(context.get("volume_trap_risk_score") or 0) <= 60
            ),
        ),
        (
            "ma20_band",
            "MA20距离合适",
            "filter",
            lambda context: (
                (distance := context.get("distance_to_ma20")) is not None
                and -0.04 <= float(distance) <= 0.12
            ),
        ),
        (
            "return_20d_band",
            "20日涨幅适中",
            "filter",
            lambda context: (
                (value := context.get("return_20d")) is not None
                and 0.03 <= float(value) <= 0.25
            ),
        ),
        (
            "pullback_quality",
            "回调质量",
            "support",
            lambda context: (
                (distance := context.get("distance_to_ma20")) is not None
                and (value := context.get("return_20d")) is not None
                and -0.08 <= float(distance) <= 0.05
                and -0.03 <= float(value) <= 0.34
            ),
        ),
        (
            "sector_pullback",
            "板块共振+回调质量",
            "support",
            lambda context: (
                float(context.get("sector_strength_score") or 0) >= 65
                and (distance := context.get("distance_to_ma20")) is not None
                and (value := context.get("return_20d")) is not None
                and -0.08 <= float(distance) <= 0.05
                and -0.03 <= float(value) <= 0.34
            ),
        ),
    ]


def _core_factor(context: dict[str, Any]) -> bool:
    return _factor_rules()[0][3](context)


def _build_factor_context(
    db,
    trade: BacktestTradeRecord,
    security_map: dict[str, Security],
    plan_cache: dict[tuple[str, str, str, str], dict[str, Any]],
    sector_feature_map: dict[str, dict[str, Any]] | None = None,
    bar_map: dict[tuple[str, date], DailyBar] | None = None,
) -> dict[str, Any] | None:
    if trade.symbol in NOISE_SUMMARY_SYMBOLS:
        return None
    security = security_map.get(trade.symbol)
    if security is None:
        return None
    plan_key = (
        trade.rule_id,
        trade.symbol,
        trade.signal_date.isoformat(),
        trade.entry_date.isoformat(),
    )
    if plan_key not in plan_cache:
        plan = db.execute(
            select(TradePlan).where(
                TradePlan.rule_id == trade.rule_id,
                TradePlan.symbol == trade.symbol,
                TradePlan.plan_date == trade.signal_date,
                TradePlan.trade_date == trade.entry_date,
            )
        ).scalar_one_or_none()
        payload = plan.entry_condition_json if plan else {}
        plan_cache[plan_key] = payload if isinstance(payload, dict) else {}
    payload = plan_cache[plan_key]
    snapshot = payload.get("snapshot") or {}
    if not isinstance(snapshot, dict):
        snapshot = {}

    bar = (bar_map or {}).get((trade.symbol, trade.signal_date))
    if bar is None:
        bar = db.execute(
            select(DailyBar).where(
                DailyBar.symbol == trade.symbol,
                DailyBar.trade_date == trade.signal_date,
            )
        ).scalar_one_or_none()
    if bar is None:
        return None

    sector_features = dict(
        (sector_feature_map or load_sector_feature_map(db, trade.signal_date)).get(
            security.industry,
            {},
        )
    )
    context = dict(snapshot)
    context.update(
        {
            "symbol": trade.symbol,
            "trade_date": trade.signal_date.isoformat(),
            "name": security.name,
            "sector_code": security.industry,
            "industry": security.industry,
            "style": security.sector_style,
            "sector_style": security.sector_style,
            "analysis_framework": security.analysis_framework,
            "holding_style": security.holding_style,
            "is_st": security.is_st,
            "is_suspended": bar.is_suspended,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "amount": float(bar.amount) if bar.amount is not None else None,
            "volume": float(bar.volume) if bar.volume is not None else None,
            "turnover_rate": float(bar.turnover_rate) if bar.turnover_rate is not None else None,
            **sector_features,
        }
    )
    return context


def _trade_key(trade: BacktestTradeRecord) -> tuple[str, str, str, str]:
    return (
        trade.rule_id,
        trade.symbol,
        trade.signal_date.isoformat(),
        trade.entry_date.isoformat(),
    )


def _summarize_samples(
    samples: list[dict[str, Any]],
) -> tuple[float | None, float | None, float | None, float | None, float | None, float | None]:
    if not samples:
        return None, None, None, None, None, None
    returns = [float(item["pnl_pct"]) for item in samples]
    wins = [value for value in returns if value > 0]
    win_rate = len(wins) / len(returns) if returns else None
    avg_return = sum(returns) / len(returns) if returns else None
    profit_factor = _profit_factor(returns)
    max_drawdown = _max_drawdown(returns)
    return_stability = _return_stability(returns)
    robustness_score = _robustness_score(
        sample_count=len(returns),
        avg_return=avg_return,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        return_stability=return_stability,
    )
    return win_rate, avg_return, profit_factor, max_drawdown, return_stability, robustness_score


def _factor_insights_for_month(
    *,
    month: str,
    trades: list[BacktestTradeRecord],
    contexts: dict[tuple[str, str, str, str], dict[str, Any]],
    prev_month_avg: dict[str, float | None] | None = None,
) -> list[FactorInsight]:
    insights: list[FactorInsight] = []
    for factor_id, factor_name, factor_type, predicate in _factor_rules():
        samples = [
            {"pnl_pct": trade.pnl_pct}
            for trade in trades
            if (context := contexts.get(_trade_key(trade))) is not None and predicate(context)
        ]
        (
            win_rate,
            avg_return,
            profit_factor,
            max_drawdown,
            return_stability,
            robustness_score,
        ) = _summarize_samples(samples)
        prev_avg = prev_month_avg.get(factor_id) if prev_month_avg else None
        if avg_return is None:
            stability = "unknown"
        elif prev_avg is None:
            stability = "single_month"
        elif avg_return > 0 and prev_avg > 0:
            stability = "stable_positive"
        elif avg_return <= 0 and prev_avg <= 0:
            stability = "stable_negative"
        else:
            stability = "mixed"
        if len(samples) < 5:
            note = "样本太少，只观察，不参与稳健排序"
        elif factor_type == "support" and stability == "stable_positive":
            note = "优先作为候选"
        elif factor_type == "filter" and stability == "stable_positive":
            note = "更适合作为过滤条件"
        else:
            note = ""
        insights.append(
            FactorInsight(
                factor_id=factor_id,
                factor_name=factor_name,
                factor_type=factor_type,
                sample_count=len(samples),
                win_rate=win_rate,
                avg_return=avg_return,
                profit_factor=profit_factor,
                max_drawdown=max_drawdown,
                return_stability=return_stability,
                robustness_score=robustness_score,
                prev_month_avg_return=prev_avg,
                stability=stability,
                note=note,
            )
        )
    return sorted(
        insights,
        key=lambda item: (
            item.sample_count < 5,
            item.factor_type != "support",
            -(item.robustness_score if item.robustness_score is not None else -999.0),
        ),
    )


def _sector_opportunities_for_month(
    *,
    daily_bars: list[DailyBar],
    securities: dict[str, Security],
    trades: list[BacktestTradeRecord],
    min_stock_count: int = 5,
) -> list[dict[str, object]]:
    bars_by_symbol: dict[str, list[DailyBar]] = defaultdict(list)
    for bar in daily_bars:
        if bar.symbol in NOISE_SUMMARY_SYMBOLS:
            continue
        security = securities.get(bar.symbol)
        if security is None or not security.industry:
            continue
        if bar.close is None:
            continue
        bars_by_symbol[bar.symbol].append(bar)

    sector_symbol_returns: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for symbol, rows in bars_by_symbol.items():
        ordered = sorted(rows, key=lambda item: item.trade_date)
        if len(ordered) < 2:
            continue
        first_price = ordered[0].open or ordered[0].close
        last_price = ordered[-1].close
        if first_price is None or last_price is None or float(first_price) <= 0:
            continue
        security = securities.get(symbol)
        if security is None or not security.industry:
            continue
        month_return = float(last_price) / float(first_price) - 1.0
        sector_symbol_returns[security.industry].append(
            (symbol, security.name or "", month_return)
        )

    trade_returns_by_sector: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        if trade.symbol in NOISE_SUMMARY_SYMBOLS:
            continue
        security = securities.get(trade.symbol)
        sector = security.industry if security and security.industry else "unknown"
        trade_returns_by_sector[sector].append(_float(trade.pnl_pct))

    rows: list[dict[str, object]] = []
    for sector, symbol_returns in sector_symbol_returns.items():
        if len(symbol_returns) < min_stock_count:
            continue
        returns = [item[2] for item in symbol_returns]
        trade_returns = trade_returns_by_sector.get(sector, [])
        leaders = sorted(symbol_returns, key=lambda item: item[2], reverse=True)[:3]
        rows.append(
            {
                "sector": sector,
                "stock_count": len(symbol_returns),
                "avg_month_return": sum(returns) / len(returns),
                "median_month_return": _median(returns),
                "positive_ratio": sum(1 for value in returns if value > 0) / len(returns),
                "trade_count": len(trade_returns),
                "trade_avg_return": (
                    sum(trade_returns) / len(trade_returns) if trade_returns else None
                ),
                "trade_win_rate": (
                    sum(1 for value in trade_returns if value > 0) / len(trade_returns)
                    if trade_returns
                    else None
                ),
                "capture_gap": (
                    (sum(returns) / len(returns))
                    - (sum(trade_returns) / len(trade_returns))
                    if trade_returns
                    else None
                ),
                "leaders": [
                    {"symbol": symbol, "name": name, "return": month_return}
                    for symbol, name, month_return in leaders
                ],
            }
        )

    return sorted(
        rows,
        key=lambda item: (
            item["avg_month_return"] or 0.0,
            item["positive_ratio"] or 0.0,
            item["stock_count"] or 0,
        ),
        reverse=True,
    )


def _render_content(
    *,
    month: str,
    paper_review_count: int,
    backtest_trade_count: int,
    winning_reviews: int,
    losing_reviews: int,
    total_pnl: float,
    avg_review_return: float | None,
    avg_backtest_return: float | None,
    top_symbols: list[dict[str, object]],
    top_rules: list[dict[str, object]],
    factor_insights: list[dict[str, object]],
    sector_opportunities: list[dict[str, object]],
    prev_month: str,
) -> str:
    lines = [f"# {month} 交易总结", ""]
    lines.extend(
        [
            "## 总览",
            f"- 纸面复盘 {paper_review_count} 笔",
            f"- 回归交易 {backtest_trade_count} 笔",
            f"- 复盘盈利 {winning_reviews} / 亏损 {losing_reviews}",
            f"- 纸面总收益 {_pct(total_pnl)}",
            f"- 纸面平均收益 {_pct(avg_review_return)}",
            f"- 回归平均收益 {_pct(avg_backtest_return)}",
            f"- 对照月份 {prev_month}",
            "",
            "## 相对更顺的票",
        ]
    )
    if top_symbols:
        for item in top_symbols:
            lines.append(
                f"- {item['symbol']} {item.get('name') or ''} {item.get('sector') or ''} "
                f"收益 {_pct(item.get('avg_return'))} | 胜率 {_pct(item.get('win_rate'))}"
            )
    else:
        lines.append("- 暂无强票")
    lines.extend(["", "## 相对更顺的规则"])
    if top_rules:
        for item in top_rules:
            lines.append(
                f"- {item['rule_id']} 交易 {item.get('trade_count') or 0} 笔 "
                f"| 胜率 {_pct(item.get('win_rate'))} | 平均收益 {_pct(item.get('avg_return'))}"
            )
    else:
        lines.append("- 暂无强规则")
    lines.extend(["", "## 板块机会对照"])
    if sector_opportunities:
        for item in sector_opportunities[:10]:
            trade_avg = item.get("trade_avg_return")
            gap = item.get("capture_gap")
            leaders = item.get("leaders") or []
            leader_text = "、".join(
                f"{leader.get('symbol')} {leader.get('name') or ''} {_pct(leader.get('return'))}"
                for leader in leaders[:3]
                if isinstance(leader, dict)
            )
            lines.append(
                f"- {item['sector']} 月均 {_pct(item.get('avg_month_return'))} | "
                f"中位 {_pct(item.get('median_month_return'))} | "
                f"上涨占比 {_pct(item.get('positive_ratio'))} | "
                f"策略 {item.get('trade_count') or 0} 笔 / 均 {_pct(trade_avg)} | "
                f"机会差 {_pct(gap)}"
            )
            if leader_text:
                lines.append(f"  - 领涨：{leader_text}")
    else:
        lines.append("- 暂无板块月度对照")
    lines.extend(["", "## 因子观察"])
    if factor_insights:
        for item in factor_insights:
            prev_text = _pct(item.get("prev_month_avg_return"))
            lines.append(
                f"- {item['factor_name']} [{item['factor_type']}] "
                f"样本 {item.get('sample_count') or 0} 笔 | "
                f"胜率 {_pct(item.get('win_rate'))} | 平均收益 {_pct(item.get('avg_return'))} | "
                f"盈亏因子 {item.get('profit_factor') or 0:.2f} | "
                f"最大回撤 {_pct(item.get('max_drawdown'))} | "
                f"稳定度 {_num(item.get('return_stability'))} | "
                f"稳健分 {_num(item.get('robustness_score'))} | "
                f"上月 {_pct(item.get('prev_month_avg_return'))} | "
                f"稳定性 {item.get('stability')}"
            )
            note = item.get("note")
            if note:
                lines.append(f"  - {note}")
    else:
        lines.append("- 暂无可比较因子")
    lines.extend(
        [
            "",
            "## 结论",
            "- 这两个月更像是在找稳定信号，不是急着下定论。",
            "- 趋势、相对强度、板块强度和量能确认可以先放在前面看，但要同时看最大回撤和稳定度。",
            "- 回调质量可以作为第二个重点因子：能接受正常回调，才有可能拿住更长收益段。",
            "- 过热、诱多、20日涨幅和 MA20 距离，更适合先做提醒和过滤，少碰明显不舒服的票。",
            f"- 如果同样的表现能在 {month} 和 {prev_month} 连续站住，",
            "  再考虑小步调整。",
            "",
            "## 下一步观察",
            "- 继续回归 `trend_score` + `relative_strength_score`。",
            "- 看 `sector_strength_score` 是否能稳定给到板块顺风。",
            "- 把 `distance_to_ma20` + `return_20d` 的回调质量作为第二重点。",
            "- `volume_confirmation_score` 先做确认项，不要单独当主因子。",
        ]
    )
    return "\n".join(lines)


def generate_monthly_trade_summary(month: str) -> MonthlyTradeSummary:
    start_date, end_date = _month_range(month)
    prev_month = _previous_month(month)
    prev_start, prev_end = _month_range(prev_month)
    with SessionLocal() as db:
        paper_reviews = [
            item
            for item in db.execute(
                select(PaperTradeReview).where(
                    PaperTradeReview.exit_date >= start_date,
                    PaperTradeReview.exit_date <= end_date,
                )
            ).scalars()
            if item.symbol not in NOISE_SUMMARY_SYMBOLS
        ]
        backtest_trades = [
            item
            for item in db.execute(
                select(BacktestTradeRecord).where(
                    BacktestTradeRecord.run_date >= start_date,
                    BacktestTradeRecord.run_date <= end_date,
                )
            ).scalars()
            if item.symbol not in NOISE_SUMMARY_SYMBOLS
        ]
        prev_backtest_trades = [
            item
            for item in db.execute(
                select(BacktestTradeRecord).where(
                    BacktestTradeRecord.run_date >= prev_start,
                    BacktestTradeRecord.run_date <= prev_end,
                )
            ).scalars()
            if item.symbol not in NOISE_SUMMARY_SYMBOLS
        ]

        month_daily_bars = [
            item
            for item in db.execute(
                select(DailyBar).where(
                    DailyBar.trade_date >= start_date,
                    DailyBar.trade_date <= end_date,
                )
            ).scalars()
        ]

        symbols = {item.symbol for item in paper_reviews}
        symbols.update(item.symbol for item in backtest_trades)
        symbols.update(item.symbol for item in month_daily_bars)
        securities = {
            item.symbol: item
            for item in db.execute(select(Security).where(Security.symbol.in_(symbols))).scalars()
        }

        paper_returns = [_float(item.pnl_pct) for item in paper_reviews]
        winning_reviews = sum(1 for value in paper_returns if value > 0)
        losing_reviews = sum(1 for value in paper_returns if value <= 0)
        total_pnl = sum(paper_returns)
        avg_review_return = sum(paper_returns) / len(paper_returns) if paper_returns else None

        backtest_returns = [_float(item.pnl_pct) for item in backtest_trades]
        avg_backtest_return = (
            sum(backtest_returns) / len(backtest_returns) if backtest_returns else None
        )

        symbol_stats: dict[str, dict[str, object]] = defaultdict(lambda: {"returns": [], "wins": 0, "sector": ""})
        for item in paper_reviews:
            stats = symbol_stats[item.symbol]
            stats["sector"] = item.sector_code or ""
            stats["returns"].append(_float(item.pnl_pct))
            if float(item.pnl_pct) > 0:
                stats["wins"] += 1

        top_symbols = []
        for symbol, stats in symbol_stats.items():
            returns = stats["returns"]
            security = securities.get(symbol)
            top_symbols.append(
                {
                    "symbol": symbol,
                    "name": security.name if security else "",
                    "sector": stats["sector"],
                    "avg_return": sum(returns) / len(returns) if returns else None,
                    "win_rate": stats["wins"] / len(returns) if returns else None,
                }
            )
        top_symbols.sort(key=lambda item: (item["avg_return"] or 0, item["win_rate"] or 0), reverse=True)

        rule_stats: dict[str, dict[str, object]] = defaultdict(lambda: {"trade_count": 0, "wins": 0, "returns": []})
        for item in backtest_trades:
            stats = rule_stats[item.rule_id]
            stats["trade_count"] += 1
            stats["returns"].append(_float(item.pnl_pct))
            if float(item.pnl_pct) > 0:
                stats["wins"] += 1

        top_rules = []
        for rule_id, stats in rule_stats.items():
            returns = stats["returns"]
            top_rules.append(
                {
                    "rule_id": rule_id,
                    "trade_count": stats["trade_count"],
                    "win_rate": stats["wins"] / len(returns) if returns else None,
                    "avg_return": sum(returns) / len(returns) if returns else None,
                }
            )
        top_rules.sort(key=lambda item: (item["avg_return"] or 0, item["win_rate"] or 0), reverse=True)

        all_backtest_symbols = {item.symbol for item in backtest_trades}
        all_backtest_symbols.update(item.symbol for item in prev_backtest_trades)
        security_map = {
            item.symbol: item
            for item in db.execute(
                select(Security).where(Security.symbol.in_(all_backtest_symbols))
            ).scalars()
        }
        plan_cache: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        sector_feature_map_cache: dict[date, dict[str, dict[str, Any]]] = {}
        all_signal_dates = {
            trade.signal_date for trade in [*backtest_trades, *prev_backtest_trades]
        }
        bar_map = {
            (item.symbol, item.trade_date): item
            for item in db.execute(
                select(DailyBar)
                .where(DailyBar.symbol.in_(all_backtest_symbols))
                .where(DailyBar.trade_date.in_(all_signal_dates))
            ).scalars()
        }
        trade_contexts: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for trade in backtest_trades:
            sector_feature_map = sector_feature_map_cache.get(trade.signal_date)
            if sector_feature_map is None:
                sector_feature_map = load_sector_feature_map(db, trade.signal_date)
                sector_feature_map_cache[trade.signal_date] = sector_feature_map
            context = _build_factor_context(
                db,
                trade,
                security_map,
                plan_cache,
                sector_feature_map=sector_feature_map,
                bar_map=bar_map,
            )
            if context is None:
                continue
            trade_contexts[_trade_key(trade)] = context

        prev_contexts: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for trade in prev_backtest_trades:
            sector_feature_map = sector_feature_map_cache.get(trade.signal_date)
            if sector_feature_map is None:
                sector_feature_map = load_sector_feature_map(db, trade.signal_date)
                sector_feature_map_cache[trade.signal_date] = sector_feature_map
            context = _build_factor_context(
                db,
                trade,
                security_map,
                plan_cache,
                sector_feature_map=sector_feature_map,
                bar_map=bar_map,
            )
            if context is None:
                continue
            prev_contexts[_trade_key(trade)] = context

        prev_month_avg: dict[str, float | None] = {}
        for factor_id, _, _, predicate in _factor_rules():
            prev_samples = [
                _float(trade.pnl_pct)
                for trade in prev_backtest_trades
                if (context := prev_contexts.get(_trade_key(trade))) is not None and predicate(context)
            ]
            prev_month_avg[factor_id] = (
                sum(prev_samples) / len(prev_samples) if prev_samples else None
            )

        factor_insights = _factor_insights_for_month(
            month=month,
            trades=backtest_trades,
            contexts=trade_contexts,
            prev_month_avg=prev_month_avg,
        )
        sector_opportunities = _sector_opportunities_for_month(
            daily_bars=month_daily_bars,
            securities=securities,
            trades=backtest_trades,
        )

        content_md = _render_content(
            month=month,
            paper_review_count=len(paper_reviews),
            backtest_trade_count=len(backtest_trades),
            winning_reviews=winning_reviews,
            losing_reviews=losing_reviews,
            total_pnl=total_pnl,
            avg_review_return=avg_review_return,
            avg_backtest_return=avg_backtest_return,
            top_symbols=top_symbols[:5],
            top_rules=top_rules[:5],
            factor_insights=[item.to_dict() for item in factor_insights[:7]],
            sector_opportunities=sector_opportunities[:10],
            prev_month=prev_month,
        )

        return MonthlyTradeSummary(
            month=month,
            paper_review_count=len(paper_reviews),
            backtest_trade_count=len(backtest_trades),
            winning_reviews=winning_reviews,
            losing_reviews=losing_reviews,
            total_pnl=total_pnl,
            avg_review_return=avg_review_return,
            avg_backtest_return=avg_backtest_return,
            top_symbols=top_symbols[:5],
            top_rules=top_rules[:5],
            factor_insights=[item.to_dict() for item in factor_insights],
            sector_opportunities=sector_opportunities,
            excluded_symbols=sorted(NOISE_SUMMARY_SYMBOLS),
            content_md=content_md,
        )
