import gc
import weakref
from types import SimpleNamespace

import pytest

from services.engine.backtest import sync
from services.engine.backtest.models import RulePerformance


def _performance(rule_id: str) -> RulePerformance:
    return RulePerformance(
        rule_id=rule_id,
        trade_count=0,
        win_rate=0.0,
        avg_return=0.0,
        expectancy=0.0,
        profit_factor=0.0,
        max_drawdown=0.0,
        avg_mfe=0.0,
        avg_mae=0.0,
        score=0.0,
    )


def test_run_rules_backtest_closes_read_session_before_computation(monkeypatch) -> None:
    events: list[str] = []

    class _Session:
        def __enter__(self):
            events.append("read:enter")
            return self

        def __exit__(self, exc_type, exc, traceback):
            events.append("read:exit")

    monkeypatch.setattr(sync, "SessionLocal", _Session)
    monkeypatch.setattr(sync, "MVP_RULES", [SimpleNamespace(id="rule-1")])
    monkeypatch.setattr(sync, "load_many_backtest_inputs", lambda *args, **kwargs: [object()])

    def run_backtest(*args, **kwargs):
        assert events == ["read:enter", "read:exit"]
        return []

    monkeypatch.setattr(sync, "run_daily_rule_backtest", run_backtest)
    monkeypatch.setattr(
        sync,
        "summarize_rule_performance",
        lambda rule_id, trades: _performance(rule_id),
    )

    result = sync.run_rules_backtest(symbols=["000001"], persist=False)

    assert events == ["read:enter", "read:exit"]
    assert result == {
        "symbols": 1,
        "rules": ["rule-1"],
        "trade_count": 0,
        "deleted_trades": 0,
        "written_trades": 0,
        "written_performance": 0,
        "summaries": [_performance("rule-1").__dict__],
    }


def test_run_rules_backtest_releases_rule_trades_when_not_persisting(monkeypatch) -> None:
    first_trade = None

    class _Trade:
        pass

    monkeypatch.setattr(
        sync,
        "MVP_RULES",
        [SimpleNamespace(id="rule-1"), SimpleNamespace(id="rule-2")],
    )
    monkeypatch.setattr(sync, "load_many_backtest_inputs", lambda *args, **kwargs: [object()])

    def run_backtest(item, rule):
        nonlocal first_trade
        if rule.id == "rule-1":
            trade = _Trade()
            first_trade = weakref.ref(trade)
            return [trade]
        gc.collect()
        assert first_trade is not None and first_trade() is None
        return []

    monkeypatch.setattr(sync, "run_daily_rule_backtest", run_backtest)
    monkeypatch.setattr(
        sync,
        "summarize_rule_performance",
        lambda rule_id, trades: _performance(rule_id),
    )

    sync.run_rules_backtest(symbols=["000001"], persist=False)


def test_run_rules_backtest_persists_with_new_session(monkeypatch) -> None:
    events: list[str] = []
    session_names = iter(["read", "write"])

    class _Session:
        def __init__(self):
            self.name = next(session_names)

        def __enter__(self):
            events.append(f"{self.name}:enter")
            return self

        def __exit__(self, exc_type, exc, traceback):
            events.append(f"{self.name}:exit")

        def commit(self):
            events.append(f"{self.name}:commit")

    monkeypatch.setattr(sync, "SessionLocal", _Session)
    monkeypatch.setattr(
        sync,
        "MVP_RULES",
        [SimpleNamespace(id="rule-1"), SimpleNamespace(id="rule-2")],
    )
    monkeypatch.setattr(sync, "load_many_backtest_inputs", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        sync,
        "summarize_rule_performance",
        lambda rule_id, trades: _performance(rule_id),
    )
    monkeypatch.setattr(
        sync,
        "delete_backtest_trades",
        lambda db, *args: events.append(f"{db.name}:delete") or 1,
    )
    monkeypatch.setattr(
        sync,
        "upsert_backtest_trades",
        lambda db, *args: events.append(f"{db.name}:trades") or 2,
    )
    monkeypatch.setattr(
        sync,
        "upsert_rule_performance",
        lambda db, *args: events.append(f"{db.name}:performance") or 1,
    )

    result = sync.run_rules_backtest(symbols=["000001"], persist=True)

    assert events == [
        "read:enter",
        "read:exit",
        "write:enter",
        "write:delete",
        "write:trades",
        "write:performance",
        "write:delete",
        "write:trades",
        "write:performance",
        "write:commit",
        "write:exit",
    ]
    assert result["deleted_trades"] == 2
    assert result["written_trades"] == 4
    assert result["written_performance"] == 2


def test_run_rules_backtest_does_not_commit_partial_rule_results(monkeypatch) -> None:
    events: list[str] = []
    session_names = iter(["read", "write"])
    performance_writes = 0

    class _Session:
        def __init__(self):
            self.name = next(session_names)

        def __enter__(self):
            events.append(f"{self.name}:enter")
            return self

        def __exit__(self, exc_type, exc, traceback):
            outcome = exc_type.__name__ if exc_type else "ok"
            events.append(f"{self.name}:exit:{outcome}")

        def commit(self):
            events.append(f"{self.name}:commit")

    def write_performance(db, *args):
        nonlocal performance_writes
        performance_writes += 1
        if performance_writes == 2:
            raise RuntimeError("write failed")
        return 1

    monkeypatch.setattr(sync, "SessionLocal", _Session)
    monkeypatch.setattr(
        sync,
        "MVP_RULES",
        [SimpleNamespace(id="rule-1"), SimpleNamespace(id="rule-2")],
    )
    monkeypatch.setattr(sync, "load_many_backtest_inputs", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        sync,
        "summarize_rule_performance",
        lambda rule_id, trades: _performance(rule_id),
    )
    monkeypatch.setattr(sync, "delete_backtest_trades", lambda db, *args: 0)
    monkeypatch.setattr(sync, "upsert_backtest_trades", lambda db, *args: 0)
    monkeypatch.setattr(sync, "upsert_rule_performance", write_performance)

    with pytest.raises(RuntimeError, match="write failed"):
        sync.run_rules_backtest(symbols=["000001"], persist=True)

    assert events == [
        "read:enter",
        "read:exit:ok",
        "write:enter",
        "write:exit:RuntimeError",
    ]
