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
                Condition(feature="sector_strength_score", op=">=", value=70),
                Condition(feature="trend_score", op=">=", value=65),
                Condition(feature="pullback_to_ma20_pct", op="<=", value=0.03),
                Condition(feature="pullback_volume_ratio", op="<=", value=0.8),
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
        name="稳定复利趋势",
        strategy_type=StrategyType.LONG_TERM,
        status=RuleStatus.TESTING,
        description="面向银行等低波动稳定资产，强调趋势、回撤控制和更长持有，不使用短线追突破逻辑。",
        entry=ConditionGroup(
            all=[
                Condition(feature="analysis_framework", op="in", value=["banking_compound"]),
                Condition(feature="fundamental_verdict", op="!=", value="weak"),
                Condition(feature="sector_sample_confidence", op=">=", value=0.05),
                Condition(feature="trend_score", op=">=", value=75),
                Condition(feature="volatility_score", op="<=", value=60),
                Condition(feature="risk_score", op="<=", value=35),
                Condition(feature="max_drawdown_20d", op=">=", value=-0.12),
                Condition(feature="distance_to_ma20", op=">=", value=-0.03),
                Condition(feature="distance_to_20d_low", op=">=", value=0.03),
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
            type="target_then_trailing",
            params={"take_profit_1_r": 2.0, "take_profit_2_r": 4.0, "drawdown_from_high_pct": 0.10},
        ),
        time_exit=TimeExitRule(max_holding_days=None),
        position=PositionRule(base_position_pct=0.12, max_position_pct=0.18),
        tags=["compound", "low-volatility", "long-term"],
    ),
]
