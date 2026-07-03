from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote_plus

import requests


@dataclass(frozen=True)
class DingTalkSendResult:
    channel: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class DingTalkNotifier:
    def __init__(
        self,
        *,
        webhook_url: str,
        secret: str | None = None,
        timeout: int = 5,
    ) -> None:
        self.webhook_url = webhook_url
        self.secret = secret
        self.timeout = timeout

    def _signed_url(self) -> str:
        if not self.secret:
            return self.webhook_url
        timestamp = str(int(time.time() * 1000))
        payload = f"{timestamp}\n{self.secret}".encode()
        digest = hmac.new(self.secret.encode(), payload, hashlib.sha256).digest()
        sign = quote_plus(base64.b64encode(digest).decode("utf-8"))
        joiner = "&" if "?" in self.webhook_url else "?"
        return f"{self.webhook_url}{joiner}timestamp={timestamp}&sign={sign}"

    def send_text(self, content: str) -> DingTalkSendResult:
        try:
            response = requests.post(
                self._signed_url(),
                json={"msgtype": "text", "text": {"content": content}},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            if payload.get("errcode") not in {None, 0}:
                return DingTalkSendResult(
                    channel="dingtalk",
                    status="failed",
                    message=str(payload),
                )
            return DingTalkSendResult(channel="dingtalk", status="ok", message="sent")
        except Exception as exc:
            return DingTalkSendResult(
                channel="dingtalk",
                status="failed",
                message=f"{type(exc).__name__}: {exc}",
            )
