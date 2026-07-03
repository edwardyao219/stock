from datetime import date

from services.engine.features import sync as feature_sync
from services.engine.features.daily import BarInput, compute_stock_daily_features
from services.engine.features.sector import SectorFeatureRow
from services.engine.features.sync import _filter_feature_rows


def test_compute_stock_daily_features_basic_values() -> None:
    bars = [
        BarInput(
            symbol="000001",
            trade_date=f"2026-01-{day:02d}",
            open=float(day),
            high=float(day + 1),
            low=float(day - 1),
            close=float(day),
            pre_close=float(day - 1) if day > 1 else None,
            amount=float(day * 1000),
        )
        for day in range(1, 22)
    ]

    rows = compute_stock_daily_features(bars)
    latest = rows[-1].features

    assert len(rows) == 21
    assert latest["return_1d"] == 21 / 20 - 1
    assert latest["return_20d"] == 21 / 1 - 1
    assert latest["ma5"] == 19
    assert latest["ma20"] == 11.5
    assert latest["distance_to_20d_high"] == 21 / 22 - 1
    assert latest["recent_high_20d"] == 22
    assert latest["recent_low_20d"] == 1
    assert latest["swing_high_10d"] == 22
    assert latest["swing_low_10d"] == 11
    assert latest["atr_pct"] is not None
    assert latest["amount_percentile_60d"] == 100
    assert latest["trend_score"] == 75
    assert latest["amount_ratio_5d"] is not None
    assert latest["recent_amount_ratio_20d"] is not None
    assert latest["close_position_in_range"] == 0.5
    assert latest["upper_shadow_pct"] > 0
    assert latest["pullback_to_ma20_pct"] is not None
    assert latest["volume_trap_risk_score"] is not None


def test_compute_stock_daily_features_scores_trend_volume_quality() -> None:
    bars = [
        BarInput(
            symbol="002837",
            trade_date=f"2026-02-{day:02d}",
            open=20.0 + day * 0.18,
            high=20.3 + day * 0.18,
            low=19.8 + day * 0.18,
            close=20.1 + day * 0.18,
            pre_close=20.1 + (day - 1) * 0.18 if day > 1 else None,
            amount=1000.0 + day * 8.0,
        )
        for day in range(1, 81)
    ]
    bars[-1] = BarInput(
        symbol="002837",
        trade_date="2026-02-80",
        open=34.2,
        high=34.9,
        low=33.9,
        close=34.7,
        pre_close=34.32,
        amount=1900.0,
    )

    rows = compute_stock_daily_features(bars)
    latest = rows[-1].features

    assert latest["ma_alignment_score"] == 100
    assert latest["ma20_slope_20d"] is not None
    assert latest["ma60_slope_20d"] is not None
    assert latest["trend_quality_score"] > 70
    assert latest["volume_confirmation_score"] > 55
    assert latest["overheat_score"] < 80
    assert latest["route_score"] > 70
    assert latest["route_label"] in {"强路线", "可跟踪"}
    assert latest["route_reason"] is not None


def test_compute_stock_daily_features_adds_price_volume_trend_score() -> None:
    bars = [
        BarInput(
            symbol="603083",
            trade_date=f"2026-03-{day:02d}",
            open=18.0 + day * 0.10,
            high=18.4 + day * 0.10,
            low=17.9 + day * 0.10,
            close=18.2 + day * 0.10 - (0.28 if day % 6 == 0 else 0.0),
            pre_close=(
                18.2 + (day - 1) * 0.10 - (0.28 if (day - 1) % 6 == 0 else 0.0)
                if day > 1
                else None
            ),
            amount=1000.0 + day * 15.0,
        )
        for day in range(1, 81)
    ]
    bars[-1] = BarInput(
        symbol="603083",
        trade_date="2026-03-80",
        open=27.45,
        high=28.20,
        low=27.30,
        close=28.05,
        pre_close=27.55,
        amount=2600.0,
    )

    latest = compute_stock_daily_features(bars)[-1].features

    assert latest["rsi_14"] is not None
    assert 50 <= latest["rsi_14"] <= 95
    assert latest["macd_dif"] is not None
    assert latest["macd_dea"] is not None
    assert latest["macd_hist"] is not None
    assert latest["macd_trend_score"] > 50
    assert latest["price_volume_trend_score"] > 65


