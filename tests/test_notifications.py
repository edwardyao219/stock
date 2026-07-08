from services.notifications.dispatcher import (
    build_candidate_tiers,
    dispatch_candidate_screening,
    dispatch_monthly_trade_summary,
    dispatch_paper_alerts,
    filter_hot_sector_candidates,
    format_candidate_screening_text,
    format_paper_alert_text,
    select_action_candidates,
    select_long_action_candidates,
)
from services.shared.config import get_settings


def _alert() -> dict:
    return {
        "symbol": "603083",
        "alert_type": "stop_loss_touched",
        "severity": "high",
        "price": 10.3,
        "current_stop": 10.34,
        "pnl_pct": -0.01,
        "alert_time": "2026-06-24T10:05:00",
        "message": "603083 盘中触及纸面止损/跟踪止损。",
        "strategy_type": "swing",
        "reasons": ["板块20日主线扩散较好"],
    }


def test_format_paper_alert_text_contains_alert_context() -> None:
    text = format_paper_alert_text([_alert()])

    assert "股票纸面交易预警" in text
    assert "603083 swing stop_loss_touched" in text
    assert "盘中触及纸面止损" in text


def test_format_paper_alert_text_filters_non_hot_short_term_alert() -> None:
    payload = _alert()
    payload["symbol"] = "000002"
    payload["message"] = "000002 历史测试预警"
    payload["strategy_type"] = "short_term"
    payload["reasons"] = []

    text = format_paper_alert_text([payload])

    assert "000002" not in text
    assert text.strip() == "股票纸面交易预警"


def test_dispatch_paper_alerts_skips_non_hot_short_term_alert(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("NOTIFICATION_CHANNELS", "dingtalk")
    monkeypatch.setenv("DINGTALK_WEBHOOK_URL", "")
    payload = _alert()
    payload["symbol"] = "000002"
    payload["strategy_type"] = "short_term"
    payload["reasons"] = []

    results = dispatch_paper_alerts([payload])

    assert results == []
    get_settings.cache_clear()


def test_format_paper_alert_text_contains_intraday_snapshot() -> None:
    payload = _alert()
    payload["intraday_snapshot"] = {
        "label": "放量分歧",
        "session_change_pct": -0.012,
        "open_gap_pct": 0.045,
        "change_from_open_pct": -0.053,
        "intraday_high_gain_pct": 0.082,
        "pullback_from_high_pct": 0.095,
        "range_position": 0.18,
        "volume_pressure_ratio": 1.6,
        "failed_near_limit_up": False,
        "spike_reversed_to_red": True,
    }

    text = format_paper_alert_text([payload])

    assert "盘中快照：放量分歧" in text
    assert "开盘+4.5%" in text
    assert "最高+8.2%" in text
    assert "回撤+9.5%" in text
    assert "冲高翻绿" in text


def test_format_candidate_screening_text_contains_reasons() -> None:
    text = format_candidate_screening_text(
        {
            "requested_feature_date": "2026-06-24",
            "feature_date": "2026-06-24",
            "feature_coverage_ratio": 0.958,
            "universe_size": 100,
            "market_regime": "weak_trend",
            "market_regime_snapshot": {
                "trend_score": 42.0,
                "breadth_score": 35.0,
                "emotion_score": 30.0,
                "emotion_gate": "risk_off",
            },
            "emotion_gate": {
                "state": "risk_off",
                "position_scale": 0.0,
                "notes": ["市场情绪偏弱，不新开仓或只保留观察。"],
            },
            "retired": 1,
            "sector_focus": [
                {
                    "sector": "通信设备",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                }
            ],
            "candidates": [
                {
                    "symbol": "603083",
                    "name": "剑桥科技",
                    "sector": "通信设备",
                    "selection_mode": "formal_strategy",
                    "score": 82.5,
                    "selected_rule_id": "R002",
                    "selected_rule_name": "趋势突破",
                    "reasons": ["入选层级：正式策略命中", "板块20日主线扩散较好", "趋势强度领先"],
                    "risk_flags": ["过热分数偏高72.0"],
                }
            ],
        }
    )

    assert "盘后股票候选" in text
    assert "请求日 2026-06-24" in text
    assert "特征日 2026-06-24" in text
    assert "覆盖 95.8%" in text
    assert "市场环境：weak_trend" not in text
    assert "情绪阀门：risk_off | 仓位系数 0.0" not in text
    assert "603083 剑桥科技 通信设备 正式策略命中 第82.5分" in text
    assert "趋势强度领先" in text
    assert "过热分数偏高72.0" in text


def test_format_candidate_screening_text_keeps_dingtalk_stock_only() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "market_regime": "weak_trend",
            "market_regime_snapshot": {
                "trend_score": 42.0,
                "breadth_score": 35.0,
                "emotion_score": 30.0,
            },
            "emotion_gate": {
                "state": "risk_off",
                "position_scale": 0.0,
                "notes": ["市场情绪偏弱，不新开仓或只保留观察。"],
            },
            "market_participation_snapshot": {
                "participation_score": 35,
                "liquidity_score": 45,
                "leadership_rate": 12,
            },
            "sector_groups": [{"sector": "半导体", "count": 3, "avg_score": 81.2}],
            "sector_focus": [
                {
                    "sector": "半导体",
                    "focus_score": 74,
                    "continuity_score": 75,
                    "resilience_score": 68.2,
                    "leadership_score": 74.8,
                    "avg_return_20d_pct": 10,
                    "positive_ratio": 0.65,
                }
            ],
            "candidates": [
                {
                    "symbol": "603061",
                    "name": "金海通",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 80.7,
                    "selected_rule_id": "R007",
                    "selected_rule_name": "趋势量能确认",
                    "selected_strategy_type": "swing",
                    "reasons": ["板块主线地位靠前", "趋势量能确认"],
                    "risk_flags": [],
                }
            ],
        }
    )

    assert "盘后股票候选" in text
    assert "603061 金海通 半导体" in text
    assert "市场环境" not in text
    assert "情绪阀门" not in text
    assert "资金参与" not in text
    assert "板块分布" not in text
    assert "板块观察" not in text


def test_format_candidate_screening_text_prioritizes_long_term_candidates() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "sector_focus": [
                {
                    "sector": "PCB",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                },
                {
                    "sector": "通信设备",
                    "focus_score": 68,
                    "continuity_score": 66,
                    "avg_return_20d_pct": 8.5,
                    "positive_ratio": 0.60,
                },
            ],
            "candidates": [
                {
                    "symbol": "600183",
                    "name": "长期回调票",
                    "sector": "PCB",
                    "selection_mode": "formal_strategy",
                    "score": 86.4,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["先看板块主线", "板块20日主线扩散较好"],
                    "risk_flags": [],
                },
                {
                    "symbol": "603083",
                    "name": "短线候选",
                    "sector": "通信设备",
                    "selection_mode": "formal_strategy",
                    "score": 82.5,
                    "selected_rule_id": "R002",
                    "selected_rule_name": "趋势突破",
                    "selected_strategy_type": "short_term",
                    "reasons": ["板块20日主线扩散较好", "趋势强度领先"],
                    "risk_flags": [],
                },
            ],
        }
    )

    assert "长期/波段主池" in text
    assert "短线观察池" in text
    assert "600183 长期回调票 PCB 中期趋势 正式策略命中 第86.4分" in text
    assert "603083 短线候选 通信设备 短线观察 正式策略命中 第82.5分" in text
    assert text.index("600183 长期回调票") < text.index("短线观察池")


