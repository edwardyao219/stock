from services.engine.plans import sync
from services.engine.plans.generator import TradePlanCandidate


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def commit(self):
        return None


def test_generate_and_store_trade_plans_stops_when_candidate_pool_is_empty(monkeypatch) -> None:
    retired = {}
    monkeypatch.setattr(sync, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(sync, "seed_default_risk_profile", lambda db: None)
    monkeypatch.setattr(sync, "load_risk_profile", lambda db, name: object())
    monkeypatch.setattr(sync, "list_pool_symbols", lambda db, **kwargs: [])
    monkeypatch.setattr(
        sync,
        "retire_unselected_trade_plans",
        lambda db, **kwargs: retired.update(kwargs) or 0,
    )

    def fail_load_contexts(*args, **kwargs):
        raise AssertionError("empty candidate pool should not fall back to full-market contexts")

    monkeypatch.setattr(sync, "load_feature_contexts", fail_load_contexts)

    result = sync.generate_and_store_trade_plans(
        plan_date="2026-07-07",
        trade_date="2026-07-08",
        feature_date="2026-07-07",
        pool_name="experiment",
    )

    assert result == {
        "contexts": 0,
        "plans": 0,
        "written": 0,
        "feature_date": "2026-07-07",
        "symbols": 0,
    }
    assert retired["active_keys"] == set()


def test_generate_and_store_trade_plans_keeps_one_active_plan_per_symbol(monkeypatch) -> None:
    retired = {}
    upsert_options = {}
    monkeypatch.setattr(sync, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(sync, "seed_default_risk_profile", lambda db: None)
    monkeypatch.setattr(sync, "load_risk_profile", lambda db, name: object())
    monkeypatch.setattr(sync, "list_pool_symbols", lambda db, **kwargs: ["603893"])
    monkeypatch.setattr(
        sync,
        "load_feature_contexts",
        lambda *args, **kwargs: [{"symbol": "603893"}],
    )
    monkeypatch.setattr(sync, "load_matching_risk_profile", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        sync,
        "generate_trade_plans",
        lambda **kwargs: [
            TradePlanCandidate(
                plan_date="2026-07-08",
                trade_date="2026-07-08",
                symbol="603893",
                rule_id="R005",
                strategy_type="swing",
                entry_summary="swing",
                initial_stop=1.0,
                take_profit_1=1.2,
                take_profit_2=None,
                position_size=0.1,
                confidence_score=80,
            ),
            TradePlanCandidate(
                plan_date="2026-07-08",
                trade_date="2026-07-08",
                symbol="603893",
                rule_id="R004",
                strategy_type="long_term",
                entry_summary="long",
                initial_stop=1.0,
                take_profit_1=1.2,
                take_profit_2=None,
                position_size=0.1,
                confidence_score=75,
            ),
        ],
    )

    def fake_upsert_trade_plans(db, plans, **kwargs):
        upsert_options.update(kwargs)
        return len(plans)

    monkeypatch.setattr(sync, "upsert_trade_plans", fake_upsert_trade_plans)
    monkeypatch.setattr(
        sync,
        "retire_unselected_trade_plans",
        lambda db, **kwargs: retired.update(kwargs) or 0,
    )

    result = sync.generate_and_store_trade_plans(
        plan_date="2026-07-08",
        trade_date="2026-07-08",
        feature_date="2026-07-07",
        pool_name="experiment",
        use_learning_adjustments=False,
    )

    assert result["plans"] == 2
    assert retired["active_keys"] == {("603893", "R004")}
    assert upsert_options["reactivate_cancelled"] is True
