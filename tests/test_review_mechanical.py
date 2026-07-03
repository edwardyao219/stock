from types import SimpleNamespace
from decimal import Decimal

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


def test_generate_daily_mechanical_review_focuses_on_market_and_candidate_recap(monkeypatch) -> None:
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
        "services.engine.review.repository.load_candidate_pool_items_for_review",
        lambda db, report_date: [
            {
                "symbol": "603083",
                "note": "候选理由：趋势强，量能健康。",
                "tags": ["after_close_candidate", "2026-06-23", "rank:1", "score:86.4"],
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
    assert "数据日期 2026-06-23（已过期）" in review.content_md
    assert "## 昨日候选今日回看" in review.content_md
    assert "第1名 / 86.4分" in review.content_md
    assert "K线 O10.00 H10.50 L9.80 C10.20" in review.content_md
    assert "## 明日候选计划" not in review.content_md
