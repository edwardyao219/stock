from types import SimpleNamespace

from services.engine.features.intraday_market_turn import classify_intraday_market_turn
from services.engine.features.intraday_market_turn_snapshot import (
    build_intraday_market_turn_snapshot,
)


def test_intraday_market_turn_confirms_repair_only_after_four_live_signals_align() -> None:
    state = classify_intraday_market_turn(
        breadth_ratio=0.58,
        index_change_pct=-0.003,
        prior_index_low_pct=-0.009,
        amount_supported=True,
        sector_expansion_count=3,
        data_ready=True,
        prior_snapshot_count=2,
    )

    assert state.key == "repair_confirmed"
    assert state.startup_watch_allowed is True
    assert state.core_action_allowed is False


def test_intraday_market_turn_fails_closed_without_a_prior_snapshot() -> None:
    state = classify_intraday_market_turn(
        breadth_ratio=0.65,
        index_change_pct=0.004,
        prior_index_low_pct=None,
        amount_supported=True,
        sector_expansion_count=4,
        data_ready=True,
        prior_snapshot_count=0,
    )

    assert state.key == "watch_repair"
    assert state.startup_watch_allowed is False


def test_intraday_snapshot_uses_full_market_breadth_and_sector_return_flow() -> None:
    quotes = [
        SimpleNamespace(
            symbol=f"600{index:03d}",
            price=11,
            pre_close=10,
            amount=110,
        )
        for index in range(1, 31)
    ]
    sector_by_symbol = {
        quote.symbol: f"板块{index // 10}" for index, quote in enumerate(quotes)
    }
    previous = [SimpleNamespace(index_change_pct=-0.009, total_amount=3000)]

    snapshot = build_intraday_market_turn_snapshot(
        quotes=quotes,
        active_security_count=30,
        sector_by_symbol=sector_by_symbol,
        index_change_pct=-0.003,
        prior_snapshots=previous,
    )

    assert snapshot["key"] == "repair_confirmed"
    assert snapshot["coverage_ratio"] == 1.0
    assert snapshot["sector_expansion_count"] == 3
    assert [item["sector"] for item in snapshot["expanding_sectors"]] == [
        "板块0",
        "板块1",
        "板块2",
    ]
    assert snapshot["expanding_sectors"][0]["up_ratio"] == 1.0
    assert snapshot["core_action_allowed"] is False


def test_intraday_snapshot_excludes_quotes_outside_active_universe() -> None:
    active_quotes = [
        SimpleNamespace(
            symbol=f"600{index:03d}",
            price=11,
            pre_close=10,
            amount=110,
        )
        for index in range(1, 30)
    ]
    inactive_quotes = [
        SimpleNamespace(
            symbol=f"300{index:03d}",
            price=11,
            pre_close=10,
            amount=110,
        )
        for index in range(1, 10)
    ]
    active_symbols = {quote.symbol for quote in active_quotes}

    snapshot = build_intraday_market_turn_snapshot(
        quotes=[*active_quotes, *inactive_quotes],
        active_security_count=30,
        active_symbols=active_symbols,
        sector_by_symbol={symbol: "半导体" for symbol in active_symbols},
        index_change_pct=0.003,
        prior_snapshots=[SimpleNamespace(index_change_pct=0.001, total_amount=2000)],
    )

    assert snapshot["coverage_ratio"] == round(29 / 30, 6)
    assert snapshot["data_ready"] is False


def test_intraday_snapshot_marks_sector_as_sustained_after_two_stable_snapshots() -> None:
    quotes = [
        SimpleNamespace(symbol=f"600{index:03d}", price=10.4, pre_close=10, amount=110)
        for index in range(1, 6)
    ]
    previous = [
        SimpleNamespace(
            index_change_pct=0.001,
            total_amount=300,
            state_json={
                "expanding_sectors": [
                    {
                        "sector": "半导体",
                        "symbol_count": 5,
                        "up_count": 4,
                        "up_ratio": 0.8,
                        "avg_change_pct": 0.035,
                    }
                ]
            },
        )
    ]

    snapshot = build_intraday_market_turn_snapshot(
        quotes=quotes,
        active_security_count=5,
        sector_by_symbol={quote.symbol: "半导体" for quote in quotes},
        index_change_pct=0.002,
        prior_snapshots=previous,
    )

    assert snapshot["sustained_sector_count"] == 1
    assert snapshot["sustained_expanding_sectors"][0]["sector"] == "半导体"
    assert snapshot["sustained_expanding_sectors"][0]["consecutive_snapshots"] == 2
