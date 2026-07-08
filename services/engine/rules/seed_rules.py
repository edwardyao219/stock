from services.engine.rules.models import (
    Condition,
    ConditionGroup,
    PositionRule,
    RuleStatus,
    StopRule,
    StrategyRule,
    StrategyType,
    TakeProfitRule,
    TimeExitRule,
)

MVP_RULES: list[StrategyRule] = [
    StrategyRule(
        id="R001",
        name="强势板块放量突破",
        strategy_type=StrategyType.SHORT_TERM,
        status=RuleStatus.TESTING,
        description="从强势板块里寻找接近新高且放量的个股，次日突破确认后进入。",
        entry=ConditionGroup(
            all=[
                Condition(feature="sector_strength_score", op=">=", value=75),
                Condition(feature="relative_strength_score", op=">=", value=70),
                Condition(feature="amount_percentile_60d", op=">=", value=80),
                Condition(feature="distance_to_20d_high", op="<=", value=0.03),
                Condition(feature="is_st", op="==", value=False),
                Condition(feature="is_suspended", op="==", value=False),
            ]
        ),
        trigger=ConditionGroup(
            all=[
                Condition(field="price", op=">", ref="previous_high"),
                Condition(field="gap_up_pct", op="<=", value=0.06),
                Condition(field="intraday_amount_ratio", op=">=", value=1.2),
            ]
        ),
        stop=StopRule(
            type="composite",
            params={"atr_multiple": 1.5, "structure_ref": "breakout_candle_low", "mode": "tighter"},
        ),
        take_profit=TakeProfitRule(type="trailing", params={"drawdown_from_high_pct": 0.06}),
        time_exit=TimeExitRule(max_holding_days=5, exit_if_no_new_high_days=5),
        position=PositionRule(base_position_pct=0.1, max_position_pct=0.15),
        tags=["sector", "breakout", "short-term"],
    ),
    StrategyRule(
        id="R002",
        name="强势板块缩量回踩",
        strategy_type=StrategyType.SWING,
        status=RuleStatus.TESTING,
        description="在强势板块中寻找趋势向上、回踩均线且缩量的个股。",
        entry=ConditionGroup(
            all=[
                ConditionGroup(
                    any=[
                        Condition(feature="sector_strength_score", op=">=", value=70),
                        Condition(feature="sector_strength_rank_score", op=">=", value=80),
                    ]
                ),
                Condition(feature="trend_score", op=">=", value=65),
                Condition(feature="distance_to_ma20", op=">=", value=-0.04),
                Condition(feature="distance_to_ma20", op="<=", value=0.08),
                Condition(feature="pullback_volume_ratio", op="<=", value=1.1),
                Condition(feature="volume_trap_risk_score", op="<=", value=65),
                Condition(feature="is_st", op="==", value=False),
                Condition(feature="is_suspended", op="==", value=False),
            ]
        ),
        trigger=ConditionGroup(
            all=[
                Condition(field="price", op=">", ref="previous_close"),
                Condition(field="sector_intraday_strength_rank", op="<=", value=10),
            ]
        ),
        stop=StopRule(type="structure", params={"ref": "recent_swing_low"}),
        take_profit=TakeProfitRule(
            type="target_then_trailing",
            params={"first_target_ref": "previous_high", "drawdown_from_high_pct": 0.08},
        ),
        time_exit=TimeExitRule(max_holding_days=20),
        position=PositionRule(base_position_pct=0.08, max_position_pct=0.12),
        tags=["sector", "pullback", "swing"],
    ),
    StrategyRule(
        id="R005",
        name="缩量蓄势突破确认",
        strategy_type=StrategyType.SWING,
        status=RuleStatus.TESTING,
        description="先观察强趋势里的缩量蓄势，避免追当天疯狂放量；次日突破信号日高点才进入。",
        entry=ConditionGroup(
            all=[
                ConditionGroup(
                    any=[
                        Condition(feature="sector_strength_score", op=">=", value=70),
                        Condition(feature="sector_strength_rank_score", op=">=", value=80),
                    ]
                ),
                Condition(feature="trend_score", op=">=", value=75),
                Condition(feature="relative_strength_score", op=">=", value=55),
                Condition(feature="sector_style", op="in", value=["theme", "growth_cycle"]),
                Condition(feature="distance_to_20d_high", op="<=", value=0.08),
                Condition(feature="distance_to_ma20", op=">=", value=-0.03),
                Condition(feature="distance_to_ma20", op="<=", value=0.12),
                Condition(feature="return_20d", op="<=", value=0.25),
                Condition(feature="close_position_in_range", op=">=", value=0.4),
                Condition(feature="upper_shadow_pct", op="<=", value=0.06),
                Condition(feature="volume_trap_risk_score", op="<=", value=60),
                Condition(feature="is_st", op="==", value=False),
                Condition(feature="is_suspended", op="==", value=False),
            ]
        ),
        trigger=ConditionGroup(
            all=[
                Condition(field="price", op=">=", ref="entry_trigger_price"),
            ]
        ),
        stop=StopRule(
            type="composite",
            params={"atr_multiple": 1.6, "structure_ref": "support_level", "mode": "tighter"},
        ),
        take_profit=TakeProfitRule(type="trailing", params={"drawdown_from_high_pct": 0.07}),
        time_exit=TimeExitRule(max_holding_days=16, exit_if_no_new_high_days=4),
        position=PositionRule(base_position_pct=0.06, max_position_pct=0.10),
        tags=["contraction", "anti-trap", "breakout-confirmation"],
    ),
    StrategyRule(
        id="R006",
        name="高强度趋势延续",
        strategy_type=StrategyType.SWING,
        status=RuleStatus.TESTING,
        description="用于液冷、通信、PCB 等强题材趋势段，要求趋势强、不过分高位、波动可控。",
        entry=ConditionGroup(
            all=[
                Condition(feature="sector_style", op="in", value=["theme", "growth_cycle"]),
                ConditionGroup(
                    any=[
                        Condition(feature="sector_strength_score", op=">=", value=65),
                        Condition(feature="sector_strength_rank_score", op=">=", value=80),
                    ]
                ),
                Condition(feature="trend_score", op=">=", value=95),
                Condition(feature="relative_strength_score", op=">=", value=55),
                Condition(feature="return_20d", op=">=", value=0.08),
                Condition(feature="return_20d", op="<=", value=0.30),
                Condition(feature="distance_to_ma10", op=">=", value=-0.02),
                Condition(feature="distance_to_ma10", op="<=", value=0.12),
                Condition(feature="distance_to_ma20", op="<=", value=0.18),
                Condition(feature="close_position_in_range", op=">=", value=0.4),
                Condition(feature="volume_trap_risk_score", op="<=", value=70),
                Condition(feature="is_st", op="==", value=False),
                Condition(feature="is_suspended", op="==", value=False),
            ]
        ),
        trigger=ConditionGroup(
            all=[
                Condition(field="price", op=">=", ref="entry_trigger_price"),
            ]
        ),
        stop=StopRule(
            type="composite",
            params={"atr_multiple": 1.8, "structure_ref": "support_level"},
        ),
        take_profit=TakeProfitRule(
            type="target_then_trailing",
            params={"take_profit_1_r": 1.5, "take_profit_2_r": 3.0, "drawdown_from_high_pct": 0.10},
        ),
        time_exit=TimeExitRule(max_holding_days=12),
        position=PositionRule(base_position_pct=0.05, max_position_pct=0.09),
        tags=["theme", "trend-continuation", "swing"],
    ),
    StrategyRule(
        id="R007",
        name="趋势量能确认",
        strategy_type=StrategyType.SWING,
        status=RuleStatus.TESTING,
        description="把上升趋势和量能确认做成基准策略：要求均线结构、斜率、量能温和确认，同时过滤高位诱多。",
        entry=ConditionGroup(
            all=[
                ConditionGroup(
                    any=[
                        Condition(feature="sector_strength_score", op=">=", value=60),
                        Condition(feature="sector_strength_rank_score", op=">=", value=80),
                    ]
                ),
                Condition(feature="ma_alignment_score", op=">=", value=75),
                Condition(feature="trend_quality_score", op=">=", value=68),
                Condition(feature="volume_confirmation_score", op=">=", value=58),
                Condition(feature="relative_strength_score", op=">=", value=52),
                Condition(feature="return_20d", op=">=", value=0.04),
                Condition(feature="return_20d", op="<=", value=0.28),
                Condition(feature="distance_to_ma20", op=">=", value=-0.02),
                Condition(feature="distance_to_ma20", op="<=", value=0.14),
                Condition(feature="close_position_in_range", op=">=", value=0.45),
                Condition(feature="upper_shadow_pct", op="<=", value=0.06),
                Condition(feature="overheat_score", op="<=", value=72),
                Condition(feature="volume_trap_risk_score", op="<=", value=58),
                Condition(feature="fundamental_verdict", op="!=", value="weak"),
                Condition(feature="is_st", op="==", value=False),
                Condition(feature="is_suspended", op="==", value=False),
            ]
        ),
        trigger=ConditionGroup(
            all=[
                Condition(field="price", op=">=", ref="entry_trigger_price"),
            ]
        ),
        stop=StopRule(
            type="composite",
            params={"atr_multiple": 1.8, "structure_ref": "support_level", "mode": "balanced"},
        ),
        take_profit=TakeProfitRule(
            type="target_then_trailing",
            params={"take_profit_1_r": 1.6, "take_profit_2_r": 3.0, "drawdown_from_high_pct": 0.09},
        ),
        time_exit=TimeExitRule(max_holding_days=14, exit_if_no_new_high_days=5),
        position=PositionRule(base_position_pct=0.06, max_position_pct=0.10),
        tags=["trend", "volume-confirmation", "baseline"],
    ),
    StrategyRule(
        id="R003",
        name="弱势市场防守过滤",
        strategy_type=StrategyType.FILTER,
        status=RuleStatus.TESTING,
        description="市场弱势时降低短线规则仓位，并禁止高开追涨。",
        market_filter=ConditionGroup(
            any=[
                Condition(feature="market_regime", op="==", value="panic"),
                Condition(feature="market_regime", op="==", value="weak_trend"),
            ]
        ),
        entry=ConditionGroup(),
        trigger=ConditionGroup(),
        stop=StopRule(type="time", params={}),
        take_profit=TakeProfitRule(type="none", params={}),
        position=PositionRule(base_position_pct=0.0, max_position_pct=0.0),
        tags=["risk", "market-filter"],
    ),
    StrategyRule(
        id="R004",
        name="板块中期趋势跟随",
        strategy_type=StrategyType.LONG_TERM,
        status=RuleStatus.TESTING,
        description=(
            "先看板块主线，再找个股趋势结构。按 1 个月以上的中期持有来设计，"
            "吃板块主升和趋势延续，不做银行红利防守逻辑。"
        ),
        entry=ConditionGroup(
            all=[
                Condition(feature="fundamental_verdict", op="!=", value="weak"),
                ConditionGroup(
                    any=[
                        Condition(feature="sector_strength_score", op=">=", value=68),
                        Condition(feature="sector_strength_rank_score", op=">=", value=80),
                    ]
                ),
                Condition(feature="sector_breadth_score", op=">=", value=50),
                Condition(feature="sector_momentum_score", op=">=", value=45),
                Condition(feature="relative_strength_score", op=">=", value=62),
                Condition(feature="trend_score", op=">=", value=72),
                Condition(feature="ma_alignment_score", op=">=", value=68),
                Condition(feature="trend_quality_score", op=">=", value=64),
                Condition(feature="volume_confirmation_score", op=">=", value=42),
                Condition(feature="return_20d", op=">=", value=0.02),
                Condition(feature="return_20d", op="<=", value=0.32),
                Condition(feature="distance_to_ma20", op=">=", value=-0.05),
                Condition(feature="distance_to_ma20", op="<=", value=0.12),
                Condition(feature="max_drawdown_20d", op=">=", value=-0.16),
                Condition(feature="overheat_score", op="<=", value=74),
                Condition(feature="volume_trap_risk_score", op="<=", value=62),
                Condition(feature="is_st", op="==", value=False),
                Condition(feature="is_suspended", op="==", value=False),
            ]
        ),
        trigger=ConditionGroup(
            all=[
                Condition(field="price", op=">=", ref="entry_trigger_price"),
            ]
        ),
        stop=StopRule(
            type="composite",
            params={"atr_multiple": 2.5, "structure_ref": "support_level"},
        ),
        take_profit=TakeProfitRule(
            type="trailing",
            params={"drawdown_from_high_pct": 0.12},
        ),
        time_exit=TimeExitRule(max_holding_days=60, exit_if_no_new_high_days=20),
        position=PositionRule(base_position_pct=0.08, max_position_pct=0.14),
        tags=["sector-first", "monthly-trend", "long-term"],
    ),
]
