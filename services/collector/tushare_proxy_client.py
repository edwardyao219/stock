from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import requests

from services.shared.config import get_settings


@dataclass(frozen=True)
class TushareResponse:
    fields: list[str]
    items: list[list[Any]]
    has_more: bool
    count: int | None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "-" in text:
        return datetime.fromisoformat(text).date().isoformat()
    if len(text) == 8:
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def query(api_name: str, params: dict[str, Any] | None = None) -> TushareResponse:
    settings = get_settings()
    if not settings.tushare_proxy_url:
        raise RuntimeError("TUSHARE_PROXY_URL is not configured")
    if not settings.tushare_auth_code:
        raise RuntimeError("TUSHARE_AUTH_CODE is not configured")

    payload = {
        "api_name": api_name,
        "auth_code": settings.tushare_auth_code,
        "params": params or {},
    }
    response = _session().post(
        settings.tushare_proxy_url,
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("code") not in {0, "0"}:
        raise RuntimeError(str(data))
    body = data.get("data") or {}
    return TushareResponse(
        fields=list(body.get("fields") or []),
        items=list(body.get("items") or []),
        has_more=bool(body.get("has_more")),
        count=body.get("count"),
    )
