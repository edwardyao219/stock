from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from services.engine.backtest.walk_forward import CANDIDATE_DISCOVERY_CACHE_VERSION
from services.engine.review.repository import INDEX_DAILY_BAR_SYMBOLS
from services.shared.models import (
    CandidateDiscoverySnapshot,
    DailyBar,
    TradingCalendar,
    TushareDatasetSyncReceipt,
)

RECOVERY_THRESHOLD_CONFIGS = ((1, 3), (2, 4), (2, 5))
MARKET_STRESS_RECOVERY_CACHE_VERSION = "market-stress-recovery-v4"
MARKET_STRESS_RECOVERY_CACHE_DIR = Path(".tmp/market-stress-recovery-cache")
MARKET_REGIME_ORDER = (
    "strong_trend",
    "rebound",
    "rebound_unconfirmed",
    "range",
    "weak_trend",
    "panic",
)
MARKET_REGIMES = frozenset(MARKET_REGIME_ORDER)


def _is_risk_snapshot(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot.get("is_usable", True)) and (
        float(snapshot["up_ratio"]) <= 0.30
        and float(snapshot["avg_change_pct"]) < 0
    )


def _is_recovery_snapshot(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot.get("is_usable", True)) and (
        float(snapshot["up_ratio"]) >= 0.45
        and float(snapshot["avg_change_pct"]) >= -0.003
    )


def _is_supportive_snapshot(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot.get("is_usable", True)) and (
        float(snapshot["up_ratio"]) >= 0.55
        and float(snapshot["avg_change_pct"]) >= 0.005
    )


