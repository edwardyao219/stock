from services.engine.research_pool import market_universe


def test_prepare_market_feature_universe_warns_when_full_market_coverage_is_low(
    monkeypatch,
) -> None:
    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def commit(self):
            return None

        def execute(self, _stmt):
            class _Result:
                def scalars(self):
                    return [f"{index:06d}" for index in range(100)]

            return _Result()

    monkeypatch.setattr(market_universe, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(market_universe, "sync_calendar_and_securities", lambda: None)
    monkeypatch.setattr(
        market_universe,
        "compute_and_store_stock_features",
        lambda symbols, start_date, end_date: {"symbols": len(symbols), "rows": 10},
    )
    monkeypatch.setattr(
        market_universe,
        "compute_and_store_sector_features",
        lambda start_date, end_date: {"sectors": 1, "rows": 1},
    )
    monkeypatch.setattr(market_universe, "_feature_symbol_count", lambda feature_date: 10)

    result = market_universe.prepare_market_feature_universe(
        feature_date="2026-06-18",
        sync_daily=False,
    )

    assert result.symbols == 100
    assert result.feature_symbols == 10
    assert result.coverage_ratio == 0.1
    assert any("全市场特征覆盖不足" in item for item in result.warnings)


def test_prepare_market_feature_universe_does_not_warn_for_limited_universe(monkeypatch) -> None:
    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def commit(self):
            return None

        def execute(self, _stmt):
            class _Result:
                def scalars(self):
                    return [f"{index:06d}" for index in range(10)]

            return _Result()

    monkeypatch.setattr(market_universe, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(market_universe, "sync_calendar_and_securities", lambda: None)
    monkeypatch.setattr(
        market_universe,
        "compute_and_store_stock_features",
        lambda symbols, start_date, end_date: {"symbols": len(symbols), "rows": 1},
    )
    monkeypatch.setattr(
        market_universe,
        "compute_and_store_sector_features",
        lambda start_date, end_date: {"sectors": 1, "rows": 1},
    )
    monkeypatch.setattr(market_universe, "_feature_symbol_count", lambda feature_date: 1)

    result = market_universe.prepare_market_feature_universe(
        feature_date="2026-06-18",
        limit=10,
        sync_daily=False,
    )

    assert result.coverage_ratio == 0.1
    assert result.warnings == []


def test_prepare_market_feature_universe_prefers_tushare_daily_for_full_market_sync(
    monkeypatch,
) -> None:
    calls = []

    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def commit(self):
            return None

        def execute(self, _stmt):
            class _Result:
                def scalars(self):
                    return ["000001", "000002", "600360"]

            return _Result()

    def fake_sync_tushare_daily(db, *, trade_date, ts_code=None):
        calls.append(("tushare", trade_date, ts_code))
        return 3

    def fail_sync_stock_daily_bars(*_args, **_kwargs):
        raise AssertionError("full-market daily sync should use Tushare first")

    monkeypatch.setattr(market_universe, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(market_universe, "sync_calendar_and_securities", lambda: None)
    monkeypatch.setattr(market_universe, "sync_tushare_daily", fake_sync_tushare_daily)
    monkeypatch.setattr(market_universe, "sync_stock_daily_bars", fail_sync_stock_daily_bars)
    monkeypatch.setattr(
        market_universe,
        "compute_and_store_stock_features",
        lambda symbols, start_date, end_date: {"symbols": len(symbols), "rows": 3},
    )
    monkeypatch.setattr(
        market_universe,
        "compute_and_store_sector_features",
        lambda start_date, end_date: {"sectors": 1, "rows": 1},
    )
    monkeypatch.setattr(market_universe, "_feature_symbol_count", lambda feature_date: 3)

    result = market_universe.prepare_market_feature_universe(
        feature_date="2026-06-30",
        sync_daily=True,
    )

    assert calls == [("tushare", "20260630", None)]
    assert result.synced_daily_rows == 3
    assert result.coverage_ratio == 1


def test_full_market_daily_sync_does_not_fallback_to_slow_akshare_when_tushare_auth_fails(
    monkeypatch,
) -> None:
    from datetime import date

    symbols = [f"{index:06d}" for index in range(600)]

    def fail_tushare(*_args, **_kwargs):
        raise RuntimeError("401 Unauthorized")

    def fail_akshare(*_args, **_kwargs):
        raise AssertionError("large full-market sync should not fall back to per-symbol Akshare")

    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(market_universe, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(market_universe, "sync_tushare_daily", fail_tushare)
    monkeypatch.setattr(market_universe, "sync_stock_daily_bars", fail_akshare)

    rows, warnings = market_universe._sync_market_daily_bars(date(2026, 7, 7), symbols)

    assert rows == 0
    assert any("未执行逐只 Akshare 兜底" in item for item in warnings)