def test_format_candidate_screening_text_uses_action_candidates_when_present() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-30",
            "universe_size": 5000,
            "retired": 0,
            "sector_focus": [
                {
                    "sector": "半导体",
                    "focus_score": 76,
                    "continuity_score": 74,
                    "avg_return_20d_pct": 11,
                    "positive_ratio": 0.66,
                }
            ],
            "action_candidates": [
                {
                    "symbol": "002156",
                    "name": "通富微电",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 84.9,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["低维主线：板块趋势和个股强度共振", "科技成长主线顺势"],
                    "risk_flags": [],
                }
            ],
            "star_candidates": [
                {
                    "symbol": "688802",
                    "name": "沐曦股份",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 90.5,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["科技成长主线顺势"],
                    "risk_flags": [],
                }
            ],
            "candidates": [
                {
                    "symbol": "002156",
                    "name": "通富微电",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 84.9,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["低维主线：板块趋势和个股强度共振", "科技成长主线顺势"],
                    "risk_flags": [],
                },
                {
                    "symbol": "600900",
                    "name": "高位观察",
                    "sector": "火力发电",
                    "selection_mode": "formal_strategy",
                    "score": 92.0,
                    "selected_rule_id": "R002",
                    "selected_rule_name": "趋势突破",
                    "selected_strategy_type": "swing",
                    "reasons": ["板块20日主线扩散较好"],
                    "risk_flags": ["距离MA20偏远17.00%"],
                },
                {
                    "symbol": "688802",
                    "name": "沐曦股份",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 90.5,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["科技成长主线顺势"],
                    "risk_flags": [],
                },
            ],
        }
    )

    assert "行动候选（普通版最多3只）" in text
    assert "002156 通富微电 半导体" in text
    assert "600900" not in text
    assert "688802" not in text
    assert "观察池 3 只在 Web" in text
    assert "科创池 1 只在 Web" in text


def test_format_candidate_screening_text_prefers_long_action_candidates() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-30",
            "universe_size": 5000,
            "retired": 0,
            "sector_focus": [
                {
                    "sector": "半导体",
                    "focus_score": 76,
                    "continuity_score": 74,
                    "avg_return_20d_pct": 11,
                    "positive_ratio": 0.66,
                }
            ],
            "long_action_candidates": [
                {
                    "symbol": "600002",
                    "name": "中期强者",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 82.0,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["中期强者：相对强度或板块扩散足够强"],
                    "risk_flags": [],
                }
            ],
            "action_candidates": [
                {
                    "symbol": "002156",
                    "name": "普通行动",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 84.9,
                    "selected_rule_id": "R002",
                    "selected_rule_name": "趋势突破",
                    "selected_strategy_type": "short_term",
                    "reasons": ["低维主线：板块趋势和个股强度共振"],
                    "risk_flags": [],
                },
                {
                    "symbol": "600002",
                    "name": "中期强者",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 82.0,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["中期强者：相对强度或板块扩散足够强"],
                    "risk_flags": [],
                },
            ],
            "candidates": [],
        }
    )

    assert "中期行动候选（最多3只）" in text
    assert "600002 中期强者 半导体" in text
    assert "002156" not in text
    assert "普通行动候选 2 只在 Web" in text


def test_format_candidate_screening_text_pushes_core_and_learning_tiers() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "sector_focus": [
                {
                    "sector": "半导体",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                }
            ],
            "candidate_tiers": {
                "core_action": [
                    {
                        "symbol": "600002",
                        "name": "核心票",
                        "sector": "半导体",
                        "selection_mode": "formal_strategy",
                        "score": 82.0,
                        "selected_rule_id": "R004",
                        "selected_rule_name": "板块中期趋势跟随",
                        "selected_strategy_type": "long_term",
                        "reasons": ["中期强者：相对强度或板块扩散足够强"],
                        "risk_flags": [],
                        "tier_reason": "板块和个股趋势同时在线，作为核心行动候选。",
                    }
                ],
                "watch_wait": [
                    {
                        "symbol": "002156",
                        "name": "观察票",
                        "sector": "半导体",
                        "selection_mode": "formal_strategy",
                        "score": 84.9,
                        "selected_strategy_type": "swing",
                        "reasons": ["低维主线：板块趋势和个股强度共振"],
                        "risk_flags": ["距离MA20偏远17.00%"],
                    }
                ],
                "risk_reject": [],
            },
            "action_candidates": [
                {
                    "symbol": "002156",
                    "name": "观察票",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 84.9,
                    "selected_strategy_type": "swing",
                    "reasons": ["低维主线：板块趋势和个股强度共振"],
                    "risk_flags": [],
                }
            ],
            "candidates": [],
        }
    )

    assert "钉钉分层推送" in text
    assert "核心行动（交易重点，最多3只）" in text
    assert "600002 核心票" in text
    assert "学习观察（非买点，盘中验证）" in text
    assert "002156 观察票" in text
    assert "不代表买点" in text


def test_select_action_candidates_keeps_low_noise_normal_pool_without_filling_risky() -> None:
    candidates = [
        {
            "symbol": "002156",
            "selection_mode": "formal_strategy",
            "score": 84.9,
            "selected_strategy_type": "long_term",
            "reasons": ["低维主线：板块趋势和个股强度共振"],
            "risk_flags": [],
        },
        {
            "symbol": "600584",
            "selection_mode": "formal_strategy",
            "score": 82.0,
            "selected_strategy_type": "swing",
            "reasons": ["板块中期趋势延续性较好"],
            "risk_flags": [],
        },
        {
            "symbol": "600900",
            "selection_mode": "formal_strategy",
            "score": 92.0,
            "selected_strategy_type": "swing",
            "reasons": ["板块20日主线扩散较好"],
            "risk_flags": ["距离MA20偏远17.00%"],
        },
        {
            "symbol": "688802",
            "selection_mode": "formal_strategy",
            "score": 90.0,
            "selected_strategy_type": "long_term",
            "reasons": ["科技成长主线顺势"],
            "risk_flags": [],
        },
    ]

    selected = select_action_candidates({"candidates": candidates}, candidates, max_items=3)

    assert [item["symbol"] for item in selected] == ["002156", "600584"]


