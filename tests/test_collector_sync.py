from services.collector import sync as collector_sync
from services.collector.contracts import CollectionResult


def test_sync_index_daily_bars_falls_back_to_tushare_when_akshare_fails(monkeypatch) -> None:
    calls = []

    def fail_fetch_index_daily_bars(**_kwargs):
        raise RuntimeError("RemoteDisconnected")

    def fake_tushare_index_daily(db, *, ts_code, start_date, end_date, symbol):
        calls.append((ts_code, start_date, end_date, symbol))
        return 1

    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(collector_sync, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(collector_sync, "fetch_index_daily_bars", fail_fetch_index_daily_bars)
    monkeypatch.setattr(collector_sync, "sync_tushare_index_daily", fake_tushare_index_daily)

    result = collector_sync.sync_index_daily_bars(
        start_date="20260707",
        end_date="20260707",
        symbols=["000001"],
    )

    assert calls == [("000001.SH", "20260707", "20260707", "sh000001")]
    assert result == [
        CollectionResult(
            source="tushare_proxy",
            dataset="index_daily:sh000001",
            trade_date="20260707",
            rows=1,
            status="ok",
            message="fallback from Akshare: RuntimeError: RemoteDisconnected",
        )
    ]
