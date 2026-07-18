from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time
from typing import Any

from services.engine.features.intraday_market_turn import classify_intraday_market_turn

INTRADAY_MARKET_MIN_COVERAGE_RATIO = 0.98
INTRADAY_SECTOR_MIN_SYMBOLS = 5
INTRADAY_SECTOR_MAX_UP_RATIO_DECAY = 0.05
INTRADAY_SECTOR_MAX_AVG_CHANGE_DECAY = 0.005
INTRADAY_LEADING_SECTOR_LIMIT = 6
INTRADAY_LEADING_SECTOR_MIN_AVG_CHANGE = 0.015
INTRADAY_LEADING_SECTOR_MIN_LEADER_CHANGE = 0.03
CROSS_DAY_MAINLINE_FIRST_CHECK_TIME = time(9, 45)
CROSS_DAY_MAINLINE_FINAL_CHECK_TIME = time(10, 30)
CROSS_DAY_MAINLINE_MAX_UP_RATIO_DECAY = 0.15
CROSS_DAY_MAINLINE_MAX_AVG_CHANGE_DECAY = 0.02
CROSS_DAY_MAINLINE_MAX_LEADER_CHANGE_DECAY = 0.04
CROSS_DAY_MAINLINE_MIN_AVG_CHANGE = 0.005
CROSS_DAY_MAINLINE_MIN_LEADER_CHANGE = 0.01


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _snapshot_time(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _cross_day_check_label(snapshot_time: datetime) -> str:
    if _matches_check_minute(snapshot_time, CROSS_DAY_MAINLINE_FINAL_CHECK_TIME):
        return "10:30复核"
    if _matches_check_minute(snapshot_time, CROSS_DAY_MAINLINE_FIRST_CHECK_TIME):
        return "09:45首次核验"
    if snapshot_time.time() > CROSS_DAY_MAINLINE_FIRST_CHECK_TIME:
        return "等待10:30复核"
    return "等待09:45首次核验"


def _matches_check_minute(snapshot_time: datetime, check_time: time) -> bool:
    return snapshot_time.hour == check_time.hour and snapshot_time.minute == check_time.minute


def build_cross_day_mainline_validation(
    *,
    snapshot_time: datetime | str,
    expanding_sectors: list[dict[str, object]],
    baseline_snapshot: Any | None,
) -> dict[str, object]:
    """Validate yesterday's sustained mainlines against a live A-share sector snapshot."""
    checked_at = _snapshot_time(snapshot_time)
    baseline_state = getattr(baseline_snapshot, "state_json", None) or {}
    baseline_rows = [
        item
        for item in baseline_state.get("leading_sustained_sectors") or []
        if isinstance(item, dict) and str(item.get("sector") or "").strip()
    ]
    baseline_trade_date = getattr(baseline_snapshot, "trade_date", None)
    current_by_sector = {
        str(item.get("sector") or "").strip(): item
        for item in expanding_sectors
        if str(item.get("sector") or "").strip()
    }
    first_check = _matches_check_minute(checked_at, CROSS_DAY_MAINLINE_FIRST_CHECK_TIME)
    final_check = _matches_check_minute(checked_at, CROSS_DAY_MAINLINE_FINAL_CHECK_TIME)
    check_due = first_check or final_check
    sectors: list[dict[str, object]] = []
    confirmed_sectors: list[str] = []
    for baseline in baseline_rows:
        sector = str(baseline["sector"]).strip()
        current = current_by_sector.get(sector)
        baseline_up_ratio = _float(baseline.get("up_ratio"))
        baseline_avg_change_pct = _float(baseline.get("avg_change_pct"))
        baseline_leader_change_pct = _float(baseline.get("leader_change_pct"))
        current_up_ratio = _float(current.get("up_ratio")) if current else None
        current_avg_change_pct = _float(current.get("avg_change_pct")) if current else None
        current_leader_change_pct = _float(current.get("leader_change_pct")) if current else None
        maintained = bool(
            current
            and current_up_ratio is not None
            and current_avg_change_pct is not None
            and current_leader_change_pct is not None
            and current_up_ratio
            >= max(0.55, (baseline_up_ratio or 0.55) - CROSS_DAY_MAINLINE_MAX_UP_RATIO_DECAY)
            and current_avg_change_pct
            >= max(
                CROSS_DAY_MAINLINE_MIN_AVG_CHANGE,
                (baseline_avg_change_pct or CROSS_DAY_MAINLINE_MIN_AVG_CHANGE)
                - CROSS_DAY_MAINLINE_MAX_AVG_CHANGE_DECAY,
            )
            and current_leader_change_pct
            >= max(
                CROSS_DAY_MAINLINE_MIN_LEADER_CHANGE,
                (baseline_leader_change_pct or CROSS_DAY_MAINLINE_MIN_LEADER_CHANGE)
                - CROSS_DAY_MAINLINE_MAX_LEADER_CHANGE_DECAY,
            )
        )
        if not check_due:
            status = "未确认"
            reason = "仅在09:45和10:30正式核验，其他时点不确认主线。"
        elif maintained:
            status = "观察确认"
            reason = "真实全市场快照显示板块扩散、涨幅和龙头承接仍在。"
            confirmed_sectors.append(sector)
        elif final_check:
            status = "失效"
            reason = "10:30复核未见昨日主线延续，停止主线绑定。"
        else:
            status = "未确认"
            reason = "首次核验未满足扩散和承接条件，等待10:30复核。"
        sectors.append(
            {
                "sector": sector,
                "status": status,
                "reason": reason,
                "baseline_up_ratio": baseline_up_ratio,
                "baseline_avg_change_pct": baseline_avg_change_pct,
                "baseline_leader_change_pct": baseline_leader_change_pct,
                "current_up_ratio": current_up_ratio,
                "current_avg_change_pct": current_avg_change_pct,
                "current_leader_change_pct": current_leader_change_pct,
                "current_leader_symbol": (
                    str(current.get("leader_symbol") or "") if current else None
                ),
                "current_leader_price": _float(current.get("leader_price")) if current else None,
            }
        )
    if not check_due:
        status = "未确认"
        summary = "等待下一正式核验时点，候选维持观察。"
    elif confirmed_sectors:
        status = "观察确认"
        summary = "昨日主线已获A股盘中扩散确认，仅用于观察候选绑定。"
    elif final_check and baseline_rows:
        status = "失效"
        summary = "昨日主线在10:30复核未延续，不再作为今日候选主线。"
    else:
        status = "未确认"
        summary = "昨日主线尚未获当日A股扩散确认，候选维持观察。"
    return {
        "status": status,
        "summary": summary,
        "baseline_trade_date": baseline_trade_date.isoformat()
        if hasattr(baseline_trade_date, "isoformat")
        else str(baseline_trade_date or "") or None,
        "checkpoint": _cross_day_check_label(checked_at),
        "confirmed_sectors": confirmed_sectors,
        "sectors": sectors,
    }


def _sustained_expanding_sectors(
    expanding_sectors: list[dict[str, object]],
    prior_snapshots: list[Any],
) -> list[dict[str, object]]:
    if not prior_snapshots:
        return []
    prior_state = getattr(prior_snapshots[-1], "state_json", None) or {}
    prior_by_sector = {
        str(item.get("sector") or ""): item
        for item in prior_state.get("expanding_sectors") or []
        if isinstance(item, dict) and str(item.get("sector") or "")
    }
    sustained: list[dict[str, object]] = []
    for item in expanding_sectors:
        sector = str(item["sector"])
        prior = prior_by_sector.get(sector)
        if prior is None:
            continue
        up_ratio = float(item["up_ratio"])
        avg_change_pct = float(item["avg_change_pct"])
        prior_up_ratio = _float(prior.get("up_ratio"))
        prior_avg_change_pct = _float(prior.get("avg_change_pct"))
        if (
            prior_up_ratio is None
            or prior_avg_change_pct is None
            or up_ratio < prior_up_ratio - INTRADAY_SECTOR_MAX_UP_RATIO_DECAY
            or avg_change_pct < prior_avg_change_pct - INTRADAY_SECTOR_MAX_AVG_CHANGE_DECAY
        ):
            continue
        sustained.append(
            {
                **item,
                "prior_up_ratio": round(prior_up_ratio, 6),
                "prior_avg_change_pct": round(prior_avg_change_pct, 6),
                "consecutive_snapshots": 2,
            }
        )
    return sustained


def build_intraday_market_turn_snapshot(
    *,
    quotes: list[Any],
    active_security_count: int,
    active_symbols: set[str] | None = None,
    sector_by_symbol: dict[str, str | None],
    index_change_pct: float | None,
    prior_snapshots: list[Any],
    cross_day_baseline_snapshot: Any | None = None,
    snapshot_time: datetime | None = None,
) -> dict[str, object]:
    valid_quotes = []
    for quote in quotes:
        symbol = str(getattr(quote, "symbol", ""))
        if active_symbols is not None and symbol not in active_symbols:
            continue
        price = _float(getattr(quote, "price", None))
        pre_close = _float(getattr(quote, "pre_close", None))
        if price is not None and pre_close is not None and pre_close > 0:
            valid_quotes.append((quote, price / pre_close - 1))

    coverage_ratio = len(valid_quotes) / active_security_count if active_security_count else 0.0
    breadth_ratio = (
        sum(1 for _, change_pct in valid_quotes if change_pct > 0) / len(valid_quotes)
        if valid_quotes
        else 0.0
    )
    total_amount = sum(
        _float(getattr(quote, "amount", None)) or 0.0 for quote, _change_pct in valid_quotes
    )
    sector_changes: dict[str, list[float]] = defaultdict(list)
    sector_quotes: dict[str, list[tuple[str, float, float, float]]] = defaultdict(list)
    for quote, change_pct in valid_quotes:
        sector = sector_by_symbol.get(str(getattr(quote, "symbol", "")))
        if sector:
            sector_changes[sector].append(change_pct)
            sector_quotes[sector].append(
                (
                    str(getattr(quote, "symbol", "")),
                    change_pct,
                    _float(getattr(quote, "amount", None)) or 0.0,
                    price,
                )
            )
    expanding_sectors = []
    for sector, changes in sector_changes.items():
        symbol_count = len(changes)
        up_count = sum(1 for value in changes if value > 0)
        up_ratio = up_count / symbol_count if symbol_count else 0.0
        if symbol_count < INTRADAY_SECTOR_MIN_SYMBOLS or up_ratio < 0.55:
            continue
        ranked_quotes = sorted(
            sector_quotes[sector],
            key=lambda value: (-value[1], -value[2], value[0]),
        )
        leader_symbol, leader_change_pct, _leader_amount, leader_price = ranked_quotes[0]
        expanding_sectors.append(
            {
                "sector": sector,
                "symbol_count": symbol_count,
                "up_count": up_count,
                "up_ratio": round(up_ratio, 6),
                "avg_change_pct": round(sum(changes) / symbol_count, 6),
                "total_amount": round(sum(value[2] for value in sector_quotes[sector]), 2),
                "leader_symbol": leader_symbol,
                "leader_price": round(leader_price, 4),
                "leader_change_pct": round(leader_change_pct, 6),
            }
        )
    expanding_sectors.sort(
        key=lambda item: (
            -float(item["avg_change_pct"]),
            -float(item["up_ratio"]),
            -int(item["symbol_count"]),
            str(item["sector"]),
        )
    )
    sector_expansion_count = len(expanding_sectors)
    sustained_expanding_sectors = _sustained_expanding_sectors(
        expanding_sectors,
        prior_snapshots,
    )
    leading_sustained_sectors = [
        item
        for item in sustained_expanding_sectors
        if float(item["avg_change_pct"]) >= INTRADAY_LEADING_SECTOR_MIN_AVG_CHANGE
        and float(item["leader_change_pct"]) >= INTRADAY_LEADING_SECTOR_MIN_LEADER_CHANGE
    ][:INTRADAY_LEADING_SECTOR_LIMIT]
    prior_index_values = [
        _float(getattr(item, "index_change_pct", None))
        for item in prior_snapshots
    ]
    prior_index_low_pct = min(
        (value for value in prior_index_values if value is not None),
        default=None,
    )
    prior_amount = (
        _float(getattr(prior_snapshots[-1], "total_amount", None))
        if prior_snapshots
        else None
    )
    amount_supported = prior_amount is not None and total_amount > prior_amount
    data_ready = bool(
        coverage_ratio >= INTRADAY_MARKET_MIN_COVERAGE_RATIO and index_change_pct is not None
    )
    state = classify_intraday_market_turn(
        breadth_ratio=breadth_ratio,
        index_change_pct=index_change_pct,
        prior_index_low_pct=prior_index_low_pct,
        amount_supported=amount_supported,
        sector_expansion_count=sector_expansion_count,
        data_ready=data_ready,
        prior_snapshot_count=len(prior_snapshots),
    )
    snapshot = state.to_dict()
    snapshot.update(
        {
            "data_ready": data_ready,
            "valid_quote_count": len(valid_quotes),
            "coverage_ratio": round(coverage_ratio, 6),
            "breadth_ratio": round(breadth_ratio, 6),
            "total_amount": round(total_amount, 2),
            "index_change_pct": (
                round(index_change_pct, 6) if index_change_pct is not None else None
            ),
            "prior_index_low_pct": round(prior_index_low_pct, 6)
            if prior_index_low_pct is not None
            else None,
            "amount_supported": amount_supported,
            "sector_expansion_count": sector_expansion_count,
            "expanding_sectors": expanding_sectors,
            "sustained_sector_count": len(sustained_expanding_sectors),
            "sustained_expanding_sectors": sustained_expanding_sectors,
            "leading_sustained_sector_count": len(leading_sustained_sectors),
            "leading_sustained_sectors": leading_sustained_sectors,
        }
    )
    if cross_day_baseline_snapshot is not None:
        baseline_state = getattr(cross_day_baseline_snapshot, "state_json", None) or {}
        if baseline_state.get("leading_sustained_sectors"):
            snapshot["cross_day_mainline"] = build_cross_day_mainline_validation(
                snapshot_time=snapshot_time or datetime.now(),
                expanding_sectors=expanding_sectors,
                baseline_snapshot=cross_day_baseline_snapshot,
            )
    return snapshot
