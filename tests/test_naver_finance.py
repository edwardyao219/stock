from datetime import datetime

from services.collector.naver_finance import parse_naver_realtime_quote


def test_parse_naver_realtime_quote_uses_raw_numeric_values_and_korea_timestamp() -> None:
    quote = parse_naver_realtime_quote(
        {
            "datas": [
                {
                    "itemCode": "000660",
                    "stockName": "SK하이닉스",
                    "closePriceRaw": "2118000",
                    "compareToPreviousClosePriceRaw": "205000",
                    "fluctuationsRatioRaw": "10.72",
                    "localTradedAt": "2026-07-15T09:42:43.182974+09:00",
                    "marketStatus": "OPEN",
                }
            ]
        },
        source="naver.finance.realtime.stock",
    )

    assert quote.symbol == "000660"
    assert quote.name == "SK하이닉스"
    assert quote.price == 2118000.0
    assert quote.change_pct == 0.1072
    assert quote.observed_at == datetime(2026, 7, 15, 9, 42, 43, 182974)
    assert quote.market_status == "OPEN"
