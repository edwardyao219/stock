from datetime import datetime

from services.jobs import status as job_status
from services.jobs.status import build_after_close_status


def test_after_close_status_exposes_candidate_review_and_dingtalk_outcomes() -> None:
    status = build_after_close_status(
        {
            "trade_date": "2026-07-14",
            "steps": [
                {
                    "name": "sync_market_regime",
                    "status": "ok",
                    "detail": "市场阶段 panic，风险 high。",
                },
                {
                    "name": "discover_next_session_candidates",
                    "status": "ok",
                    "summary": "明日候选完成：写入 0 只股票。",
                    "details": ["钉钉提醒：dingtalk:ok"],
                },
                {"name": "generate_daily_review", "status": "ok", "summary": "复盘已生成"},
            ],
        }
    )

    assert status["candidate_web_status"] == "ok"
    assert status["review_status"] == "ok"
    assert status["dingtalk_status"] == "ok"
    assert status["market_regime"] == "panic"
    assert status["market_regime_risk_level"] == "high"


def test_merge_after_close_status_preserves_push_outcomes(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(
        job_status,
        "read_after_close_status",
        lambda trade_date: {
            "trade_date": trade_date,
            "candidate_count": 21,
            "dingtalk_status": "ok",
            "message": "候选推送完成",
        },
    )
    monkeypatch.setattr(
        job_status,
        "_write_after_close_status_payload",
        lambda trade_date, payload: captured.update(payload),
        raising=False,
    )

    job_status.merge_after_close_status(
        "2026-07-16",
        {
            "moneyflow_status": "ok",
            "moneyflow_rows": 5197,
            "plan_rows_refreshed": 0,
        },
    )

    assert {key: value for key, value in captured.items() if key != "updated_at"} == {
        "trade_date": "2026-07-16",
        "candidate_count": 21,
        "dingtalk_status": "ok",
        "message": "候选推送完成",
        "moneyflow_status": "ok",
        "moneyflow_rows": 5197,
        "plan_rows_refreshed": 0,
    }
    assert "updated_at" in captured


def test_merge_after_close_status_refreshes_updated_at(monkeypatch) -> None:
    captured = {}
    refreshed_at = datetime(2026, 7, 23, 8, 50)
    monkeypatch.setattr(
        job_status,
        "read_after_close_status",
        lambda trade_date: {"trade_date": trade_date, "updated_at": "2026-07-22T18:44:12+08:00"},
    )
    monkeypatch.setattr(job_status, "now_local", lambda: refreshed_at)
    monkeypatch.setattr(
        job_status,
        "_write_after_close_status_payload",
        lambda trade_date, payload: captured.update(payload),
    )

    job_status.merge_after_close_status("2026-07-22", {"candidate_recovery_status": "ok"})

    assert captured["updated_at"] == refreshed_at.isoformat()
