from services.collector import daily
from services.collector.contracts import CollectionResult


def test_sync_daily_market_data_full_refresh_syncs_tushare_daily_without_pending(
    monkeypatch,
) -> None:
    calls = {}

    def fake_calendar_and_securities():
        calls["calendar"] = True
        return [
            CollectionResult(
                source="akshare",
                dataset="trading_calendar",
                trade_date="2026-07-07",
                rows=1,
                status="ok",
            )
        ]

    def fake_index_daily_bars(*, end_date):
        calls["index_end_date"] = end_date
        return [
            CollectionResult(
                source="akshare",
                dataset="index_daily:000001",
                trade_date=end_date,
                rows=1,
                status="ok",
            )
        ]

    def fake_current_tushare_securities(trade_date):
        calls["stock_basic"] = trade_date
        return CollectionResult(
            source="tushare_proxy",
            dataset="stock_basic",
            trade_date="20260707",
            rows=5500,
            status="ok",
        )

    def fake_tushare_market_data(trade_date, *, datasets, force=False):
        calls["tushare"] = {
            "trade_date": trade_date,
            "datasets": tuple(datasets),
            "force": force,
        }
        return [
            CollectionResult(
                source="tushare_proxy",
                dataset="daily",
                trade_date=trade_date,
                rows=5200,
                status="ok",
            )
        ]

    monkeypatch.setattr(
        "services.collector.sync.sync_calendar_and_securities",
        fake_calendar_and_securities,
    )
    monkeypatch.setattr(
        "services.collector.sync.sync_current_tushare_securities",
        fake_current_tushare_securities,
    )
    monkeypatch.setattr("services.collector.sync.sync_index_daily_bars", fake_index_daily_bars)
    monkeypatch.setattr(
        "services.collector.sync.sync_tushare_market_data_resumable",
        fake_tushare_market_data,
    )

    results = daily.sync_daily_market_data("2026-07-07", full_refresh=True)

    assert calls == {
        "calendar": True,
        "stock_basic": "20260707",
        "index_end_date": "20260707",
        "tushare": {
            "trade_date": "20260707",
            "datasets": (
                "daily",
                "daily_basic",
                "stk_limit",
                "moneyflow",
                "moneyflow_dc",
                "limit_list_d",
                "cyq_perf",
            ),
            "force": False,
        },
    }
    assert not [item for item in results if item.status == "pending"]
    assert ("stock_basic", "ok", 5500) in [
        (item.dataset, item.status, item.rows) for item in results
    ]
    assert ("daily", "ok", 5200) in [(item.dataset, item.status, item.rows) for item in results]
