from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EvidenceTag:
    name: str
    direction: str
    severity: str
    rationale: str
    values: dict[str, float | str | None]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _score(value: Any, default: float = 50.0) -> float:
    return _float(value) if value is not None else default


def _near_recent_high(context: dict[str, Any]) -> bool:
    distance_to_high = _float(context.get("distance_to_20d_high"))
    return_5d = _float(context.get("return_5d"))
    return_20d = _float(context.get("return_20d"))
    return (
        (distance_to_high is not None and distance_to_high >= -0.03)
        or (return_5d is not None and return_5d >= 0.08)
        or (return_20d is not None and return_20d >= 0.15)
    )


def _amount_percentile(context: dict[str, Any]) -> float:
    return _score(context.get("amount_percentile_60d"), _score(context.get("volume_score")))


def build_trade_evidence(context: dict[str, Any]) -> dict[str, Any]:
    amount_percentile = _amount_percentile(context)
    trend_score = _score(context.get("trend_score"))
    sector_strength = _score(context.get("sector_strength_score"))
    sector_confidence = _score(context.get("sector_sample_confidence"), 0.0)
    risk_score = _score(context.get("risk_score"))
    atr_percentile = _score(context.get("atr_pct_percentile_60d"))
    fundamental_score = _score(context.get("fundamental_score"))
    fundamental_verdict = context.get("fundamental_verdict")
    near_high = _near_recent_high(context)

    tags: list[EvidenceTag] = []

    if amount_percentile >= 80 and near_high:
        tags.append(
            EvidenceTag(
                name="high_position_volume_spike",
                direction="risk",
                severity="high",
                rationale="高位或短期涨幅较大时出现极端放量，可能是追高、诱多或利好兑现。",
                values={
                    "amount_percentile_60d": amount_percentile,
                    "distance_to_20d_high": _float(context.get("distance_to_20d_high")),
                    "return_5d": _float(context.get("return_5d")),
                    "return_20d": _float(context.get("return_20d")),
                },
            )
        )

    if 55 <= amount_percentile < 80 and trend_score >= 65:
        tags.append(
            EvidenceTag(
                name="moderate_volume_confirmation",
                direction="support",
                severity="medium",
                rationale="温和放量叠加趋势较强，更偏向承接确认，而不是单纯追涨。",
                values={
                    "amount_percentile_60d": amount_percentile,
                    "trend_score": trend_score,
                },
            )
        )

    if sector_strength >= 70 and sector_confidence >= 0.2:
        tags.append(
            EvidenceTag(
                name="strong_sector_confirmation",
                direction="support",
                severity="medium",
                rationale="板块强度较高且样本可信度不低，个股信号有板块环境支撑。",
                values={
                    "sector_strength_score": sector_strength,
                    "sector_sample_confidence": sector_confidence,
                },
            )
        )
    elif sector_strength < 50:
        tags.append(
            EvidenceTag(
                name="weak_sector_confirmation",
                direction="risk",
                severity="medium",
                rationale="板块强度不足，个股信号容易变成孤立冲高。",
                values={"sector_strength_score": sector_strength},
            )
        )

    if trend_score >= 75 and risk_score <= 35:
        tags.append(
            EvidenceTag(
                name="trend_alignment",
                direction="support",
                severity="medium",
                rationale="均线趋势和风险分数同时支持，说明技术形态相对顺势。",
                values={"trend_score": trend_score, "risk_score": risk_score},
            )
        )

    if atr_percentile >= 80:
        tags.append(
            EvidenceTag(
                name="volatility_overheat",
                direction="risk",
                severity="medium",
                rationale="波动分位较高，止损和追高失败概率需要单独观察。",
                values={"atr_pct_percentile_60d": atr_percentile},
            )
        )

    if fundamental_verdict == "weak" and amount_percentile >= 70:
        tags.append(
            EvidenceTag(
                name="weak_quality_hot_money",
                direction="risk",
                severity="high",
                rationale="基本面偏弱但交易热度较高，更可能是题材或资金博弈驱动。",
                values={
                    "fundamental_score": fundamental_score,
                    "amount_percentile_60d": amount_percentile,
                },
            )
        )
    elif fundamental_verdict == "supportive":
        tags.append(
            EvidenceTag(
                name="fundamental_support",
                direction="support",
                severity="low",
                rationale="基本面评分对交易计划形成支撑，但仍需结合交易面验证。",
                values={"fundamental_score": fundamental_score},
            )
        )

    if context.get("holding_style") == "compound" or context.get("sector_style") == "compound":
        tags.append(
            EvidenceTag(
                name="compound_sector_context",
                direction="context",
                severity="low",
                rationale="复利型稳定板块不应套用高弹性题材的止盈止损参数。",
                values={
                    "sector_style": context.get("sector_style"),
                    "holding_style": context.get("holding_style"),
                },
            )
        )

    return {
        "schema_version": 1,
        "tags": [tag.to_dict() for tag in tags],
        "risk_flags": [tag.name for tag in tags if tag.direction == "risk"],
        "support_flags": [tag.name for tag in tags if tag.direction == "support"],
        "scores": {
            "amount_percentile_60d": amount_percentile,
            "trend_score": trend_score,
            "sector_strength_score": sector_strength,
            "risk_score": risk_score,
            "atr_pct_percentile_60d": atr_percentile,
            "fundamental_score": fundamental_score,
        },
    }
