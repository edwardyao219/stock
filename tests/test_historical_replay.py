from datetime import date

from services.engine.backtest import replay


def test_historical_replay_dry_run_walks_dates_without_trades(monkeypatch) -> None:
    calls = {"features": [], "plans": []}

    monkeypatch.setattr(
        replay,
        "_available_trade_dates",
        lambda start_date, end_date, symbols: [date(2026, 1, 2), date(2026, 1, 3)],
    )
    monkeypatch.setattr(replay, "_symbol_count_for_date", lambda trade_date, symbols: len(symbols))

    def fake_stock_features(symbols, start_date, end_date):
        calls["features"].append((tuple(symbols), start_date, end_date))
        return {"symbols": len(symbols), "rows": len(symbols)}

    monkeypatch.setattr(replay, "compute_and_store_stock_features", fake_stock_features)
    monkeypatch.setattr(
        replay,
        "compute_and_store_sector_features",
        lambda start_date, end_date: {"sectors": 1, "rows": 1},
    )
    monkeypatch.setattr(
        replay,
        "_discover_candidates_and_generate_plans",
        lambda **kwargs: calls["plans"].append(kwargs)
        or (
            {"universe_size": 2, "candidates": [{"symbol": "002837"}]},
            {"contexts": 2, "plans": 1, "written": 1},
        ),
    )

    result = replay.run_historical_replay(
        start_date="2026-01-02",
        end_date="2026-01-03",
        symbols=["002837", "603083"],
        dry_run=True,
    )

    assert result.processed_days == 2
    assert result.generated_plans == 1
    assert result.opened == 0
    assert result.closed == 0
    assert calls["plans"][0]["trade_date"] == "2026-01-02"
    assert calls["plans"][0]["next_trade_date"] == "2026-01-03"
    assert result.days[0].candidates == 1
    assert result.account_summary.initial_cash == 1000000
    assert result.account_summary.equity == 1000000
    assert result.account_summary.total_return_pct == 0


