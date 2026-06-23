from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class SectorFeatureRow:
    sector_code: str
    trade_date: str
    features: dict[str, Any]


def _score_between(value: float, low: float, high: float) -> float:
    if high == low:
        return 50.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100))


def _avg(values: list[float]) -> float | None:
    return mean(values) if values else None


def _sample_confidence(count: int) -> float:
    if count <= 0:
        return 0.0
    return max(0.0, min(1.0, count / 10))


def compute_sector_features(stock_contexts: list[dict[str, Any]]) -> list[SectorFeatureRow]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for context in stock_contexts:
        sector_code = context.get("sector_code") or context.get("industry")
        trade_date = context.get("trade_date")
        if not sector_code or not trade_date:
            continue
        grouped.setdefault((str(sector_code), str(trade_date)), []).append(context)

    rows: list[SectorFeatureRow] = []
    for (sector_code, trade_date), items in grouped.items():
        returns_1d = [float(item["return_1d"]) for item in items if item.get("return_1d") is not None]
        returns_5d = [float(item["return_5d"]) for item in items if item.get("return_5d") is not None]
        returns_20d = [float(item["return_20d"]) for item in items if item.get("return_20d") is not None]
        trend_scores = [float(item["trend_score"]) for item in items if item.get("trend_score") is not None]
        volume_scores = [float(item["volume_score"]) for item in items if item.get("volume_score") is not None]
        relative_scores = [
            float(item["relative_strength_score"])
            for item in items
            if item.get("relative_strength_score") is not None
        ]

        up_count = sum(1 for value in returns_1d if value > 0)
        breadth_score = up_count / len(returns_1d) * 100 if returns_1d else 50.0
        avg_return_5d = _avg(returns_5d) or 0.0
        avg_return_20d = _avg(returns_20d) or 0.0
        momentum_score = (
            _score_between(avg_return_5d, -0.06, 0.10) * 0.55
            + _score_between(avg_return_20d, -0.15, 0.25) * 0.45
        )
        sector_strength_score = max(
            0.0,
            min(
                100.0,
                (_avg(trend_scores) or 50.0) * 0.30
                + (_avg(relative_scores) or 50.0) * 0.25
                + (_avg(volume_scores) or 50.0) * 0.20
                + breadth_score * 0.15
                + momentum_score * 0.10,
            ),
        )

        rows.append(
            SectorFeatureRow(
                sector_code=sector_code,
                trade_date=trade_date,
                features={
                    "sector_strength_score": round(sector_strength_score, 4),
                    "sector_breadth_score": round(breadth_score, 4),
                    "sector_momentum_score": round(momentum_score, 4),
                    "sector_avg_return_1d": _avg(returns_1d),
                    "sector_avg_return_5d": avg_return_5d,
                    "sector_avg_return_20d": avg_return_20d,
                    "sector_avg_trend_score": _avg(trend_scores),
                    "sector_avg_volume_score": _avg(volume_scores),
                    "sector_avg_relative_strength_score": _avg(relative_scores),
                    "sector_stock_count": len(items),
                    "sector_up_count": up_count,
                    "sector_sample_confidence": _sample_confidence(len(items)),
                },
            )
        )

    return sorted(rows, key=lambda item: (item.trade_date, item.sector_code))