def _replay_threshold(
    snapshots: list[dict[str, Any]],
    *,
    limited_after: int,
    normal_after: int,
    false_rebound_window: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    state = "normal"
    recovery_count = 0
    active_risk_index: int | None = None
    active_risk_year: int | None = None
    active_risk_regime: str | None = None
    releases: list[tuple[int, int, str | None]] = []
    recovery_days: list[int] = []
    yearly_stats: dict[int, dict[str, Any]] = {}
    regime_stats: dict[str, dict[str, Any]] = {}
    risk_event_count = 0
    blocked_days = 0
    limited_days = 0
    blocked_opportunity_days = 0
    limited_opportunity_days = 0

    for index, snapshot in enumerate(snapshots):
        snapshot_year = int(str(snapshot["trade_date"])[:4])
        snapshot_regime = str(snapshot.get("market_regime") or "")
        if snapshot_regime not in MARKET_REGIMES:
            snapshot_regime = ""
        yearly = yearly_stats.setdefault(
            snapshot_year,
            {
                "snapshot_count": 0,
                "observed_trade_day_count": 0,
                "data_gap_count": 0,
                "risk_event_count": 0,
                "completed_recovery_count": 0,
                "evaluated_recovery_count": 0,
                "false_rebound_count": 0,
                "recovery_days": [],
                "blocked_opportunity_days": 0,
                "limited_opportunity_days": 0,
            },
        )
        yearly["observed_trade_day_count"] += 1
        regime = (
            regime_stats.setdefault(
                snapshot_regime,
                {
                    "snapshot_count": 0,
                    "risk_event_count": 0,
                    "completed_recovery_count": 0,
                    "evaluated_recovery_count": 0,
                    "false_rebound_count": 0,
                    "recovery_days": [],
                },
            )
            if snapshot_regime
            else None
        )
        if regime is not None:
            regime["snapshot_count"] += 1
        if not snapshot.get("is_usable", True):
            yearly["data_gap_count"] += 1
            if state != "normal":
                state = "blocked"
                recovery_count = 0
            continue
        yearly["snapshot_count"] += 1
        if _is_risk_snapshot(snapshot):
            if state == "normal":
                risk_event_count += 1
                yearly["risk_event_count"] += 1
                active_risk_year = snapshot_year
                active_risk_regime = snapshot_regime or None
                if regime is not None:
                    regime["risk_event_count"] += 1
            state = "blocked"
            recovery_count = 0
            active_risk_index = index
        elif state != "normal":
            recovery_count = recovery_count + 1 if _is_recovery_snapshot(snapshot) else 0
            if recovery_count >= normal_after:
                state = "normal"
                event_year = active_risk_year or snapshot_year
                event_regime = active_risk_regime
                releases.append((index, event_year, event_regime))
                yearly_stats[event_year]["completed_recovery_count"] += 1
                if event_regime is not None:
                    regime_stats[event_regime]["completed_recovery_count"] += 1
                if active_risk_index is not None:
                    duration = index - active_risk_index
                    recovery_days.append(duration)
                    yearly_stats[event_year]["recovery_days"].append(duration)
                    if event_regime is not None:
                        regime_stats[event_regime]["recovery_days"].append(duration)
                active_risk_index = None
                active_risk_year = None
                active_risk_regime = None
            elif recovery_count >= limited_after:
                state = "limited"
            else:
                state = "blocked"

        if state == "blocked":
            blocked_days += 1
            if _is_supportive_snapshot(snapshot):
                blocked_opportunity_days += 1
                yearly["blocked_opportunity_days"] += 1
        elif state == "limited":
            limited_days += 1
            if _is_supportive_snapshot(snapshot):
                limited_opportunity_days += 1
                yearly["limited_opportunity_days"] += 1

    evaluated_releases = [
        (release_index, event_year, event_regime)
        for release_index, event_year, event_regime in releases
        if release_index + false_rebound_window < len(snapshots)
        and all(
            snapshot.get("is_usable", True)
            for snapshot in snapshots[
                release_index + 1 : release_index + false_rebound_window + 1
            ]
        )
    ]
    for _, event_year, event_regime in evaluated_releases:
        yearly_stats[event_year]["evaluated_recovery_count"] += 1
        if event_regime is not None:
            regime_stats[event_regime]["evaluated_recovery_count"] += 1
    false_rebound_count = 0
    for release_index, event_year, event_regime in evaluated_releases:
        if any(
            _is_risk_snapshot(snapshot)
            for snapshot in snapshots[
                release_index + 1 : release_index + false_rebound_window + 1
            ]
        ):
            false_rebound_count += 1
            yearly_stats[event_year]["false_rebound_count"] += 1
            if event_regime is not None:
                regime_stats[event_regime]["false_rebound_count"] += 1
    completed_recovery_count = len(releases)
    evaluated_recovery_count = len(evaluated_releases)
    row = {
        "threshold_label": f"{limited_after}/{normal_after}",
        "limited_after": limited_after,
        "normal_after": normal_after,
        "risk_event_count": risk_event_count,
        "completed_recovery_count": completed_recovery_count,
        "evaluated_recovery_count": evaluated_recovery_count,
        "unresolved_event_count": max(0, risk_event_count - completed_recovery_count),
        "false_rebound_count": false_rebound_count,
        "false_rebound_rate": (
            round(false_rebound_count / evaluated_recovery_count, 6)
            if evaluated_recovery_count
            else None
        ),
        "avg_recovery_days": (
            round(sum(recovery_days) / len(recovery_days), 2) if recovery_days else None
        ),
        "blocked_days": blocked_days,
        "limited_days": limited_days,
        "blocked_opportunity_days": blocked_opportunity_days,
        "limited_opportunity_days": limited_opportunity_days,
        "is_current": (limited_after, normal_after) == (2, 4),
    }
    yearly_rows = []
    for year in sorted(yearly_stats, reverse=True):
        stats = yearly_stats[year]
        evaluated_count = int(stats["evaluated_recovery_count"])
        yearly_recovery_days = stats.pop("recovery_days")
        yearly_rows.append(
            {
                "year": year,
                **stats,
                "unresolved_event_count": max(
                    0,
                    int(stats["risk_event_count"])
                    - int(stats["completed_recovery_count"]),
                ),
                "false_rebound_rate": (
                    round(int(stats["false_rebound_count"]) / evaluated_count, 6)
                    if evaluated_count
                    else None
                ),
                "avg_recovery_days": (
                    round(sum(yearly_recovery_days) / len(yearly_recovery_days), 2)
                    if yearly_recovery_days
                    else None
                ),
            }
        )
    regime_rows = []
    for regime_name in MARKET_REGIME_ORDER:
        stats = regime_stats.get(regime_name)
        if stats is None:
            continue
        evaluated_count = int(stats["evaluated_recovery_count"])
        regime_recovery_days = stats.pop("recovery_days")
        regime_rows.append(
            {
                "regime": regime_name,
                **stats,
                "unresolved_event_count": max(
                    0,
                    int(stats["risk_event_count"])
                    - int(stats["completed_recovery_count"]),
                ),
                "false_rebound_rate": (
                    round(int(stats["false_rebound_count"]) / evaluated_count, 6)
                    if evaluated_count
                    else None
                ),
                "avg_recovery_days": (
                    round(sum(regime_recovery_days) / len(regime_recovery_days), 2)
                    if regime_recovery_days
                    else None
                ),
            }
        )
    return row, yearly_rows, regime_rows


def _opportunity_days(row: dict[str, Any]) -> int:
    return int(row["blocked_opportunity_days"]) + int(row["limited_opportunity_days"])


def _recommend_threshold(
    rows: list[dict[str, Any]],
    *,
    min_risk_events: int,
) -> dict[str, Any]:
    current = next(row for row in rows if row["is_current"])
    if int(current["risk_event_count"]) < min_risk_events:
        return {
            "status": "insufficient_data",
            "label": "样本不足，维持2/4",
            "threshold_label": "2/4",
            "summary": (
                f"仅{current['risk_event_count']}次风险事件，少于{min_risk_events}次，"
                "暂不调整恢复阈值。"
            ),
        }

    current_false_rate = current["false_rebound_rate"]
    current_recovery_days = current["avg_recovery_days"]
    dominating: list[dict[str, Any]] = []
    for row in rows:
        if row["is_current"]:
            continue
        false_rate = row["false_rebound_rate"]
        recovery_days = row["avg_recovery_days"]
        if (
            false_rate is None
            or current_false_rate is None
            or recovery_days is None
            or current_recovery_days is None
        ):
            continue
        no_worse = (
            false_rate <= current_false_rate
            and _opportunity_days(row) <= _opportunity_days(current)
            and recovery_days <= current_recovery_days
        )
        strictly_better = (
            false_rate < current_false_rate
            or _opportunity_days(row) < _opportunity_days(current)
            or recovery_days < current_recovery_days
        )
        if no_worse and strictly_better:
            dominating.append(row)

    if not dominating:
        return {
            "status": "keep_current",
            "label": "维持2/4",
            "threshold_label": "2/4",
            "summary": "替代阈值没有同时降低假反弹和恢复延迟，继续使用当前2/4。",
        }

    best = min(
        dominating,
        key=lambda row: (
            float(row["false_rebound_rate"]),
            _opportunity_days(row),
            float(row["avg_recovery_days"]),
        ),
    )
    return {
        "status": "adjust",
        "label": f"建议调整为{best['threshold_label']}",
        "threshold_label": best["threshold_label"],
        "summary": "该阈值在当前样本中同时减少假反弹、机会延迟和平均恢复天数。",
    }


def replay_market_stress_recovery(
    snapshots: list[dict[str, Any]],
    *,
    false_rebound_window: int = 3,
    min_risk_events: int = 5,
) -> dict[str, Any]:
    ordered = sorted(snapshots, key=lambda item: str(item["trade_date"]))
    usable_snapshot_count = sum(1 for item in ordered if item.get("is_usable", True))
    regime_coverage_count = sum(
        1 for item in ordered if str(item.get("market_regime") or "") in MARKET_REGIMES
    )
    replays = [
        _replay_threshold(
            ordered,
            limited_after=limited_after,
            normal_after=normal_after,
            false_rebound_window=false_rebound_window,
        )
        for limited_after, normal_after in RECOVERY_THRESHOLD_CONFIGS
    ]
    rows = [row for row, _, _ in replays]
    yearly_rows = next(yearly for row, yearly, _ in replays if row["is_current"])
    regime_rows = next(regimes for row, _, regimes in replays if row["is_current"])
    return {
        "snapshot_count": usable_snapshot_count,
        "observed_trade_day_count": len(ordered),
        "data_gap_count": len(ordered) - usable_snapshot_count,
        "market_regime_coverage_count": regime_coverage_count,
        "market_regime_gap_count": len(ordered) - regime_coverage_count,
        "false_rebound_window": false_rebound_window,
        "rows": rows,
        "yearly_rows": yearly_rows,
        "regime_rows": regime_rows,
        "recommendation": _recommend_threshold(rows, min_risk_events=min_risk_events),
    }


def load_market_stress_recovery_regimes(
    db: Session,
    *,
    start_date: str,
    end_date: str,
) -> dict[str, str]:
    rows = db.execute(
        select(CandidateDiscoverySnapshot.signal_date, CandidateDiscoverySnapshot.discovery_json)
        .where(CandidateDiscoverySnapshot.cache_version == CANDIDATE_DISCOVERY_CACHE_VERSION)
        .where(CandidateDiscoverySnapshot.signal_date >= date.fromisoformat(start_date))
        .where(CandidateDiscoverySnapshot.signal_date <= date.fromisoformat(end_date))
    ).all()
    values_by_date: dict[str, set[str]] = defaultdict(set)
    for signal_date, discovery in rows:
        snapshot = (discovery or {}).get("market_regime_snapshot") or {}
        regime = str((discovery or {}).get("market_regime") or snapshot.get("regime") or "")
        if regime in MARKET_REGIMES:
            values_by_date[signal_date.isoformat()].add(regime)
    return {
        trade_date: next(iter(regimes))
        for trade_date, regimes in values_by_date.items()
        if len(regimes) == 1
    }


def load_market_stress_recovery_snapshots(
    db: Session,
    *,
    start_date: str,
    end_date: str,
    min_coverage_ratio: float = 0.80,
) -> list[dict[str, Any]]:
    stock_count = func.count()
    up_count = func.sum(case((DailyBar.close > DailyBar.pre_close, 1), else_=0))
    avg_change_pct = func.avg(DailyBar.close / DailyBar.pre_close - 1)
    rows = db.execute(
        select(
            DailyBar.trade_date,
            stock_count.label("stock_count"),
            up_count.label("up_count"),
            avg_change_pct.label("avg_change_pct"),
        )
        .where(DailyBar.trade_date >= date.fromisoformat(start_date))
        .where(DailyBar.trade_date <= date.fromisoformat(end_date))
        .where(DailyBar.symbol.notin_(INDEX_DAILY_BAR_SYMBOLS))
        .where(DailyBar.pre_close.is_not(None))
        .where(DailyBar.pre_close > 0)
        .group_by(DailyBar.trade_date)
        .order_by(DailyBar.trade_date)
    ).all()
    max_stock_count = max((int(row.stock_count) for row in rows), default=0)
    minimum_count = max_stock_count * min_coverage_ratio
    rows_by_date = {row.trade_date: row for row in rows}
    calendar_dates = list(
        db.execute(
            select(TradingCalendar.trade_date)
            .where(TradingCalendar.trade_date >= date.fromisoformat(start_date))
            .where(TradingCalendar.trade_date <= date.fromisoformat(end_date))
            .where(TradingCalendar.is_open.is_(True))
            .order_by(TradingCalendar.trade_date)
        ).scalars()
    )
    trade_dates = calendar_dates or sorted(rows_by_date)
    snapshots: list[dict[str, Any]] = []
    for trade_date in trade_dates:
        row = rows_by_date.get(trade_date)
        if row is None:
            snapshots.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "stock_count": 0,
                    "coverage_ratio": 0.0,
                    "up_ratio": None,
                    "avg_change_pct": None,
                    "is_usable": False,
                }
            )
            continue
        row_stock_count = int(row.stock_count)
        snapshots.append(
            {
                "trade_date": trade_date.isoformat(),
                "stock_count": row_stock_count,
                "coverage_ratio": round(row_stock_count / max_stock_count, 6),
                "up_ratio": round(int(row.up_count or 0) / row_stock_count, 6),
                "avg_change_pct": round(float(row.avg_change_pct), 6),
                "is_usable": row_stock_count >= minimum_count,
            }
        )
    return snapshots


