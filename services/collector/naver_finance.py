from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import requests

NAVER_REALTIME_URL = "https://polling.finance.naver.com/api/realtime/domestic/{kind}/{symbol}"


@dataclass(frozen=True)
class NaverRealtimeQuote:
    symbol: str
    name: str
    price: float | None
    previous_close_change: float | None
    change_pct: float | None
    observed_at: datetime | None
    market_status: str | None
    source: str


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_naver_realtime_quote(
    payload: dict[str, Any],
    *,
    source: str,
) -> NaverRealtimeQuote:
    rows = payload.get("datas") or []
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    observed_at: datetime | None = None
    raw_time = str(row.get("localTradedAt") or "").strip()
    if raw_time:
        try:
            observed_at = datetime.fromisoformat(raw_time).replace(tzinfo=None)
        except ValueError:
            observed_at = None
    change_pct = _float(row.get("fluctuationsRatioRaw"))
    return NaverRealtimeQuote(
        symbol=str(row.get("itemCode") or row.get("symbolCode") or "").strip(),
        name=str(row.get("stockName") or "").strip(),
        price=_float(row.get("closePriceRaw")),
        previous_close_change=_float(row.get("compareToPreviousClosePriceRaw")),
        change_pct=change_pct / 100 if change_pct is not None else None,
        observed_at=observed_at,
        market_status=str(row.get("marketStatus") or "").strip() or None,
        source=source,
    )


def fetch_naver_realtime_quote(
    symbol: str,
    *,
    kind: Literal["stock", "index"],
) -> NaverRealtimeQuote:
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        NAVER_REALTIME_URL.format(kind=kind, symbol=symbol),
        headers={
            "Referer": "https://finance.naver.com/",
            "User-Agent": "Mozilla/5.0",
        },
        timeout=10,
    )
    response.raise_for_status()
    source = f"naver.finance.realtime.{kind}"
    return parse_naver_realtime_quote(response.json(), source=source)
