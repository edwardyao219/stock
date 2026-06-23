from services.engine.features.daily import BarInput, compute_stock_daily_features


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
    assert latest["amount_percentile_60d"] == 100
    assert latest["trend_score"] == 75