def build_market_stress_recovery_report(
    db: Session,
    *,
    start_date: str,
    end_date: str,
    min_coverage_ratio: float = 0.80,
) -> dict[str, Any]:
    snapshots = load_market_stress_recovery_snapshots(
        db,
        start_date=start_date,
        end_date=end_date,
        min_coverage_ratio=min_coverage_ratio,
    )
    regimes = load_market_stress_recovery_regimes(
        db,
        start_date=start_date,
        end_date=end_date,
    )
    for snapshot in snapshots:
        snapshot["market_regime"] = regimes.get(str(snapshot["trade_date"]))
    replay = replay_market_stress_recovery(snapshots)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "data_source": "daily_bars",
        "market_regime_data_source": "candidate_discovery_snapshots",
        "market_regime_cache_version": CANDIDATE_DISCOVERY_CACHE_VERSION,
        "min_coverage_ratio": min_coverage_ratio,
        "first_trade_date": snapshots[0]["trade_date"] if snapshots else None,
        "last_trade_date": snapshots[-1]["trade_date"] if snapshots else None,
        **replay,
    }


def load_or_build_market_stress_recovery_report(
    db: Session,
    *,
    start_date: str,
    end_date: str,
    min_coverage_ratio: float = 0.80,
    force_refresh: bool = False,
) -> dict[str, Any]:
    latest_trade_date = db.execute(
        select(func.max(DailyBar.trade_date))
        .where(DailyBar.trade_date <= date.fromisoformat(end_date))
        .where(DailyBar.symbol.notin_(INDEX_DAILY_BAR_SYMBOLS))
    ).scalar_one_or_none()
    latest_stock_count = (
        int(
            db.execute(
                select(func.count())
                .select_from(DailyBar)
                .where(DailyBar.trade_date == latest_trade_date)
                .where(DailyBar.symbol.notin_(INDEX_DAILY_BAR_SYMBOLS))
                .where(DailyBar.pre_close.is_not(None))
                .where(DailyBar.pre_close > 0)
            ).scalar_one()
        )
        if latest_trade_date
        else 0
    )
    latest_revision = db.execute(
        select(func.max(TushareDatasetSyncReceipt.completed_at))
        .where(TushareDatasetSyncReceipt.dataset == "daily_bars")
        .where(TushareDatasetSyncReceipt.trade_date >= date.fromisoformat(start_date))
        .where(TushareDatasetSyncReceipt.trade_date <= date.fromisoformat(end_date))
    ).scalar_one_or_none()
    regime_snapshot_count, latest_regime_revision = db.execute(
        select(
            func.count(),
            func.max(CandidateDiscoverySnapshot.updated_at),
        )
        .where(CandidateDiscoverySnapshot.cache_version == CANDIDATE_DISCOVERY_CACHE_VERSION)
        .where(CandidateDiscoverySnapshot.signal_date >= date.fromisoformat(start_date))
        .where(CandidateDiscoverySnapshot.signal_date <= date.fromisoformat(end_date))
    ).one()
    calendar_open_count, latest_calendar_date = db.execute(
        select(func.count(), func.max(TradingCalendar.trade_date))
        .where(TradingCalendar.trade_date >= date.fromisoformat(start_date))
        .where(TradingCalendar.trade_date <= date.fromisoformat(end_date))
        .where(TradingCalendar.is_open.is_(True))
    ).one()
    cache_payload = {
        "version": MARKET_STRESS_RECOVERY_CACHE_VERSION,
        "start_date": start_date,
        "end_date": end_date,
        "min_coverage_ratio": round(min_coverage_ratio, 6),
        "latest_trade_date": latest_trade_date.isoformat() if latest_trade_date else None,
        "latest_stock_count": latest_stock_count,
        "latest_revision": latest_revision.isoformat() if latest_revision else None,
        "market_regime_cache_version": CANDIDATE_DISCOVERY_CACHE_VERSION,
        "market_regime_snapshot_count": int(regime_snapshot_count),
        "latest_market_regime_revision": (
            latest_regime_revision.isoformat() if latest_regime_revision else None
        ),
        "calendar_open_count": int(calendar_open_count),
        "latest_calendar_date": (
            latest_calendar_date.isoformat() if latest_calendar_date else None
        ),
    }
    cache_key = hashlib.sha256(
        json.dumps(cache_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    cache_path = Path(MARKET_STRESS_RECOVERY_CACHE_DIR) / f"{cache_key}.json"
    if not force_refresh:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
        if isinstance(cached, dict) and cached.get("cache_key") == cache_key:
            report = cached.get("report")
            if isinstance(report, dict):
                return {
                    **report,
                    "cache": {
                        "hit": True,
                        "cache_key": cache_key,
                        "version": MARKET_STRESS_RECOVERY_CACHE_VERSION,
                    },
                }

    report = build_market_stress_recovery_report(
        db,
        start_date=start_date,
        end_date=end_date,
        min_coverage_ratio=min_coverage_ratio,
    )
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(
                {"cache_key": cache_key, "report": report},
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        tmp_path.replace(cache_path)
    except OSError:
        pass
    return {
        **report,
        "cache": {
            "hit": False,
            "cache_key": cache_key,
            "version": MARKET_STRESS_RECOVERY_CACHE_VERSION,
        },
    }
