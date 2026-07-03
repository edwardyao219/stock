from services.engine.features.sector import compute_sector_features


def test_compute_sector_features_groups_stock_contexts_by_industry() -> None:
    rows = compute_sector_features(
        [
            {
                "symbol": "000001",
                "trade_date": "2026-06-23",
                "sector_code": "银行",
                "return_1d": 0.01,
                "return_5d": 0.04,
                "return_20d": 0.08,
                "trend_score": 80,
                "volume_score": 70,
                "relative_strength_score": 75,
            },
            {
                "symbol": "601398",
                "trade_date": "2026-06-23",
                "sector_code": "银行",
                "return_1d": -0.005,
                "return_5d": 0.02,
                "return_20d": 0.05,
                "trend_score": 75,
                "volume_score": 60,
                "relative_strength_score": 70,
            },
            {
                "symbol": "600519",
                "trade_date": "2026-06-23",
                "sector_code": "白酒",
                "return_1d": 0.02,
                "return_5d": 0.03,
                "return_20d": 0.10,
                "trend_score": 90,
                "volume_score": 80,
                "relative_strength_score": 85,
            },
        ]
    )

    by_sector = {row.sector_code: row.features for row in rows}

    assert set(by_sector) == {"银行", "白酒"}
    assert by_sector["银行"]["sector_stock_count"] == 2
    assert by_sector["银行"]["sector_up_count"] == 1
    assert by_sector["银行"]["sector_breadth_score"] == 50
    assert by_sector["银行"]["sector_sample_confidence"] == 0.2
    assert by_sector["白酒"]["sector_sample_confidence"] == 0.1
    assert by_sector["银行"]["sector_strength_score"] > 65
    assert by_sector["银行"]["sector_trend_continuity_score"] > 60
    assert by_sector["银行"]["sector_trend_resilience_score"] > 50
    assert by_sector["白酒"]["sector_strength_score"] > by_sector["银行"]["sector_strength_score"]
    assert by_sector["白酒"]["sector_trend_continuity_score"] > by_sector["银行"]["sector_trend_continuity_score"]