def test_select_action_candidates_prefers_long_horizon_strength_reason() -> None:
    candidates = [
        {
            "symbol": "600001",
            "selection_mode": "formal_strategy",
            "score": 91.0,
            "selected_strategy_type": "short_term",
            "reasons": ["趋势+相对强度因子仍有支撑"],
            "risk_flags": [],
        },
        {
            "symbol": "600002",
            "sector": "半导体",
            "selection_mode": "formal_strategy",
            "score": 82.0,
            "selected_strategy_type": "short_term",
            "reasons": ["中期强者：相对强度或板块扩散足够强"],
            "risk_flags": [],
        },
    ]

    selected = select_action_candidates({"candidates": candidates}, candidates, max_items=1)

    assert [item["symbol"] for item in selected] == ["600002"]


def test_select_long_action_candidates_requires_market_participation() -> None:
    candidates = [
        {
            "symbol": "600002",
            "sector": "半导体",
            "selection_mode": "formal_strategy",
            "score": 82.0,
            "selected_strategy_type": "long_term",
            "reasons": ["中期强者：相对强度或板块扩散足够强"],
            "risk_flags": [],
        }
    ]

    weak_discovery = {
        "candidates": candidates,
        "market_participation_snapshot": {
            "participation_score": 41.0,
            "liquidity_score": 31.0,
        },
    }
    strong_discovery = {
        "candidates": candidates,
        "market_participation_snapshot": {
            "participation_score": 48.0,
            "liquidity_score": 38.0,
        },
    }

    assert select_long_action_candidates(weak_discovery, candidates, max_items=3) == []
    assert [
        item["symbol"]
        for item in select_long_action_candidates(strong_discovery, candidates, max_items=3)
    ] == ["600002"]


def test_select_long_action_candidates_requires_trend_style_context() -> None:
    candidates = [
        {
            "symbol": "600001",
            "sector": "食品饮料",
            "sector_style": "consumer_quality",
            "selection_mode": "formal_strategy",
            "score": 99.0,
            "selected_strategy_type": "long_term",
            "reasons": ["中期强者：相对强度或板块扩散足够强"],
            "risk_flags": [],
        },
        {
            "symbol": "600002",
            "sector": "半导体",
            "sector_style": "growth_cycle",
            "selection_mode": "formal_strategy",
            "score": 82.0,
            "selected_strategy_type": "long_term",
            "reasons": ["中期强者：相对强度或板块扩散足够强"],
            "risk_flags": [],
        },
        {
            "symbol": "600003",
            "sector": "综合类",
            "sector_style": "unknown",
            "selection_mode": "formal_strategy",
            "score": 98.0,
            "selected_strategy_type": "long_term",
            "reasons": ["中期强者：相对强度或板块扩散足够强"],
            "risk_flags": [],
        },
    ]
    discovery = {
        "candidates": candidates,
        "market_participation_snapshot": {
            "participation_score": 55.0,
            "liquidity_score": 45.0,
        },
    }

    selected = select_long_action_candidates(discovery, candidates, max_items=3)

    assert [item["symbol"] for item in selected] == ["600002"]


def test_select_long_action_candidates_accepts_volume_confirmed_extension() -> None:
    candidates = [
        {
            "symbol": "600002",
            "sector": "半导体",
            "sector_style": "growth_cycle",
            "selection_mode": "formal_strategy",
            "score": 82.0,
            "selected_strategy_type": "long_term",
            "reasons": [
                "中期扩展观察：趋势连续性和相对强度接近中期强者",
                "板块中期趋势延续性较好",
                "量能未明显失速",
                "价格未明显远离MA20",
            ],
            "risk_flags": [],
            "volume_confirmation_score": 52.0,
            "price_volume_trend_score": 58.0,
            "return_20d": 0.14,
            "distance_to_ma20": 0.04,
        }
    ]
    discovery = {
        "candidates": candidates,
        "market_participation_snapshot": {
            "participation_score": 55.0,
            "liquidity_score": 45.0,
        },
    }

    selected = select_long_action_candidates(discovery, candidates, max_items=3)

    assert [item["symbol"] for item in selected] == ["600002"]


def test_select_long_action_candidates_rejects_extension_without_volume_confirmation() -> None:
    candidates = [
        {
            "symbol": "600002",
            "sector": "半导体",
            "sector_style": "growth_cycle",
            "selection_mode": "formal_strategy",
            "score": 92.0,
            "selected_strategy_type": "long_term",
            "reasons": [
                "中期扩展观察：趋势连续性和相对强度接近中期强者",
                "板块中期趋势延续性较好",
                "价格未明显远离MA20",
            ],
            "risk_flags": [],
            "volume_confirmation_score": 36.0,
            "price_volume_trend_score": 40.0,
            "return_20d": 0.14,
            "distance_to_ma20": 0.04,
        }
    ]
    discovery = {
        "candidates": candidates,
        "market_participation_snapshot": {
            "participation_score": 55.0,
            "liquidity_score": 45.0,
        },
    }

    assert select_long_action_candidates(discovery, candidates, max_items=3) == []


def test_build_candidate_tiers_separates_core_watch_and_risk() -> None:
    candidates = [
        {
            "symbol": "600002",
            "name": "中期强者",
            "sector": "半导体",
            "suggested_horizon_days": 10,
            "horizon_reason": "风格周期：growth_cycle偏10日观察，科技成长先看承接延续",
            "selection_mode": "formal_strategy",
            "score": 82.0,
            "selected_strategy_type": "long_term",
            "reasons": ["中期强者：相对强度或板块扩散足够强"],
            "risk_flags": [],
        },
        {
            "symbol": "002156",
            "name": "等待回踩",
            "sector": "半导体",
            "suggested_horizon_days": 10,
            "horizon_reason": "风格周期：growth_cycle偏10日观察，科技成长先看承接延续",
            "selection_mode": "formal_strategy",
            "score": 84.9,
            "selected_strategy_type": "swing",
            "reasons": ["低维主线：板块趋势和个股强度共振"],
            "risk_flags": ["距离MA20偏远17.00%"],
        },
        {
            "symbol": "600673",
            "name": "潜力观察",
            "sector": "综合类",
            "selection_mode": "potential_watch",
            "score": 91.0,
            "selected_strategy_type": "watch_breakout",
            "reasons": ["潜力观察：个股启动但板块未确认，只观察不行动"],
            "risk_flags": [],
        },
        {
            "symbol": "600900",
            "name": "过热样本",
            "sector": "电力",
            "selection_mode": "formal_strategy",
            "score": 92.0,
            "selected_strategy_type": "swing",
            "reasons": ["趋势+相对强度因子仍有支撑"],
            "risk_flags": ["过热分数偏高78.0", "放量诱多风险"],
        },
    ]
    discovery = {
        "candidates": candidates,
        "action_candidates": [candidates[0]],
        "long_action_candidates": [candidates[0]],
    }

    tiers = build_candidate_tiers(discovery)

    assert [item["symbol"] for item in tiers["core_action"]] == ["600002"]
    assert [item["symbol"] for item in tiers["watch_wait"]] == ["002156", "600673"]
    assert [item["symbol"] for item in tiers["risk_reject"]] == ["600900"]
    assert tiers["core_action"][0]["candidate_tier"] == "core_action"
    assert "核心行动" in tiers["core_action"][0]["candidate_tier_label"]
    assert "10日观察" in tiers["core_action"][0]["tier_reason"]
    assert "等回踩" in tiers["watch_wait"][0]["tier_reason"]
    assert "10日观察" in tiers["watch_wait"][0]["tier_reason"]
    assert "风险" in tiers["risk_reject"][0]["candidate_tier_label"]


