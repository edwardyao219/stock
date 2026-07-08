from services.engine.plans import sync


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