def test_compute_stock_daily_features_normalizes_share_volume_when_amount_is_missing() -> None:
    bars = []
    for day in range(1, 26):
        close = 10.0 + day * 0.02
        if day <= 21:
            amount = None
            volume = 100_000_000.0
        else:
            amount = 1_080_000_000.0 + day * 5_000_000.0
            volume = amount / close / 100
        bars.append(
            BarInput(
                symbol="002156",
                trade_date=f"2026-04-{day:02d}",
                open=close * 0.99,
                high=close * 1.01,
                low=close * 0.98,
                close=close,
                pre_close=10.0 + (day - 1) * 0.02 if day > 1 else None,
                amount=amount,
                volume=volume,
            )
        )

    latest = compute_stock_daily_features(bars)[-1].features

    assert latest["amount_ratio_5d"] is not None
    assert 0.8 <= latest["amount_ratio_5d"] <= 1.4


def test_compute_stock_daily_features_treats_zero_amount_as_missing_for_volume_estimate() -> None:
    bars = []
    for day in range(1, 26):
        close = 30.0 + day * 0.12
        if day <= 21:
            amount = 0.0
            volume = 35_000_000.0 + day * 300_000.0
        else:
            amount = 1_150_000_000.0 + day * 12_000_000.0
            volume = amount / close / 100
        bars.append(
            BarInput(
                symbol="603290",
                trade_date=f"2026-05-{day:02d}",
                open=close * 0.99,
                high=close * 1.02,
                low=close * 0.98,
                close=close,
                pre_close=30.0 + (day - 1) * 0.12 if day > 1 else None,
                amount=amount,
                volume=volume,
            )
        )

    latest = compute_stock_daily_features(bars)[-1].features

    assert latest["amount_ratio_5d"] is not None
    assert 0.8 <= latest["amount_ratio_5d"] <= 1.4
    assert latest["volume_confirmation_score"] > 45


def test_compute_stock_daily_features_handles_medium_share_volume_without_amount_history() -> None:
    bars = []
    for day in range(1, 8):
        close = 135.0 + day * 1.2
        if day <= 3:
            amount = 0.0
            volume = 13_000_000.0 + day * 900_000.0
        else:
            amount = 1_450_000_000.0 + day * 180_000_000.0
            volume = amount / close / 100.0
        bars.append(
            BarInput(
                symbol="603290",
                trade_date=f"2026-06-{21 + day:02d}",
                open=close * 0.99,
                high=close * 1.02,
                low=close * 0.98,
                close=close,
                pre_close=135.0 + (day - 1) * 1.2 if day > 1 else None,
                amount=amount,
                volume=volume,
            )
        )

    latest = compute_stock_daily_features(bars)[-1].features

    assert latest["amount_ratio_5d"] is not None
    assert 0.8 <= latest["amount_ratio_5d"] <= 1.4
    assert latest["amount_percentile_60d"] > 40


def test_compute_stock_daily_features_rebases_prior_missing_share_volume() -> None:
    bars = []
    for day in range(1, 8):
        close = 24.0 + day * 0.1
        if day <= 4:
            amount = None
            volume = 2_200_000.0 + day * 120_000.0
        else:
            amount = 58_000_000.0 + day * 1_500_000.0
            volume = amount / close / 100.0
        bars.append(
            BarInput(
                symbol="603351",
                trade_date=f"2026-06-{23 + day:02d}",
                open=close * 0.99,
                high=close * 1.02,
                low=close * 0.98,
                close=close,
                pre_close=24.0 + (day - 1) * 0.1 if day > 1 else None,
                amount=amount,
                volume=volume,
            )
        )

    latest = compute_stock_daily_features(bars)[-1].features

    assert latest["amount_ratio_5d"] is not None
    assert 0.8 <= latest["amount_ratio_5d"] <= 1.5
    assert latest["volume_confirmation_score"] > 45