def test_historical_replay_may_focus_preset_uses_may_window_and_filters_noise(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(
        replay,
        "_available_trade_dates",
        lambda start_date, end_date, symbols: [date(2026, 5, 6), date(2026, 5, 7)],
    )
    monkeypatch.setattr(replay, "_symbol_count_for_date", lambda trade_date, symbols: len(symbols))
    monkeypatch.setattr(
        replay,
        "compute_and_store_stock_features",
        lambda symbols, start_date, end_date: captured.update(
            {"features": (symbols, start_date, end_date)}
        )
        or {"symbols": len(symbols), "rows": len(symbols)},
    )
    monkeypatch.setattr(
        replay,
        "compute_and_store_sector_features",
        lambda start_date, end_date: {"sectors": 1, "rows": 1},
    )
    monkeypatch.setattr(
        replay,
        "_discover_candidates_and_generate_plans",
        lambda **kwargs: captured.update({"discover": kwargs})
        or (
            {"universe_size": 3, "candidates": []},
            {"contexts": 3, "plans": 0, "written": 0},
        ),
    )

    result = replay.run_historical_replay(
        preset="may_focus",
        symbols=["000001", "002837", "603083", "600183"],
        dry_run=True,
        generate_learning=False,
    )

    assert result.start_date == "2026-05-01"
    assert result.end_date == "2026-05-31"
    assert result.preset == "may_focus"
    assert result.symbols == ["002837", "603083", "600183"]
    assert captured["features"][0] == ["002837", "603083", "600183"]
    assert captured["discover"]["symbols"] == ["002837", "603083", "600183"]


def test_historical_replay_june_hot_sectors_preset_uses_hot_sector_symbols(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(
        replay,
        "_available_trade_dates",
        lambda start_date, end_date, symbols: [date(2026, 6, 3), date(2026, 6, 4)],
    )
    monkeypatch.setattr(replay, "_symbol_count_for_date", lambda trade_date, symbols: len(symbols))
    monkeypatch.setattr(
        replay,
        "compute_and_store_stock_features",
        lambda symbols, start_date, end_date: captured.update(
            {"features": (symbols, start_date, end_date)}
        )
        or {"symbols": len(symbols), "rows": len(symbols)},
    )
    monkeypatch.setattr(
        replay,
        "compute_and_store_sector_features",
        lambda start_date, end_date: {"sectors": 1, "rows": 1},
    )
    monkeypatch.setattr(
        replay,
        "_discover_candidates_and_generate_plans",
        lambda **kwargs: captured.update({"discover": kwargs})
        or (
            {"universe_size": 4, "candidates": []},
            {"contexts": 4, "plans": 0, "written": 0},
        ),
    )

    result = replay.run_historical_replay(
        preset="june_hot_sectors",
        dry_run=True,
        generate_learning=False,
    )

    assert result.start_date == "2026-06-01"
    assert result.end_date == "2026-06-30"
    assert result.preset == "june_hot_sectors"
    assert result.symbols == ["600183", "603083", "002837", "600519"]
    assert captured["features"][0] == ["600183", "603083", "002837", "600519"]
    assert captured["discover"]["symbols"] == ["600183", "603083", "002837", "600519"]


def test_historical_replay_limits_paper_entries_to_main_strategies(monkeypatch) -> None:
    captured = {}

    monkeypatch.setattr(
        replay,
        "_available_trade_dates",
        lambda start_date, end_date, symbols: [date(2026, 6, 3)],
    )
    monkeypatch.setattr(replay, "_symbol_count_for_date", lambda trade_date, symbols: len(symbols))
    monkeypatch.setattr(
        replay,
        "compute_and_store_stock_features",
        lambda symbols, start_date, end_date: {"symbols": len(symbols), "rows": len(symbols)},
    )
    monkeypatch.setattr(
        replay,
        "compute_and_store_sector_features",
        lambda start_date, end_date: {"sectors": 1, "rows": 1},
    )
    monkeypatch.setattr(replay, "_feature_row_count_for_date", lambda trade_date, symbols: 1)
    monkeypatch.setattr(replay, "_sector_row_count_for_date", lambda trade_date: 1)
    monkeypatch.setattr(
        replay,
        "_account_summary",
        lambda **kwargs: replay.HistoricalReplayAccountSummary(
            initial_cash=1000000,
            cash=1000000,
            market_value=0,
            equity=1000000,
            total_return_pct=0,
            realized_pnl=0,
            open_positions=0,
            closed_positions=0,
            win_rate=None,
            avg_closed_return_pct=None,
        ),
    )

    def fake_paper_simulation(**kwargs):
        captured["paper"] = kwargs
        return type(
            "Result",
            (),
            {
                "opened": 0,
                "closed": 0,
                "skipped": 0,
                "messages": [],
            },
        )()

    monkeypatch.setattr(replay, "run_daily_paper_simulation", fake_paper_simulation)

    replay.run_historical_replay(
        start_date="2026-06-03",
        end_date="2026-06-03",
        symbols=["000021"],
        generate_learning=False,
    )

    assert captured["paper"]["allowed_strategy_types"] == {"long_term", "swing"}


def test_replay_candidate_step_generates_plans_only_for_formal_candidates(monkeypatch) -> None:
    captured = {"discover": None, "plans": None, "committed": False}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def commit(self):
            captured["committed"] = True

    def fake_discover(db, **kwargs):
        captured["discover"] = kwargs
        return {
            "feature_date": "2026-01-02",
            "universe_size": 2,
            "candidates": [
                {"symbol": "002837", "selection_mode": "formal_strategy"},
                {"symbol": "603083", "selection_mode": "observation"},
            ],
        }

    def fake_generate(**kwargs):
        captured["plans"] = kwargs
        return {"contexts": 1, "plans": 1, "written": 1}

    monkeypatch.setattr(replay, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(replay, "discover_next_session_candidates", fake_discover)
    monkeypatch.setattr(replay, "generate_and_store_trade_plans", fake_generate)

    discovery, plan_result = replay._discover_candidates_and_generate_plans(
        trade_date="2026-01-02",
        next_trade_date="2026-01-03",
        symbols=["002837", "603083"],
        limit=2,
        use_learning_adjustments=True,
    )

    assert captured["committed"] is True
    assert captured["discover"]["symbols"] == ["002837", "603083"]
    assert captured["discover"]["min_universe_size"] == 0
    assert captured["plans"]["symbols"] == ["002837"]
    assert captured["plans"]["plan_date"] == "2026-01-02"
    assert captured["plans"]["trade_date"] == "2026-01-03"
    assert discovery["candidates"][1]["selection_mode"] == "observation"
    assert plan_result["written"] == 1
