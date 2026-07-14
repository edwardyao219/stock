from services.jobs.status import build_after_close_status


def test_after_close_status_exposes_candidate_review_and_dingtalk_outcomes() -> None:
    status = build_after_close_status(
        {
            "trade_date": "2026-07-14",
            "steps": [
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