def test_build_candidate_tiers_explains_when_core_action_is_empty() -> None:
    candidates = [
        {
            "symbol": "002669",
            "sector": "化工原料",
            "selection_mode": "potential_watch",
            "selected_strategy_type": "watch_breakout",
            "score": 66.9,
            "risk_flags": [],
            "reasons": ["潜力观察：个股启动但板块未确认，只观察不行动"],
        },
        {
            "symbol": "600360",
            "sector": "半导体",
            "selection_mode": "observation",
            "selected_strategy_type": "watch_breakout",
            "score": 67.0,
            "risk_flags": ["板块20日涨幅/扩散已偏拥挤", "放量诱多风险61.5"],
            "reasons": ["入选层级：观察候选"],
        },
    ]

    tiers = build_candidate_tiers({"candidates": candidates}, candidates)

    assert tiers["core_action"] == []
    assert tiers["summary"]["core_block_reason"] == (
        "没有核心行动：候选仍以潜力观察/买点未确认为主，正式票又带较重风险。"
    )


def test_build_candidate_tiers_blocks_market_beta_core_when_market_is_weak() -> None:
    candidate = {
        "symbol": "601336",
        "name": "新华保险",
        "sector": "保险",
        "sector_style": "market_beta",
        "suggested_horizon_days": 5,
        "horizon_reason": "风格周期：market_beta偏5日观察，需结合指数和成交额",
        "selection_mode": "formal_strategy",
        "score": 86.8,
        "selected_strategy_type": "swing",
        "reasons": ["趋势强度领先", "相对强度领先市场"],
        "risk_flags": [],
    }
    discovery = {
        "candidates": [candidate],
        "long_action_candidates": [candidate],
        "market_regime": "weak_trend",
        "market_regime_snapshot": {
            "breadth_score": 34.0,
            "emotion_gate": "risk_off",
        },
        "market_participation_snapshot": {
            "participation_score": 41.0,
            "liquidity_score": 31.0,
        },
    }

    tiers = build_candidate_tiers(discovery)

    assert tiers["core_action"] == []
    assert [item["symbol"] for item in tiers["watch_wait"]] == ["601336"]
    assert "市场弹性" in tiers["watch_wait"][0]["tier_reason"]
    assert "弱市缩量" in tiers["watch_wait"][0]["tier_reason"]
    assert tiers["summary"]["core_block_reason"] == (
        "没有核心行动：市场弹性候选遇到弱市缩量，先降为观察。"
    )


def test_build_candidate_tiers_blocks_all_core_when_market_stress_is_risk_off() -> None:
    candidate = {
        "symbol": "603061",
        "name": "金海通",
        "sector": "半导体",
        "sector_style": "growth_cycle",
        "suggested_horizon_days": 10,
        "horizon_reason": "风格周期：growth_cycle偏10日观察，科技成长先看承接延续",
        "selection_mode": "formal_strategy",
        "score": 88.0,
        "selected_strategy_type": "long_term",
        "reasons": ["低维主线：板块趋势和个股强度共振"],
        "risk_flags": [],
    }
    discovery = {
        "candidates": [candidate],
        "long_action_candidates": [candidate],
        "market_stress": {
            "stress_status": "risk_off",
            "risk_action_label": "停止扩散，只做观察和风控",
            "stress_reasons": ["上涨占比仅18%，市场宽度明显不足"],
        },
    }

    tiers = build_candidate_tiers(discovery)

    assert tiers["core_action"] == []
    assert [item["symbol"] for item in tiers["watch_wait"]] == ["603061"]
    assert "大盘压力大" in tiers["watch_wait"][0]["tier_reason"]
    assert "停止扩散" in tiers["watch_wait"][0]["tier_reason"]
    assert tiers["summary"]["core_block_reason"] == (
        "没有核心行动：大盘压力大，停止扩散，只做观察和风控。"
    )


def test_build_candidate_tiers_adds_sector_watch_basket_when_market_stress_is_risk_off() -> None:
    core = {
        "symbol": "603061",
        "name": "金海通",
        "sector": "半导体",
        "sector_style": "growth_cycle",
        "selection_mode": "formal_strategy",
        "score": 88.0,
        "selected_strategy_type": "long_term",
        "reasons": ["低维主线：板块趋势和个股强度共振"],
        "risk_flags": [],
    }
    growth_first = {
        "symbol": "002558",
        "name": "巨人网络",
        "sector": "互联网",
        "sector_style": "growth_cycle",
        "selection_mode": "potential_watch",
        "score": 86.0,
        "selected_strategy_type": "watch_breakout",
        "reasons": ["潜力观察：个股启动但板块未确认", "成交量开始确认"],
        "risk_flags": [],
    }
    growth_second = {
        "symbol": "300308",
        "name": "中际旭创",
        "sector": "通信设备",
        "sector_style": "growth_cycle",
        "selection_mode": "potential_watch",
        "score": 82.0,
        "selected_strategy_type": "watch_breakout",
        "reasons": ["潜力观察：个股启动但板块未确认", "板块20日主线扩散较好"],
        "risk_flags": [],
    }
    growth_third = {
        "symbol": "600584",
        "name": "长电科技",
        "sector": "半导体",
        "sector_style": "growth_cycle",
        "selection_mode": "potential_watch",
        "score": 79.0,
        "selected_strategy_type": "watch_breakout",
        "reasons": ["潜力观察：个股启动但板块未确认"],
        "risk_flags": [],
    }
    cyclical = {
        "symbol": "600111",
        "name": "北方稀土",
        "sector": "小金属",
        "sector_style": "cyclical",
        "selection_mode": "potential_watch",
        "score": 81.0,
        "selected_strategy_type": "watch_breakout",
        "reasons": ["潜力观察：个股启动但板块未确认", "趋势+相对强度因子仍有支撑"],
        "risk_flags": [],
    }
    consumer = {
        "symbol": "600519",
        "name": "贵州茅台",
        "sector": "白酒",
        "sector_style": "consumer_quality",
        "selection_mode": "potential_watch",
        "score": 92.0,
        "selected_strategy_type": "watch_breakout",
        "reasons": ["潜力观察：个股启动但板块未确认"],
        "risk_flags": [],
    }
    discovery = {
        "candidates": [core, growth_first, growth_second, growth_third, cyclical, consumer],
        "long_action_candidates": [core],
        "market_stress": {
            "stress_status": "risk_off",
            "risk_action_label": "停止扩散，只做观察和风控",
            "stress_reasons": ["上涨占比仅18%，市场宽度明显不足"],
        },
        "style_gate_policy": {
            "rows": [
                {
                    "style": "growth_cycle",
                    "label": "科技成长",
                    "status": "upgrade_allowed",
                    "status_label": "允许潜力升级",
                    "summary": "科技成长近期回放占优，可放网页端重点观察。",
                },
                {
                    "style": "cyclical",
                    "label": "周期资源",
                    "status": "upgrade_allowed",
                    "status_label": "允许潜力升级",
                    "summary": "周期资源近期回放修复，可放网页端重点观察。",
                },
                {
                    "style": "consumer_quality",
                    "label": "消费质量",
                    "status": "observe_only",
                    "status_label": "只观察",
                    "summary": "消费质量先只观察。",
                },
            ]
        },
    }

    tiers = build_candidate_tiers(discovery, max_core_items=3)

    assert tiers["core_action"] == []
    assert [item["symbol"] for item in tiers["sector_watch"]] == [
        "002558",
        "300308",
        "600111",
        "600519",
    ]
    assert "600584" not in [item["symbol"] for item in tiers["sector_watch"]]
    assert all(item["candidate_tier"] == "sector_watch" for item in tiers["sector_watch"])
    assert "防守阶段板块观察" in tiers["sector_watch"][0]["tier_reason"]
    assert "交给人盘中判断" in tiers["sector_watch"][0]["tier_reason"]
    assert "只观察" in tiers["sector_watch"][-1]["tier_reason"]
    assert tiers["summary"]["sector_watch_count"] == 4


