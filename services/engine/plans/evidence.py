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


def _threshold(thresholds: dict[str, float], key: str, default: float) -> float:
    return float(thresholds.get(key, default))


def _near_recent_high(context: dict[str, Any], thresholds: dict[str, float]) -> bool:
    distance_to_high = _float(context.get("distance_to_20d_high"))
    return_5d = _float(context.get("return_5d"))
    return_20d = _float(context.get("return_20d"))
    return (
        (
            distance_to_high is not None
            and distance_to_high >= _threshold(thresholds, "near_high_distance_pct", -0.03)
        )
        or (
            return_5d is not None
            and return_5d >= _threshold(thresholds, "strong_return_5d_pct", 0.08)
        )
        or (
            return_20d is not None
            and return_20d >= _threshold(thresholds, "strong_return_20d_pct", 0.15)
        )
    )


def _amount_percentile(context: dict[str, Any]) -> float:
    return _score(context.get("amount_percentile_60d"), _score(context.get("volume_score")))


def build_trade_evidence(
    context: dict[str, Any],
    thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    active_thresholds = thresholds or {}
    amount_percentile = _amount_percentile(context)
    trend_score = _score(context.get("trend_score"))
    sector_strength = _score(context.get("sector_strength_score"))
    sector_confidence = _score(context.get("sector_sample_confidence"), 0.0)
    sector_breadth = _score(context.get("sector_breadth_score"))
    sector_momentum = _score(context.get("sector_momentum_score"))
    sector_fund_flow_score = _score(context.get("sector_fund_flow_score"))
    moneyflow_support_score = _score(context.get("moneyflow_support_score"))
    raw_moneyflow_support_score = _float(context.get("moneyflow_support_score"))
    dc_net_amount_rate = _float(context.get("dc_net_amount_rate"))
    limit_event = context.get("limit_event")
    limit_open_times = _float(context.get("limit_open_times"))
    chip_cost_85pct = _float(context.get("chip_cost_85pct"))
    chip_winner_rate = _float(context.get("chip_winner_rate"))
    close = _float(context.get("close"))
    risk_score = _score(context.get("risk_score"))
    atr_percentile = _score(context.get("atr_pct_percentile_60d"))
    fundamental_score = _score(context.get("fundamental_score"))
    fundamental_verdict = context.get("fundamental_verdict")
    near_high = _near_recent_high(context, active_thresholds)
    data_evidence_risk = context.get("data_evidence_risk")

    tags: list[EvidenceTag] = []

    if (
        amount_percentile >= _threshold(active_thresholds, "high_volume_percentile", 80.0)
        and near_high
    ):
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

    if (
        _threshold(active_thresholds, "moderate_volume_min_percentile", 55.0)
        <= amount_percentile
        < _threshold(active_thresholds, "high_volume_percentile", 80.0)
        and trend_score >= _threshold(active_thresholds, "trend_volume_confirm_score", 65.0)
    ):
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

    if (
        sector_strength >= _threshold(active_thresholds, "strong_sector_score", 70.0)
        and sector_confidence >= _threshold(active_thresholds, "sector_confidence_min", 0.2)
    ):
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
    elif sector_strength < _threshold(active_thresholds, "weak_sector_score", 50.0):
        tags.append(
            EvidenceTag(
                name="weak_sector_confirmation",
                direction="risk",
                severity="medium",
                rationale="板块强度不足，个股信号容易变成孤立冲高。",
                values={"sector_strength_score": sector_strength},
            )
        )

    if (
        sector_breadth >= _threshold(active_thresholds, "sector_breadth_min", 55.0)
        and sector_momentum >= _threshold(active_thresholds, "sector_momentum_min", 55.0)
    ):
        tags.append(
            EvidenceTag(
                name="sector_breadth_momentum_confirmation",
                direction="support",
                severity="low",
                rationale="板块广度和动量一起抬升，个股更像跟随主线而不是独立波动。",
                values={
                    "sector_breadth_score": sector_breadth,
                    "sector_momentum_score": sector_momentum,
                },
            )
        )
    elif sector_breadth <= _threshold(active_thresholds, "weak_sector_breadth", 45.0):
        tags.append(
            EvidenceTag(
                name="sector_breadth_divergence",
                direction="risk",
                severity="low",
                rationale="板块广度不够时，单票强势更容易变成孤立冲高。",
                values={
                    "sector_breadth_score": sector_breadth,
                    "sector_momentum_score": sector_momentum,
                },
            )
        )

    if (
        sector_fund_flow_score >= _threshold(active_thresholds, "sector_fund_flow_score", 58.0)
        and moneyflow_support_score >= _threshold(active_thresholds, "stock_moneyflow_score", 54.0)
    ):
        tags.append(
            EvidenceTag(
                name="fund_flow_confirmation",
                direction="support",
                severity="low",
                rationale="行业资金和个股净流向同时偏正，说明信号不完全是空心上涨。",
                values={
                    "sector_fund_flow_score": sector_fund_flow_score,
                    "moneyflow_support_score": moneyflow_support_score,
                    "sector_fund_flow_rate": _float(context.get("sector_fund_flow_rate")),
                    "net_mf_amount": _float(context.get("net_mf_amount")),
                },
            )
        )
    elif (
        sector_fund_flow_score <= _threshold(active_thresholds, "weak_sector_fund_flow_score", 42.0)
        and moneyflow_support_score <= _threshold(active_thresholds, "weak_stock_moneyflow_score", 45.0)
    ):
        tags.append(
            EvidenceTag(
                name="fund_flow_divergence",
                direction="risk",
                severity="low",
                rationale="行业和个股资金都偏弱时，走势延续性要打折看待。",
                values={
                    "sector_fund_flow_score": sector_fund_flow_score,
                    "moneyflow_support_score": moneyflow_support_score,
                    "sector_fund_flow_rate": _float(context.get("sector_fund_flow_rate")),
                    "net_mf_amount": _float(context.get("net_mf_amount")),
                },
            )
        )

    if (
        trend_score >= _threshold(active_thresholds, "trend_alignment_score", 75.0)
        and risk_score <= _threshold(active_thresholds, "trend_alignment_max_risk", 35.0)
    ):
        tags.append(
            EvidenceTag(
                name="trend_alignment",
                direction="support",
                severity="medium",
                rationale="均线趋势和风险分数同时支持，说明技术形态相对顺势。",
                values={"trend_score": trend_score, "risk_score": risk_score},
            )
        )
    elif trend_score >= _threshold(active_thresholds, "trend_alignment_score", 75.0) - 5.0:
        tags.append(
            EvidenceTag(
                name="trend_alignment",
                direction="support",
                severity="low",
                rationale="趋势结构基本顺势，但还没到足够强的确认级别。",
                values={"trend_score": trend_score, "risk_score": risk_score},
            )
        )

    if atr_percentile >= _threshold(active_thresholds, "high_volatility_percentile", 80.0):
        tags.append(
            EvidenceTag(
                name="volatility_overheat",
                direction="risk",
                severity="medium",
                rationale="波动分位较高，止损和追高失败概率需要单独观察。",
                values={"atr_pct_percentile_60d": atr_percentile},
            )
        )

    if (
        fundamental_verdict == "weak"
        and amount_percentile
        >= _threshold(active_thresholds, "weak_quality_hot_money_volume", 70.0)
    ):
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

    if raw_moneyflow_support_score is not None and dc_net_amount_rate is not None:
        values = {
            "moneyflow_support_score": raw_moneyflow_support_score,
            "dc_net_amount_rate": dc_net_amount_rate,
        }
        if raw_moneyflow_support_score >= 54.0 and dc_net_amount_rate >= 1.0:
            tags.append(
                EvidenceTag(
                    name="dual_source_moneyflow_confirmation",
                    direction="support",
                    severity="low",
                    rationale="既有资金分数和东财资金流均偏正，资金面形成双源确认。",
                    values=values,
                )
            )
        elif raw_moneyflow_support_score <= 45.0 and dc_net_amount_rate <= -1.0:
            tags.append(
                EvidenceTag(
                    name="dual_source_moneyflow_outflow",
                    direction="risk",
                    severity="high",
                    rationale="两类资金流同时转弱，行动计划不应逆势开仓。",
                    values=values,
                )
            )
        elif (
            raw_moneyflow_support_score >= 54.0 and dc_net_amount_rate <= -1.0
        ) or (
            raw_moneyflow_support_score <= 45.0 and dc_net_amount_rate >= 1.0
        ):
            tags.append(
                EvidenceTag(
                    name="moneyflow_source_divergence",
                    direction="risk",
                    severity="low",
                    rationale="两类资金流方向相反，资金确认不足但不单独阻断计划。",
                    values=values,
                )
            )

    if limit_event == "D":
        tags.append(
            EvidenceTag(
                name="limit_down_risk",
                direction="risk",
                severity="high",
                rationale="当日跌停表明流动性和承接风险显著，禁止生成新的行动计划。",
                values={"limit_event": str(limit_event)},
            )
        )
    if limit_open_times is not None and limit_open_times >= 2.0:
        tags.append(
            EvidenceTag(
                name="repeated_limit_open",
                direction="risk",
                severity="high",
                rationale="反复开板说明封板承接不稳定，禁止生成新的行动计划。",
                values={"limit_open_times": limit_open_times},
            )
        )
    if close is not None and chip_cost_85pct is not None and close < chip_cost_85pct:
        tags.append(
            EvidenceTag(
                name="chip_overhead_pressure",
                direction="risk",
                severity="medium",
                rationale="收盘价低于高位筹码成本，套牢盘压力需要在计划中保留说明。",
                values={"close": close, "chip_cost_85pct": chip_cost_85pct},
            )
        )
    if (
        close is not None
        and chip_cost_85pct is not None
        and chip_winner_rate is not None
        and close >= chip_cost_85pct
        and chip_winner_rate >= 90.0
    ):
        tags.append(
            EvidenceTag(
                name="chip_overheat",
                direction="risk",
                severity="high",
                rationale="获利盘过高且价格站上高位筹码成本，禁止追高生成行动计划。",
                values={
                    "close": close,
                    "chip_cost_85pct": chip_cost_85pct,
                    "chip_winner_rate": chip_winner_rate,
                },
            )
        )

    if isinstance(data_evidence_risk, dict) and data_evidence_risk.get("status") == "blocked":
        reasons = [str(item) for item in data_evidence_risk.get("reasons") or []]
        tags.append(
            EvidenceTag(
                name="data_evidence_incomplete",
                direction="risk",
                severity="high",
                rationale="数据证据未完整到位，禁止把候选升级为可交易计划。",
                values={
                    "status": "blocked",
                    "reasons": "；".join(reasons) or "数据未就绪",
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
            "sector_breadth_score": sector_breadth,
            "sector_momentum_score": sector_momentum,
            "sector_fund_flow_score": sector_fund_flow_score,
            "moneyflow_support_score": moneyflow_support_score,
            "dc_net_amount_rate": dc_net_amount_rate,
            "limit_event": limit_event,
            "limit_open_times": limit_open_times,
            "chip_cost_85pct": chip_cost_85pct,
            "chip_winner_rate": chip_winner_rate,
            "risk_score": risk_score,
            "atr_pct_percentile_60d": atr_percentile,
            "fundamental_score": fundamental_score,
        },
        "thresholds": active_thresholds,
    }