def test_filter_feature_rows_keeps_target_day_after_history_based_compute() -> None:
    bars = [
        BarInput(
            symbol="000001",
            trade_date=f"2026-01-{day:02d}",
            open=float(day),
            high=float(day + 1),
            low=float(day - 1),
            close=float(day),
            pre_close=float(day - 1) if day > 1 else None,
            amount=float(day * 1000),
        )
        for day in range(1, 22)
    ]

    rows = _filter_feature_rows(
        compute_stock_daily_features(bars),
        start_date=date(2026, 1, 21),
        end_date=date(2026, 1, 21),
    )

    assert len(rows) == 1
    assert rows[0].trade_date == "2026-01-21"
    assert rows[0].features["ma20"] == 11.5
    assert rows[0].features["return_20d"] == 21 / 1 - 1


def test_compute_and_store_stock_features_loads_only_needed_warmup_history(monkeypatch) -> None:
    calls = []

    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def commit(self) -> None:
            calls.append(("commit",))

    def fake_list_active_symbols(_db, limit=None):
        calls.append(("list", limit))
        return ["600000"]

    def fake_load_daily_bars(_db, *, symbol, start_date=None, end_date=None):
        calls.append(("load", symbol, start_date, end_date))
        return []

    monkeypatch.setattr(feature_sync, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(feature_sync, "list_active_symbols", fake_list_active_symbols)
    monkeypatch.setattr(feature_sync, "load_daily_bars", fake_load_daily_bars)
    monkeypatch.setattr(feature_sync, "compute_stock_daily_features", lambda _bars: [])
    monkeypatch.setattr(feature_sync, "upsert_stock_features", lambda _db, _rows: 0)

    result = feature_sync.compute_and_store_stock_features(
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )

    assert result == {"symbols": 1, "rows": 0}
    assert ("load", "600000", date(2026, 1, 1), date(2026, 5, 31)) in calls


def test_compute_and_store_sector_features_skips_low_coverage_feature_days(monkeypatch) -> None:
    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def commit(self) -> None:
            pass

    stock_contexts = [
        {"symbol": f"600{i:03d}", "trade_date": "2026-06-29", "sector_code": "半导体"}
        for i in range(10)
    ] + [
        {"symbol": "000001", "trade_date": "2026-06-30", "sector_code": "银行"}
    ]
    written_rows: list[SectorFeatureRow] = []

    def fake_compute_sector_features(contexts):
        trade_dates = sorted({str(context["trade_date"]) for context in contexts})
        return [
            SectorFeatureRow(
                sector_code=f"板块{index}",
                trade_date=trade_date,
                features={"sector_stock_count": len(contexts)},
            )
            for index, trade_date in enumerate(trade_dates, start=1)
        ]

    monkeypatch.setattr(feature_sync, "SessionLocal", lambda: _Db())
    monkeypatch.setattr(
        feature_sync,
        "load_stock_feature_contexts",
        lambda _db, start_date=None, end_date=None: stock_contexts,
    )
    monkeypatch.setattr(feature_sync, "compute_sector_features", fake_compute_sector_features)
    monkeypatch.setattr(
        feature_sync,
        "upsert_sector_features",
        lambda _db, rows: written_rows.extend(rows) or len(written_rows),
    )

    result = feature_sync.compute_and_store_sector_features(
        start_date=date(2026, 6, 29),
        end_date=date(2026, 6, 30),
    )

    assert result == {"sectors": 1, "rows": 1}
    assert [row.trade_date for row in written_rows] == ["2026-06-29"]