def test_build_candidate_tiers_limits_core_to_one_when_market_stress_is_caution() -> None:
    first = {
        "symbol": "603061",
        "name": "金海通",
        "sector": "半导体",
        "sector_style": "growth_cycle",
        "selection_mode": "formal_strategy",
        "score": 88.0,
        "selected_strategy_type": "long_term",
        "reasons": ["低维主线：板块趋势和个股强度共振"],
        "risk_flags": [],
    }
    second = {
        "symbol": "600360",
        "name": "华微电子",
        "sector": "半导体",
        "sector_style": "growth_cycle",
        "selection_mode": "formal_strategy",
        "score": 84.0,
        "selected_strategy_type": "swing",
        "reasons": ["中期强者：相对强度或板块扩散足够强"],
        "risk_flags": [],
    }
    discovery = {
        "candidates": [first, second],
        "long_action_candidates": [first, second],
        "market_stress": {
            "stress_status": "caution",
            "risk_action_label": "降低频率，等盘中确认",
            "stress_reasons": ["上涨占比34%，弱势面较宽"],
        },
    }

    tiers = build_candidate_tiers(discovery, max_core_items=3)

    assert [item["symbol"] for item in tiers["core_action"]] == ["603061"]
    assert [item["symbol"] for item in tiers["watch_wait"]] == ["600360"]
    assert "大盘谨慎" in tiers["watch_wait"][0]["tier_reason"]
    assert "只保留最强一只" in tiers["watch_wait"][0]["tier_reason"]


def test_build_candidate_tiers_keeps_startup_preheat_as_watch_wait() -> None:
    candidates = [
        {
            "symbol": "002558",
            "sector": "互联网",
            "suggested_horizon_days": 10,
            "horizon_reason": "风格周期：growth_cycle偏10日观察，科技成长先看承接延续",
            "selection_mode": "potential_watch",
            "selected_strategy_type": "watch_breakout",
            "score": 70.0,
            "startup_signal_score": 82.5,
            "startup_signal_label": "启动观察",
            "risk_flags": [],
            "reasons": [
                "启动前夜：T-1量价修复，20日涨幅仍不高，只观察次日承接",
                "成交量开始确认：温和放量配合价格修复，但未进入核心行动",
            ],
        }
    ]

    tiers = build_candidate_tiers({"candidates": candidates}, candidates)

    assert tiers["core_action"] == []
    assert [item["symbol"] for item in tiers["watch_wait"]] == ["002558"]
    assert tiers["watch_wait"][0]["candidate_tier"] == "watch_wait"
    assert "启动前夜" in tiers["watch_wait"][0]["tier_reason"]
    assert "启动观察82.5分" in tiers["watch_wait"][0]["tier_reason"]
    assert "不代表买点" in tiers["watch_wait"][0]["tier_reason"]
    assert "10日观察" in tiers["watch_wait"][0]["tier_reason"]


def test_build_candidate_tiers_attaches_style_gate_to_startup_preheat() -> None:
    candidates = [
        {
            "symbol": "002558",
            "sector": "互联网",
            "sector_style": "growth_cycle",
            "selection_mode": "potential_watch",
            "selected_strategy_type": "watch_breakout",
            "score": 70.0,
            "risk_flags": [],
            "reasons": [
                "启动前夜：T-1量价修复，20日涨幅仍不高，只观察次日承接",
                "成交量开始确认：温和放量配合价格修复，但未进入核心行动",
            ],
        },
        {
            "symbol": "600001",
            "sector": "食品饮料",
            "sector_style": "consumer_quality",
            "selection_mode": "potential_watch",
            "selected_strategy_type": "watch_breakout",
            "score": 68.0,
            "risk_flags": [],
            "reasons": [
                "启动前夜：T-1量价修复，20日涨幅仍不高，只观察次日承接",
                "成交量开始确认：温和放量配合价格修复，但未进入核心行动",
            ],
        },
    ]

    tiers = build_candidate_tiers(
        {
            "candidates": candidates,
            "startup_preheat_policy": {
                "scope": "startup_preheat",
                "horizon": 5,
                "rows": [
                    {
                        "style": "growth_cycle",
                        "label": "科技成长",
                        "status": "upgrade_allowed",
                        "status_label": "允许潜力升级",
                        "summary": "科技成长启动前夜可盘中重点观察，不代表买点。",
                    },
                    {
                        "style": "consumer_quality",
                        "label": "消费质量",
                        "status": "stand_down",
                        "status_label": "暂不升级",
                        "summary": "消费质量启动前夜近期不占优，暂不升级。",
                    },
                ],
            },
        },
        candidates,
    )

    rows = {item["symbol"]: item for item in tiers["watch_wait"]}
    assert rows["002558"]["style_gate_status"] == "upgrade_allowed"
    assert rows["002558"]["style_gate_label"] == "允许潜力升级"
    assert rows["002558"]["style_gate_scope"] == "startup_preheat"
    assert rows["002558"]["style_gate_horizon"] == 5
    assert "科技成长启动前夜可盘中重点观察" in rows["002558"]["style_gate_reason"]
    assert "不代表买点" in rows["002558"]["tier_reason"]
    assert rows["600001"]["style_gate_status"] == "stand_down"
    assert "消费质量启动前夜近期不占优" in rows["600001"]["style_gate_reason"]


