from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from services.notifications.dingtalk import DingTalkNotifier
from services.shared.config import get_settings


@dataclass(frozen=True)
class NotificationResult:
    channel: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _enabled_channels() -> set[str]:
    channels = get_settings().notification_channels
    return {item.strip().lower() for item in channels.split(",") if item.strip()}


def format_paper_alert_text(alerts: list[dict[str, Any]]) -> str:
    lines = ["股票纸面交易预警"]
    for alert in alerts:
        lines.append(
            f"{alert.get('symbol')} {alert.get('alert_type')} "
            f"[{alert.get('severity')}] "
            f"价格={alert.get('price')} 止损={alert.get('current_stop')} "
            f"收益={alert.get('pnl_pct')} 时间={alert.get('alert_time')}"
        )
        lines.append(str(alert.get("message") or ""))
    return "\n".join(lines)


def dispatch_paper_alerts(alerts: list[dict[str, Any]]) -> list[NotificationResult]:
    if not alerts:
        return []

    settings = get_settings()
    channels = _enabled_channels()
    results: list[NotificationResult] = []

    if "dingtalk" in channels:
        if not settings.dingtalk_webhook_url:
            results.append(
                NotificationResult(
                    channel="dingtalk",
                    status="skipped",
                    message="DINGTALK_WEBHOOK_URL is not configured",
                )
            )
        else:
            notifier = DingTalkNotifier(
                webhook_url=settings.dingtalk_webhook_url,
                secret=settings.dingtalk_secret,
            )
            result = notifier.send_text(format_paper_alert_text(alerts))
            results.append(
                NotificationResult(
                    channel=result.channel,
                    status=result.status,
                    message=result.message,
                )
            )

    return results
