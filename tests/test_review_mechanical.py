from decimal import Decimal
from types import SimpleNamespace

from services.engine.review import mechanical as review_mechanical


class _DummySession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def commit(self):
        return None

    def execute(self, *args, **kwargs):
        return SimpleNamespace(scalars=lambda: [])


def test_generate_daily_mechanical_review_focuses_on_market_and_candidate_recap(
    monkeypatch,
) -> None:
    monkeypatch.setattr("services.shared.database.SessionLocal", lambda: _DummySession())
    monkeypatch.setattr(
        "services.engine.review.repository.load_market_summary_for_report_date",
        lambda db, report_date: {
            "requested_date": report_date,
            "trade_date": "2026-06-23",
            "stale": True,
            "stock_count": 2,
            "up_count": 1,
            "down_count": 1,
            "flat_count": 0,
            "up_ratio": 0.5,
            "avg_change_pct": 0.01,
            "total_amount": 123456789,
            "amount_change_pct": 0.2,
            "active_security_count": 2,
            "coverage_ratio": 1.0,
            "is_full_market": True,
        },
    )
    monkeypatch.setattr(
        "services.engine.review.repository.load_market_indexes_for_report_date",
        lambda db, report_date: [
            {
                "name": "上证指数",
                "symbol": "sh000001",
                "trade_date": "2026-06-24",
                "close": 3380.0,
                "change_pct": -0.005,
                "amount": 123456789,
                "stale": False,
            }
        ],
    )
    monkeypatch.setattr(
        "services.engine.review.repository.load_market_cross_section_for_report_date",
        lambda db, report_date: {
            "strong_sectors": [
                {
                    "sector": "消费电子",
                    "stock_count": 4,
                    "up_ratio": 0.75,
                    "avg_change_pct": 0.035,
                    "total_amount": 456789000,
                    "fund_flow_net_amount": 123456789,
                    "fund_flow_rate": 4.2,
                    "fund_flow_trade_date": "2026-06-22",
                    "fund_flow_stale": True,
                }
            ],
            "weak_sectors": [
                {
                    "sector": "半导体",
                    "stock_count": 5,
                    "up_ratio": 0.2,
                    "avg_change_pct": -0.026,
                    "total_amount": 556789000,
                    "fund_flow_net_amount": None,
                    "fund_flow_rate": None,
                    "fund_flow_trade_date": "",
                    "fund_flow_stale": False,
                }
            ],
            "top_gainers": [
                {
                    "symbol": "002001",
                    "name": "样本强股",
                    "sector": "消费电子",
                    "change_pct": 0.1,
                    "amount": 223456789,
                }
            ],
            "top_losers": [
                {
                    "symbol": "300001",
                    "name": "样本弱股",
                    "sector": "半导体",
                    "change_pct": -0.08,
                    "amount": 123456789,
                }
            ],
            "sector_moneyflow_trade_date": "2026-06-22",
            "sector_moneyflow_stale": True,
            "sector_moneyflow_total_count": 3,
            "sector_moneyflow_matched_count": 2,
            "sector_moneyflow_missing_count": 1,
            "sector_moneyflow_coverage_ratio": 0.666667,
        },
    )
    monkeypatch.setattr(
        "services.engine.features.health.inspect_daily_data_health",
        lambda db, trade_date: SimpleNamespace(
            status="warning",
            trade_date=__import__("datetime").date(2026, 6, 23),
            daily_bar_count=2,
            feature_count=1,
            previous_daily_bar_count=2,
            amount_missing_ratio=0.0,
            issues=[
                SimpleNamespace(
                    code="feature_missing",
                    severity="warning",
                    message="已有日线但缺少当日特征，候选池可能仍在使用旧批次。",
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "services.engine.review.repository.load_candidate_pool_items_for_review",
        lambda db, report_date: [
            {
                "symbol": "603083",
                "note": "候选理由：趋势强，量能健康。",
                "tags": [
                    "after_close_candidate",
                    "2026-06-23",
                    "rank:1",
                    "score:86.4",
                    "tier:core_action",
                    "tier_reason:弱情绪阶段只保留少量长期主线：板块连续性和量能确认同时达标；盘中仍看承接，不追高。",
                    "candidate_summary:没有核心行动：大盘压力大，停止扩散，只做观察和风控。",
                ],
                "status": "active",
            }
        ],
    )
    monkeypatch.setattr(
        "services.engine.review.repository.load_daily_bars_for_symbols",
        lambda db, trade_date, symbols: {
            "603083": SimpleNamespace(
                open=Decimal("10"),
                high=Decimal("10.5"),
                low=Decimal("9.8"),
                close=Decimal("10.2"),
                pre_close=Decimal("10"),
                amount=Decimal("12345678"),
            )
        },
    )
    monkeypatch.setattr(
        "services.engine.review.repository.load_rule_performance_for_date",
        lambda db, report_date: [
            SimpleNamespace(
                rule_id="R001",
                trade_count=3,
                win_rate=0.67,
                avg_return=0.03,
                profit_factor=1.5,
                score=88.0,
            )
        ],
    )
    monkeypatch.setattr(
        "services.engine.review.repository.load_trade_plans_for_date",
        lambda db, report_date: [SimpleNamespace(symbol="603083")],
    )
    monkeypatch.setattr(
        review_mechanical,
        "diagnose_rule_performances",
        lambda performances: [
            SimpleNamespace(
                rule_id="R001",
                status="ok",
                confidence="medium",
                summary="趋势结构稳定。",
                suggestions=["继续观察"],
                parameter_suggestions=[],
                to_dict=lambda: {
                    "rule_id": "R001",
                    "status": "ok",
                    "confidence": "medium",
                },
            )
        ],
    )
    monkeypatch.setattr(
        "services.engine.review.repository.insert_review_report",
        lambda *args, **kwargs: 1,
    )
    monkeypatch.setattr(
        "services.engine.review.repository.upsert_parameter_recommendations",
        lambda *args, **kwargs: 0,
    )

    review = review_mechanical.generate_daily_mechanical_review("2026-06-24")

    assert "## 市场概况" in review.content_md
    assert "主要指数" in review.content_md
    assert "上证指数 3380.00 / -0.50%" in review.content_md
    assert "## 数据健康" in review.content_md
    assert "已有日线但缺少当日特征" in review.content_md
    assert "## 大盘强弱分化" in review.content_md
    assert "消费电子" in review.content_md
    assert "资金净流入 1.2亿 / 净流入率 4.20%（资金日期 2026-06-22，非当日）" in review.content_md
    assert (
        "行业资金流日期 2026-06-22（非当日），覆盖 2 / 3，覆盖率 66.67%，缺失 1 个板块"
        in review.content_md
    )
    assert "行业资金流覆盖不足，只作为板块趋势的辅助确认，不单独判断主线。" in review.content_md
    assert "样本强股" in review.content_md
    assert "样本弱股" in review.content_md
    assert "强股通常来自当日更强的板块" in review.content_md
    assert "## 盘面与候选分化" in review.content_md
    assert "市场宽度均衡偏分歧" in review.content_md
    assert "主线先看 消费电子，承压集中在 半导体" in review.content_md
    assert "昨日候选有日线 1/1 只，红盘 1 只，绿盘 0 只，平均 2.00%" in review.content_md
    assert "候选整体跑赢市场平均 1.00 个百分点" in review.content_md
    assert "如果候选表现好于市场，优先看板块顺风和个股自身承接" in review.content_md
    assert "数据日期 2026-06-23（已过期）" in review.content_md
    assert "## 昨日候选今日回看" in review.content_md
    assert "第1名 / 86.4分" in review.content_md
    assert "分层: 核心行动" in review.content_md
    assert "弱情绪阶段只保留少量长期主线" in review.content_md
    assert "候选池提示: 没有核心行动：大盘压力大，停止扩散，只做观察和风控。" in review.content_md
    assert "K线 O10.00 H10.50 L9.80 C10.20" in review.content_md
    assert "## 明日候选计划" not in review.content_md


def test_sector_line_marks_aggregated_moneyflow_sources() -> None:
    line = review_mechanical._sector_line(
        {
            "sector": "半导体",
            "stock_count": 10,
            "up_ratio": 0.6,
            "avg_change_pct": 0.02,
            "total_amount": 123456789,
            "fund_flow_net_amount": 75000000,
            "fund_flow_rate": None,
            "fund_flow_trade_date": "2026-07-07",
            "fund_flow_stale": False,
            "fund_flow_source_count": 2,
        }
    )

    assert "资金净流入 7500.0万 / 净流入率 -" in line
    assert "细分合计 2 个" in line


def test_candidate_divergence_describes_relative_strength_in_weak_market() -> None:
    lines = review_mechanical._candidate_divergence_lines(
        market_summary={
            "up_count": 693,
            "down_count": 4797,
            "up_ratio": 0.1256,
            "avg_change_pct": -0.0263,
        },
        market_cross_section={
            "strong_sectors": [{"sector": "半导体"}, {"sector": "银行"}],
            "weak_sectors": [{"sector": "黄金"}],
        },
        candidate_items=[],
        candidate_bars={},
    )
    text = "\n".join(lines)

    assert "市场宽度偏弱" in text
    assert "下跌 4797" in text
    assert "极端防守" in text
    assert "次日少推核心" in text
    assert "弱市里相对抗跌先看 半导体、银行" in text
    assert "不等于主线确认" in text
    assert "主线先看 半导体、银行" not in text