def test_format_candidate_screening_text_pushes_layered_learning_sections() -> None:
    core = {
        "symbol": "603005",
        "name": "核心票",
        "sector": "半导体",
        "selection_mode": "formal_strategy",
        "score": 82.0,
        "selected_rule_id": "R007",
        "selected_rule_name": "趋势量能确认",
        "selected_strategy_type": "swing",
        "reasons": ["低维主线：板块趋势和个股强度共振"],
        "risk_flags": [],
        "tier_reason": "板块和个股趋势同时在线，作为核心行动候选；盘中仍看承接。",
    }
    startup = {
        "symbol": "002558",
        "name": "启动前夜",
        "sector": "互联网",
        "selection_mode": "potential_watch",
        "score": 70.0,
        "selected_strategy_type": "watch_breakout",
        "reasons": [
            "启动前夜：T-1量价修复，20日涨幅仍不高，只观察次日承接",
            "成交量开始确认：温和放量配合价格修复，但未进入核心行动",
        ],
        "risk_flags": [],
        "tier_reason": "启动前夜：T-1量价已经修复，但还没到核心买点，先盯次日承接。",
    }
    risky = {
        "symbol": "600900",
        "name": "风险样本",
        "sector": "电力",
        "selection_mode": "formal_strategy",
        "score": 77.0,
        "selected_strategy_type": "swing",
        "reasons": ["趋势+相对强度因子仍有支撑"],
        "risk_flags": ["过热分数偏高78.0", "放量诱多风险"],
        "tier_reason": "风险信号偏重：过热分数偏高78.0；放量诱多风险，暂不纳入行动池。",
    }

    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "candidates": [core, startup, risky],
            "candidate_tiers": {
                "core_action": [core],
                "watch_wait": [startup],
                "risk_reject": [risky],
                "summary": {"core_block_reason": None},
            },
        }
    )

    assert "钉钉分层推送" in text
    assert "核心行动（交易重点，最多3只）" in text
    assert "学习观察（非买点，盘中验证）" in text
    assert "暂不升级/风险理由" in text
    assert "603005 核心票" in text
    assert "002558 启动前夜" in text
    assert "600900 风险样本" in text
    assert "不代表买点" in text
    assert "只在 Web" not in text


def test_format_candidate_screening_text_prioritizes_style_gate_watch_items() -> None:
    upgrade = {
        "symbol": "002558",
        "name": "启动前夜",
        "sector": "互联网",
        "sector_style": "growth_cycle",
        "selection_mode": "potential_watch",
        "selected_strategy_type": "watch_breakout",
        "score": 60.0,
        "selected_rule_id": "WATCH",
        "selected_rule_name": "启动观察",
        "reasons": ["启动前夜：T-1量价修复，先观察次日承接"],
        "risk_flags": [],
        "style_gate_status": "upgrade_allowed",
        "style_gate_label": "允许潜力升级",
        "style_gate_reason": "科技成长启动前夜可盘中重点观察，不代表买点。",
        "tier_reason": "启动前夜：先盯承接。",
    }
    observe = {
        "symbol": "300001",
        "name": "只观察",
        "sector": "软件服务",
        "sector_style": "growth_cycle",
        "selection_mode": "potential_watch",
        "selected_strategy_type": "watch_breakout",
        "score": 88.0,
        "selected_rule_id": "WATCH",
        "selected_rule_name": "观察",
        "reasons": ["潜力观察：个股启动但板块未确认"],
        "risk_flags": [],
        "style_gate_status": "observe_only",
        "style_gate_label": "只观察",
        "style_gate_reason": "科技成长潜力观察近期有修复，只做网页端观察。",
        "tier_reason": "只观察承接。",
    }
    stand_down = {
        "symbol": "600001",
        "name": "暂缓观察",
        "sector": "食品饮料",
        "sector_style": "consumer_quality",
        "selection_mode": "potential_watch",
        "selected_strategy_type": "watch_breakout",
        "score": 96.0,
        "selected_rule_id": "WATCH",
        "selected_rule_name": "观察",
        "reasons": ["潜力观察：个股启动但板块未确认"],
        "risk_flags": [],
        "style_gate_status": "stand_down",
        "style_gate_label": "暂不升级",
        "style_gate_reason": "消费质量启动前夜近期不占优，暂不升级。",
        "tier_reason": "暂缓升级。",
    }

    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "candidate_tiers": {
                "core_action": [],
                "watch_wait": [stand_down, observe, upgrade],
                "risk_reject": [],
                "summary": {"core_block_reason": "没有核心行动：先观察承接。"},
            },
        }
    )

    assert text.index("1. 002558 启动前夜") < text.index("2. 300001 只观察")
    assert text.index("2. 300001 只观察") < text.index("3. 600001 暂缓观察")
    assert "门控：允许潜力升级 / 科技成长启动前夜可盘中重点观察，不代表买点。" in text
    assert "门控：暂不升级 / 消费质量启动前夜近期不占优，暂不升级。" in text


def test_format_candidate_screening_text_pushes_learning_tiers_without_core() -> None:
    startup = {
        "symbol": "002558",
        "name": "启动前夜",
        "sector": "互联网",
        "selection_mode": "potential_watch",
        "score": 70.0,
        "selected_strategy_type": "watch_breakout",
        "reasons": ["启动前夜：T-1量价修复，先观察次日承接"],
        "risk_flags": [],
        "tier_reason": "启动前夜：T-1量价已经修复，但还没到核心买点。",
    }
    risky = {
        "symbol": "600900",
        "name": "风险样本",
        "sector": "电力",
        "selection_mode": "formal_strategy",
        "score": 77.0,
        "selected_strategy_type": "swing",
        "reasons": ["趋势+相对强度因子仍有支撑"],
        "risk_flags": ["过热分数偏高78.0"],
        "tier_reason": "风险信号偏重：过热分数偏高78.0，暂不纳入行动池。",
    }

    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "candidate_tiers": {
                "core_action": [],
                "watch_wait": [startup],
                "risk_reject": [risky],
                "summary": {
                    "core_block_reason": "没有核心行动：当前候选都是潜力观察。"
                },
            },
            "candidates": [],
        }
    )

    assert "钉钉分层推送" in text
    assert "核心行动（交易重点，最多3只）" in text
    assert "暂无候选" in text
    assert "没有核心行动：当前候选都是潜力观察。" in text
    assert "002558 启动前夜" in text
    assert "暂不升级/风险理由" in text
    assert "600900 风险样本" in text
    assert "只在 Web" not in text


