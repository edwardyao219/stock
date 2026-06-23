from services.notifications.dispatcher import dispatch_paper_alerts, format_paper_alert_text
from services.shared.config import get_settings


def _alert() -> dict:
    return {
        "symbol": "000001",
        "alert_type": "stop_loss_touched",
        "severity": "high",
        "price": 10.3,
        "current_stop": 10.34,
        "pnl_pct": -0.01,
        "alert_time": "2026-06-24T10:05:00",
        "message": "000001 盘中触及纸面止损/跟踪止损。",
    }


def test_format_paper_alert_text_contains_alert_context() -> None:
    text = format_paper_alert_text([_alert()])

    assert "股票纸面交易预警" in text
    assert "000001 stop_loss_touched" in text
    assert "盘中触及纸面止损" in text


def test_dispatch_paper_alerts_skips_unconfigured_dingtalk(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("NOTIFICATION_CHANNELS", "dingtalk")
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)

    results = dispatch_paper_alerts([_alert()])

    assert len(results) == 1
    assert results[0].channel == "dingtalk"
    assert results[0].status == "skipped"
    get_settings.cache_clear()