def test_format_candidate_screening_text_shows_defensive_sector_watch_section() -> None:
    sector_watch = {
        "symbol": "002558",
        "name": "巨人网络",
        "sector": "互联网",
        "selection_mode": "potential_watch",
        "score": 86.0,
        "selected_strategy_type": "watch_breakout",
        "reasons": ["潜力观察：个股启动但板块未确认"],
        "risk_flags": [],
        "candidate_tier": "sector_watch",
        "candidate_tier_label": "板块观察",
        "tier_reason": "防守阶段板块观察：科技成长方向保留代表票，交给人盘中判断，非买点。",
    }

    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "candidate_tiers": {
                "core_action": [],
                "sector_watch": [sector_watch],
                "watch_wait": [],
                "risk_reject": [],
                "summary": {
                    "core_block_reason": "没有核心行动：大盘压力大，停止扩散，只做观察和风控。"
                },
            },
            "candidates": [],
        }
    )

    assert "防守板块观察 1 只" in text
    assert "防守板块观察（交给人判断，非买点）" in text
    assert "科技成长方向保留代表票" in text
    assert "学习观察（非买点，盘中验证）" in text


def test_filter_hot_sector_candidates_keeps_potential_watch_outside_hot_sector() -> None:
    discovery = {
        "sector_focus": [
            {
                "sector": "证券",
                "focus_score": 76,
                "continuity_score": 74,
                "avg_return_20d_pct": 11,
                "positive_ratio": 0.66,
            }
        ]
    }
    candidates = [
        {
            "symbol": "601066",
            "sector": "证券",
            "selection_mode": "formal_strategy",
            "reasons": ["板块20日主线扩散较好"],
        },
        {
            "symbol": "600673",
            "sector": "综合类",
            "selection_mode": "potential_watch",
            "reasons": ["潜力观察：个股启动但板块未确认，只观察不行动"],
        },
        {
            "symbol": "600000",
            "sector": "银行",
            "selection_mode": "observation",
            "reasons": ["相对强度不弱"],
        },
    ]

    filtered = filter_hot_sector_candidates(discovery, candidates)

    assert [item["symbol"] for item in filtered] == ["601066", "600673"]


def test_select_action_candidates_excludes_potential_watch() -> None:
    candidates = [
        {
            "symbol": "002156",
            "selection_mode": "formal_strategy",
            "score": 84.9,
            "selected_strategy_type": "long_term",
            "reasons": ["低维主线：板块趋势和个股强度共振"],
            "risk_flags": [],
        },
        {
            "symbol": "600673",
            "selection_mode": "potential_watch",
            "score": 91.0,
            "selected_strategy_type": "watch_breakout",
            "reasons": ["潜力观察：个股启动但板块未确认，只观察不行动"],
            "risk_flags": [],
        },
    ]

    selected = select_action_candidates({"candidates": candidates}, candidates, max_items=3)

    assert [item["symbol"] for item in selected] == ["002156"]


def test_format_candidate_screening_text_includes_sector_distribution() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "sector_groups": [
                {"sector": "半导体", "count": 3, "avg_score": 81.2},
                {"sector": "化学制药", "count": 2, "avg_score": 76.5},
            ],
            "sector_focus": [
                {
                    "sector": "半导体",
                    "continuity_score": 77.4,
                    "resilience_score": 68.2,
                    "leadership_score": 74.8,
                }
            ],
            "candidates": [
                {
                    "symbol": "603061",
                    "name": "金海通",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "score": 80.7,
                    "selected_rule_id": "R007",
                    "selected_rule_name": "趋势量能确认",
                    "selected_strategy_type": "swing",
                    "reasons": ["板块主线地位靠前", "板块20日主线扩散较好"],
                    "risk_flags": [],
                }
            ],
        }
    )

    assert "板块分布：" not in text
    assert "半导体 3只 / 均分81.2" not in text
    assert "板块观察：" not in text
    assert "半导体 月势77.4 / 韧性68.2 / 领头74.8" not in text
    assert "603061 金海通 半导体" in text


def test_format_candidate_screening_text_excludes_exploration_candidates() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "sector_focus": [
                {
                    "sector": "半导体",
                    "focus_score": 74,
                    "continuity_score": 75,
                    "avg_return_20d_pct": 10,
                    "positive_ratio": 0.65,
                }
            ],
            "candidates": [
                {
                    "symbol": "002156",
                    "name": "通富微电",
                    "sector": "半导体",
                    "selection_mode": "exploration",
                    "score": 79.1,
                    "selected_rule_id": "EXP001",
                    "selected_rule_name": "强板块趋势探索",
                    "selected_strategy_type": "watch_breakout",
                    "reasons": ["板块20日主线扩散较好", "趋势+相对强度因子仍有支撑"],
                    "risk_flags": [],
                },
                {
                    "symbol": "603061",
                    "name": "金海通",
                    "sector": "半导体",
                    "selection_mode": "observation",
                    "score": 80.7,
                    "selected_rule_id": "OBS001",
                    "selected_rule_name": "观察候选",
                    "selected_strategy_type": "watch_breakout",
                    "reasons": ["板块20日主线扩散较好", "趋势和资金同向"],
                    "risk_flags": [],
                },
            ],
        }
    )

    assert "002156" not in text
    assert "EXP001" not in text
    assert "603061 金海通 半导体" in text


def test_format_candidate_screening_text_marks_all_risky_candidates_as_watch_only() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "sector_focus": [
                {
                    "sector": "半导体",
                    "focus_score": 74,
                    "continuity_score": 75,
                    "avg_return_20d_pct": 10,
                    "positive_ratio": 0.65,
                }
            ],
            "candidates": [
                {
                    "symbol": "603061",
                    "name": "金海通",
                    "sector": "半导体",
                    "selection_mode": "observation",
                    "score": 80.7,
                    "selected_rule_id": "OBS001",
                    "selected_rule_name": "观察候选",
                    "selected_strategy_type": "watch_breakout",
                    "reasons": ["板块20日主线扩散较好", "趋势和资金同向"],
                    "risk_flags": ["今日涨幅较大10.00%"],
                }
            ],
        }
    )

    assert "只做观察清单" in text


def test_format_candidate_screening_text_surfaces_robust_factor_reasons() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "sector_focus": [
                {
                    "sector": "通信设备",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                },
                {
                    "sector": "专用设备",
                    "focus_score": 66,
                    "continuity_score": 68,
                    "avg_return_20d_pct": 8.2,
                    "positive_ratio": 0.58,
                },
            ],
            "candidates": [
                {
                    "symbol": "603083",
                    "name": "低噪音观察",
                    "sector": "通信设备",
                    "selection_mode": "formal_strategy",
                    "score": 80.2,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "swing",
                    "reasons": [
                        "入选层级：正式策略命中",
                        "路线 强路线 第78.8分",
                        "路线判断：趋势和资金都在同一方向",
                        "趋势78.0",
                        "支撑：回调质量符合5月较稳因子，趋势+相对强度因子仍有支撑，板块中期趋势延续性较好",
                    ],
                    "risk_flags": [],
                }
            ],
        }
    )

    assert "回调质量符合5月较稳因子" in text
    assert "趋势+相对强度因子仍有支撑" in text
    assert "板块中期趋势延续性较好" in text


def test_format_candidate_screening_text_splits_star_market_candidates() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "candidates": [
                {
                    "symbol": "603083",
                    "name": "普通候选",
                    "sector": "通信设备",
                    "selection_mode": "formal_strategy",
                    "score": 82.5,
                    "selected_rule_id": "R002",
                    "selected_rule_name": "趋势突破",
                    "selected_strategy_type": "short_term",
                    "reasons": ["板块20日主线扩散较好", "趋势强度领先"],
                    "risk_flags": [],
                },
                {
                    "symbol": "688003",
                    "name": "科创候选",
                    "sector": "专用设备",
                    "selection_mode": "formal_strategy",
                    "score": 75.4,
                    "selected_rule_id": "R007",
                    "selected_rule_name": "趋势量能确认",
                    "selected_strategy_type": "short_term",
                    "reasons": ["板块20日主线扩散较好", "趋势和资金同向"],
                    "risk_flags": [],
                },
            ],
        }
    )

    assert "长期/波段主池（普通版最多8只）" in text
    assert "科创板高弹性池（最多10只）" in text
    assert text.index("603083 普通候选") < text.index("科创板高弹性池")
    assert text.index("688003 科创候选") > text.index("科创板高弹性池")


def test_format_candidate_screening_text_groups_multiple_rules_by_symbol() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "candidates": [
                {
                    "symbol": "603083",
                    "name": "普通候选",
                    "sector": "通信设备",
                    "selection_mode": "formal_strategy",
                    "score": 82.5,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["板块中期趋势延续性较好"],
                    "risk_flags": [],
                },
                {
                    "symbol": "603083",
                    "name": "普通候选",
                    "sector": "通信设备",
                    "selection_mode": "formal_strategy",
                    "score": 78.5,
                    "selected_rule_id": "R007",
                    "selected_rule_name": "趋势量能确认",
                    "selected_strategy_type": "swing",
                    "reasons": ["板块20日主线扩散较好", "趋势和资金同向"],
                    "risk_flags": [],
                },
            ],
        }
    )

    assert text.count("603083 普通候选 通信设备") == 1
    assert "规则：R004 板块中期趋势跟随" in text
    assert "共振规则：R004、R007" in text
    assert "板块20日主线扩散较好" in text


def test_format_candidate_screening_text_keeps_only_formal_selection_tier_when_present() -> None:
    text = format_candidate_screening_text(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "sector_focus": [
                {
                    "sector": "半导体",
                    "focus_score": 74,
                    "continuity_score": 75,
                    "avg_return_20d_pct": 10,
                    "positive_ratio": 0.65,
                }
            ],
            "candidates": [
                {
                    "symbol": "603061",
                    "name": "正式票",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "selection_tier": "formal",
                    "score": 80.7,
                    "selected_rule_id": "R007",
                    "selected_rule_name": "趋势量能确认",
                    "selected_strategy_type": "swing",
                    "reasons": ["板块20日主线扩散较好", "趋势量能确认"],
                    "risk_flags": [],
                },
                {
                    "symbol": "603062",
                    "name": "观察票",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "selection_tier": "watch",
                    "score": 88.0,
                    "selected_rule_id": "R007",
                    "selected_rule_name": "趋势量能确认",
                    "selected_strategy_type": "swing",
                    "reasons": ["板块20日主线扩散较好", "等待确认"],
                    "risk_flags": [],
                },
                {
                    "symbol": "603063",
                    "name": "暂缓票",
                    "sector": "半导体",
                    "selection_mode": "formal_strategy",
                    "selection_tier": "defer",
                    "score": 90.0,
                    "selected_rule_id": "R007",
                    "selected_rule_name": "趋势量能确认",
                    "selected_strategy_type": "swing",
                    "reasons": ["板块20日主线扩散较好", "放量回落"],
                    "risk_flags": ["放量回落"],
                },
            ],
        }
    )

    assert "603061 正式票" in text
    assert "603062 观察票" not in text
    assert "603063 暂缓票" not in text


def test_dispatch_paper_alerts_skips_unconfigured_dingtalk(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("NOTIFICATION_CHANNELS", "dingtalk")
    monkeypatch.setenv("DINGTALK_WEBHOOK_URL", "")

    results = dispatch_paper_alerts([_alert()])

    assert len(results) == 1
    assert results[0].channel == "dingtalk"
    assert results[0].status == "skipped"
    get_settings.cache_clear()


def test_dispatch_candidate_screening_skips_unconfigured_dingtalk(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("NOTIFICATION_CHANNELS", "dingtalk")
    monkeypatch.setenv("DINGTALK_WEBHOOK_URL", "")

    results = dispatch_candidate_screening(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "sector_focus": [
                {
                    "sector": "通信设备",
                    "focus_score": 72,
                    "continuity_score": 70,
                    "avg_return_20d_pct": 9,
                    "positive_ratio": 0.62,
                }
            ],
            "candidates": [
                {
                    "symbol": "603083",
                    "selection_mode": "formal_strategy",
                    "score": 82.5,
                    "selected_rule_id": "R002",
                    "selected_rule_name": "趋势突破",
                    "sector": "通信设备",
                    "reasons": ["板块20日主线扩散较好", "趋势强度领先"],
                    "risk_flags": [],
                }
            ],
        }
    )

    assert len(results) == 1
    assert results[0].status == "skipped"
    get_settings.cache_clear()


def test_dispatch_candidate_screening_sends_long_term_only_payload(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("NOTIFICATION_CHANNELS", "dingtalk")
    monkeypatch.setenv("DINGTALK_WEBHOOK_URL", "")

    results = dispatch_candidate_screening(
        {
            "feature_date": "2026-06-24",
            "universe_size": 100,
            "retired": 0,
            "candidates": [
                {
                    "symbol": "600183",
                    "selection_mode": "formal_strategy",
                    "score": 86.4,
                    "selected_rule_id": "R004",
                    "selected_rule_name": "板块中期趋势跟随",
                    "selected_strategy_type": "long_term",
                    "reasons": ["先看板块主线"],
                    "risk_flags": [],
                }
            ],
        }
    )

    assert len(results) == 1
    assert results[0].status == "skipped"
    get_settings.cache_clear()


def test_dispatch_monthly_trade_summary_is_web_only(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("NOTIFICATION_CHANNELS", "dingtalk")
    monkeypatch.setenv("DINGTALK_WEBHOOK_URL", "")

    results = dispatch_monthly_trade_summary("6月交易总结")

    assert results == []
    get_settings.cache_clear()
