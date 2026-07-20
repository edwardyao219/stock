from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from services.engine.backtest import repository as backtest_repository
from services.engine.plans import watchlist
from services.engine.plans.context import (
    _moneyflow_context,
    build_strategy_context,
    load_sector_feature_map,
    load_tushare_industry_moneyflow_map,
)
from services.engine.plans.evidence import build_trade_evidence
from services.engine.plans.repository import load_feature_contexts
from services.shared.database import Base
from services.shared.models import (
    DailyBar,
    FundamentalSnapshot,
    SectorFeatureDaily,
    SectorProfile,
    Security,
    StockFeatureDaily,
    TushareCyqPerf,
    TushareDailyBasic,
    TushareLimitListD,
    TushareMoneyflow,
    TushareMoneyflowDc,
    TushareMoneyflowIndDc,
)


def _security(symbol: str, *, exchange: str = "SH", industry: str = "半导体") -> Security:
    return Security(
        symbol=symbol,
        name=f"样本{symbol}",
        exchange=exchange,
        industry=industry,
        is_active=True,
        is_st=False,
    )


def _feature(symbol: str, trade_date: date) -> StockFeatureDaily:
    return StockFeatureDaily(
        symbol=symbol,
        trade_date=trade_date,
        features={"trend_score": 80, "relative_strength_score": 72},
    )


def _bar(symbol: str, trade_date: date) -> DailyBar:
    return DailyBar(
        symbol=symbol,
        trade_date=trade_date,
        open=Decimal("12.46"),
        high=Decimal("12.51"),
        low=Decimal("12.34"),
        close=Decimal("12.34"),
        pre_close=Decimal("12.46"),
        volume=Decimal("1012818.01"),
        amount=Decimal("1255113.972"),
        turnover_rate=Decimal("1.23"),
        limit_up=Decimal("13.71"),
        limit_down=Decimal("11.21"),
        is_suspended=False,
    )


def test_moneyflow_support_score_uses_relative_net_flow_across_stock_sizes() -> None:
    def row(net_amount: str, buy_amount: str) -> TushareMoneyflow:
        return TushareMoneyflow(
            ts_code="000001.SZ",
            trade_date=date(2026, 7, 17),
            buy_sm_amount=Decimal(buy_amount),
            buy_md_amount=Decimal(buy_amount),
            buy_lg_amount=Decimal(buy_amount),
            buy_elg_amount=Decimal(buy_amount),
            net_mf_amount=Decimal(net_amount),
        )

    positive = _moneyflow_context(row("100", "250"))
    negative = _moneyflow_context(row("-100", "250"))
    same_ratio_larger_stock = _moneyflow_context(row("1000", "2500"))
    no_turnover = _moneyflow_context(row("100", "0"))

    assert positive["moneyflow_support_score"] == 60.0
    assert negative["moneyflow_support_score"] == 40.0
    assert same_ratio_larger_stock["moneyflow_support_score"] == 60.0
    assert no_turnover["moneyflow_support_score"] == 50.0


def test_moneyflow_support_score_rejects_incomplete_or_invalid_buy_amounts() -> None:
    incomplete = TushareMoneyflow(
        ts_code="000001.SZ",
        trade_date=date(2026, 7, 17),
        buy_sm_amount=None,
        buy_md_amount=Decimal("100"),
        buy_lg_amount=Decimal("100"),
        buy_elg_amount=Decimal("100"),
        net_mf_amount=Decimal("-100"),
    )
    negative = TushareMoneyflow(
        ts_code="000001.SZ",
        trade_date=date(2026, 7, 17),
        buy_sm_amount=Decimal("-100"),
        buy_md_amount=Decimal("100"),
        buy_lg_amount=Decimal("100"),
        buy_elg_amount=Decimal("100"),
        net_mf_amount=Decimal("-100"),
    )

    for row in (incomplete, negative):
        context = _moneyflow_context(row)
        evidence = build_trade_evidence({**context, "dc_net_amount_rate": -1.0})

        assert context["moneyflow_buy_amount"] is None
        assert context["moneyflow_support_score"] == 50.0
        assert "dual_source_moneyflow_outflow" not in evidence["risk_flags"]


def test_moneyflow_support_score_clips_extreme_relative_net_flow() -> None:
    def score(net_amount: str) -> float:
        row = TushareMoneyflow(
            ts_code="000001.SZ",
            trade_date=date(2026, 7, 17),
            buy_sm_amount=Decimal("25"),
            buy_md_amount=Decimal("25"),
            buy_lg_amount=Decimal("25"),
            buy_elg_amount=Decimal("25"),
            net_mf_amount=Decimal(net_amount),
        )
        return _moneyflow_context(row)["moneyflow_support_score"]

    assert score("1000") == 100.0
    assert score("-1000") == 0.0


def _daily_basic(
    ts_code: str,
    trade_date: date,
    *,
    volume_ratio: str = "1.10",
) -> TushareDailyBasic:
    return TushareDailyBasic(
        ts_code=ts_code,
        trade_date=trade_date,
        turnover_rate=Decimal("1.23"),
        volume_ratio=Decimal(volume_ratio),
        pe_ttm=Decimal("8.76"),
        pb=Decimal("1.11"),
        total_mv=Decimal("123456.78"),
        circ_mv=Decimal("123456.78"),
    )


def test_load_feature_contexts_batches_same_day_tushare_5000_evidence() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    target_date = date(2026, 7, 10)
    prior_date = date(2026, 7, 9)

    with Session(engine) as db:
        db.add_all(
            [
                _security("000001", exchange="SZ"),
                _security("000002", exchange="SZ"),
                _feature("000001", target_date),
                _feature("000002", target_date),
                _bar("000001", target_date),
                _bar("000002", target_date),
                TushareMoneyflowDc(
                    ts_code="000001.SZ",
                    trade_date=prior_date,
                    net_amount_rate=Decimal("9.9"),
                ),
                TushareMoneyflowDc(
                    ts_code="000001.SZ",
                    trade_date=target_date,
                    net_amount_rate=Decimal("-1.5"),
                ),
                TushareMoneyflowDc(
                    ts_code="000002.SZ",
                    trade_date=prior_date,
                    net_amount_rate=Decimal("7.7"),
                ),
                TushareLimitListD(
                    ts_code="000001.SZ",
                    trade_date=prior_date,
                    limit="D",
                    open_times=9,
                ),
                TushareLimitListD(
                    ts_code="000001.SZ",
                    trade_date=target_date,
                    limit="U",
                    open_times=2,
                ),
                TushareLimitListD(
                    ts_code="000002.SZ",
                    trade_date=prior_date,
                    limit="U",
                    open_times=8,
                ),
                TushareCyqPerf(
                    ts_code="000001.SZ",
                    trade_date=prior_date,
                    cost_50pct=Decimal("99.9"),
                    cost_85pct=Decimal("199.9"),
                    winner_rate=Decimal("99.9"),
                ),
                TushareCyqPerf(
                    ts_code="000001.SZ",
                    trade_date=target_date,
                    cost_50pct=Decimal("10.2"),
                    cost_85pct=Decimal("11.4"),
                    winner_rate=Decimal("91.0"),
                ),
                TushareCyqPerf(
                    ts_code="000002.SZ",
                    trade_date=prior_date,
                    cost_50pct=Decimal("88.8"),
                ),
            ]
        )
        db.commit()

        statements_by_table = {
            "tushare_moneyflow_dc": 0,
            "tushare_limit_list_d": 0,
            "tushare_cyq_perf": 0,
        }

        def track_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
            lowered = " ".join(statement.lower().split()) + " "
            for table in statements_by_table:
                if f"from {table} " in lowered:
                    statements_by_table[table] += 1

        event.listen(engine, "before_cursor_execute", track_sql)
        try:
            contexts = load_feature_contexts(db, target_date.isoformat())
        finally:
            event.remove(engine, "before_cursor_execute", track_sql)

    context_by_symbol = {context["symbol"]: context for context in contexts}
    context = context_by_symbol["000001"]
    assert context["dc_net_amount_rate"] == -1.5
    assert context["limit_event"] == "U"
    assert context["limit_open_times"] == 2
    assert context["chip_cost_50pct"] == 10.2
    assert context["chip_cost_85pct"] == 11.4
    assert context["chip_winner_rate"] == 91.0
    assert "dc_net_amount_rate" not in context_by_symbol["000002"]
    assert "limit_event" not in context_by_symbol["000002"]
    assert "chip_cost_50pct" not in context_by_symbol["000002"]
    assert statements_by_table == {
        "tushare_moneyflow_dc": 2,
        "tushare_limit_list_d": 1,
        "tushare_cyq_perf": 1,
    }


def test_load_feature_contexts_batches_tushare_daily_basic_without_future_rows() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 6, 30)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001"),
                _security("600002"),
                _security("002156", exchange="SZ"),
                _feature("600001", signal_date),
                _feature("600002", signal_date),
                _feature("002156", signal_date),
                _bar("600001", signal_date),
                _bar("600002", signal_date),
                _bar("002156", signal_date),
                _daily_basic("600001.SH", signal_date, volume_ratio="1.01"),
                _daily_basic("600002.SH", signal_date, volume_ratio="1.02"),
                _daily_basic("002156.SZ", signal_date, volume_ratio="1.56"),
                _daily_basic("002156.SZ", date(2026, 7, 1), volume_ratio="9.99"),
            ]
        )
        db.commit()

        statements: list[str] = []

        def track_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
            if "tushare_daily_basic" in statement.lower():
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", track_sql)
        try:
            contexts = load_feature_contexts(db, signal_date.isoformat())
        finally:
            event.remove(engine, "before_cursor_execute", track_sql)

    volume_ratio_by_symbol = {
        context["symbol"]: context.get("volume_ratio") for context in contexts
    }

    assert volume_ratio_by_symbol == {
        "002156": 1.56,
        "600001": 1.01,
        "600002": 1.02,
    }
    assert len(statements) == 1


def test_load_feature_contexts_can_prioritize_strategy_candidates_before_limit() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 7)

    with Session(engine) as db:
        db.add_all(
            [
                _security("000001", exchange="SZ", industry="银行"),
                _security("688256", exchange="SH", industry="半导体"),
                StockFeatureDaily(
                    symbol="000001",
                    trade_date=signal_date,
                    features={
                        "sector_strength_score": 50,
                        "trend_score": 45,
                        "relative_strength_score": 42,
                        "volume_confirmation_score": 30,
                        "volume_trap_risk_score": 70,
                    },
                ),
                StockFeatureDaily(
                    symbol="688256",
                    trade_date=signal_date,
                    features={
                        "sector_strength_score": 88,
                        "trend_score": 91,
                        "relative_strength_score": 82,
                        "volume_confirmation_score": 76,
                        "volume_trap_risk_score": 25,
                    },
                ),
                _bar("000001", signal_date),
                _bar("688256", signal_date),
            ]
        )
        db.commit()

        default_contexts = load_feature_contexts(db, signal_date.isoformat(), limit=1)
        prioritized_contexts = load_feature_contexts(
            db,
            signal_date.isoformat(),
            limit=1,
            prefer_strategy_candidates=True,
        )

    assert [item["symbol"] for item in default_contexts] == ["000001"]
    assert [item["symbol"] for item in prioritized_contexts] == ["688256"]


def test_load_sector_feature_map_adds_relative_rank_score() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 7)

    with Session(engine) as db:
        db.add_all(
            [
                SectorFeatureDaily(
                    sector_code="半导体",
                    trade_date=signal_date,
                    features={"sector_strength_score": 58.1},
                ),
                SectorFeatureDaily(
                    sector_code="证券",
                    trade_date=signal_date,
                    features={"sector_strength_score": 40.5},
                ),
                SectorFeatureDaily(
                    sector_code="银行",
                    trade_date=signal_date,
                    features={"sector_strength_score": 35.0},
                ),
            ]
        )
        db.commit()

        sector_map = load_sector_feature_map(db, signal_date)

    assert sector_map["半导体"]["sector_strength_rank_score"] == 100.0
    assert sector_map["证券"]["sector_strength_rank_score"] == 50.0
    assert sector_map["银行"]["sector_strength_rank_score"] == 0.0


def test_load_feature_contexts_batches_optional_context_sources_without_future_rows() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 6, 30)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", industry="半导体"),
                _security("600002", industry="半导体"),
                _security("002156", exchange="SZ", industry="元件"),
                _feature("600001", signal_date),
                _feature("600002", signal_date),
                _feature("002156", signal_date),
                _bar("600001", signal_date),
                _bar("600002", signal_date),
                _bar("002156", signal_date),
                TushareMoneyflow(
                    ts_code="002156.SZ",
                    trade_date=signal_date,
                    buy_sm_amount=Decimal("1"),
                    sell_sm_amount=Decimal("2"),
                    buy_md_amount=Decimal("3"),
                    sell_md_amount=Decimal("4"),
                    buy_lg_amount=Decimal("5"),
                    sell_lg_amount=Decimal("6"),
                    buy_elg_amount=Decimal("7"),
                    sell_elg_amount=Decimal("8"),
                    net_mf_amount=Decimal("9"),
                ),
                TushareMoneyflow(
                    ts_code="002156.SZ",
                    trade_date=date(2026, 7, 1),
                    net_mf_amount=Decimal("999"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=signal_date,
                    content_type="行业",
                    ts_code="BK0001.DC",
                    name="半导体",
                    pct_change=Decimal("1.2"),
                    close=Decimal("1024.5"),
                    net_amount=Decimal("500000000"),
                    net_amount_rate=Decimal("3.5"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 7, 1),
                    content_type="行业",
                    ts_code="BK0001.DC",
                    name="半导体",
                    net_amount=Decimal("900000000"),
                    net_amount_rate=Decimal("9.9"),
                ),
                SectorProfile(
                    sector_name="半导体",
                    sector_style="growth_cycle",
                    analysis_framework="tech_growth_cycle",
                    default_strategy_type="long_term",
                    preferred_holding_style="monthly_trend",
                    key_drivers_json={"drivers": ["国产替代"]},
                ),
                FundamentalSnapshot(
                    symbol="002156",
                    report_date=date(2026, 3, 31),
                    available_date=date(2026, 4, 30),
                    revenue_growth=Decimal("12.5"),
                    profit_growth=Decimal("8.0"),
                    roe=Decimal("6.6"),
                    pe_ttm=Decimal("35.5"),
                    pb=Decimal("3.2"),
                    extra_json={"source": "known"},
                ),
                FundamentalSnapshot(
                    symbol="002156",
                    report_date=date(2026, 6, 30),
                    available_date=date(2026, 7, 1),
                    revenue_growth=Decimal("999"),
                    pe_ttm=Decimal("999"),
                    pb=Decimal("99"),
                    extra_json={"source": "future"},
                ),
            ]
        )
        db.commit()

        statements_by_table: dict[str, int] = {
            "tushare_moneyflow": 0,
            "tushare_moneyflow_ind_dc": 0,
            "fundamental_snapshots": 0,
            "sector_profiles": 0,
        }

        def track_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
            lowered = " ".join(statement.lower().split()) + " "
            for table in statements_by_table:
                if f"from {table} " in lowered:
                    statements_by_table[table] += 1

        event.listen(engine, "before_cursor_execute", track_sql)
        try:
            contexts = load_feature_contexts(db, signal_date.isoformat())
        finally:
            event.remove(engine, "before_cursor_execute", track_sql)

    context_by_symbol = {context["symbol"]: context for context in contexts}

    assert context_by_symbol["002156"]["net_mf_amount"] == 9.0
    assert context_by_symbol["600001"]["sector_fund_flow_rate"] == 3.5
    assert context_by_symbol["600001"]["sector_style"] == "growth_cycle"
    assert context_by_symbol["600001"]["analysis_framework"] == "tech_growth_cycle"
    assert context_by_symbol["600001"]["holding_style"] == "monthly_trend"
    assert context_by_symbol["600001"]["sector_key_drivers"] == ["国产替代"]
    assert context_by_symbol["002156"]["revenue_growth"] == 12.5
    assert context_by_symbol["002156"]["pe_ttm"] == 35.5
    assert statements_by_table == {
        "tushare_moneyflow": 1,
        "tushare_moneyflow_ind_dc": 1,
        "fundamental_snapshots": 2,
        "sector_profiles": 1,
    }


def test_build_strategy_context_includes_tushare_market_fields() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        security = Security(
            symbol="000001",
            name="平安银行",
            exchange="SZ",
            industry="银行",
            is_active=True,
            is_st=False,
        )
        feature_row = StockFeatureDaily(
            symbol="000001",
            trade_date=date(2025, 7, 29),
            features={"trend_score": 80, "relative_strength_score": 72},
        )
        bar = DailyBar(
            symbol="000001",
            trade_date=date(2025, 7, 29),
            open=Decimal("12.46"),
            high=Decimal("12.51"),
            low=Decimal("12.34"),
            close=Decimal("12.34"),
            pre_close=Decimal("12.46"),
            volume=Decimal("1012818.01"),
            amount=Decimal("1255113.972"),
            turnover_rate=Decimal("1.23"),
            limit_up=Decimal("13.71"),
            limit_down=Decimal("11.21"),
            is_suspended=False,
        )
        db.add_all(
            [
                security,
                feature_row,
                bar,
                TushareDailyBasic(
                    ts_code="000001.SZ",
                    trade_date=date(2025, 7, 29),
                    turnover_rate=Decimal("1.23"),
                    volume_ratio=Decimal("0.98"),
                    pe_ttm=Decimal("8.76"),
                    pb=Decimal("1.11"),
                    total_mv=Decimal("123456.78"),
                    circ_mv=Decimal("123456.78"),
                ),
                TushareMoneyflow(
                    ts_code="000001.SZ",
                    trade_date=date(2025, 7, 29),
                    buy_sm_amount=Decimal("1"),
                    sell_sm_amount=Decimal("2"),
                    buy_md_amount=Decimal("3"),
                    sell_md_amount=Decimal("4"),
                    buy_lg_amount=Decimal("5"),
                    sell_lg_amount=Decimal("6"),
                    buy_elg_amount=Decimal("7"),
                    sell_elg_amount=Decimal("8"),
                    net_mf_amount=Decimal("9"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2025, 7, 29),
                    content_type="行业",
                    ts_code="BK0475.DC",
                    name="银行",
                    pct_change=Decimal("1.2"),
                    close=Decimal("1024.5"),
                    net_amount=Decimal("500000000"),
                    net_amount_rate=Decimal("3.5"),
                ),
            ]
        )
        db.commit()

        context = build_strategy_context(
            db,
            feature_row=feature_row,
            security=security,
            bar=bar,
            sector_feature_map={
                "银行": {
                    "sector_strength_score": 70,
                    "sector_sample_confidence": 0.4,
                }
            },
        )

    assert context["volume_ratio"] == 0.98
    assert context["pe_ttm"] == 8.76
    assert context["net_mf_amount"] == 9.0
    assert context["sector_fund_flow_rate"] == 3.5
    assert context["sector_fund_flow_score"] > 50
    assert context["moneyflow_support_score"] > 40


def test_build_strategy_context_deduplicates_industry_moneyflow_by_name() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 6, 30)

    with Session(engine) as db:
        security = _security("603061", industry="半导体")
        feature_row = _feature("603061", signal_date)
        bar = _bar("603061", signal_date)
        db.add_all(
            [
                security,
                feature_row,
                bar,
                TushareMoneyflowIndDc(
                    trade_date=signal_date,
                    content_type="行业",
                    ts_code="BK0001.DC",
                    name="半导体",
                    net_amount=Decimal("100000000"),
                    net_amount_rate=Decimal("1.2"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=signal_date,
                    content_type="行业",
                    ts_code="BK0999.DC",
                    name="半导体",
                    net_amount=Decimal("500000000"),
                    net_amount_rate=Decimal("3.5"),
                ),
            ]
        )
        db.commit()

        context = build_strategy_context(
            db,
            feature_row=feature_row,
            security=security,
            bar=bar,
        )

    assert context["sector_fund_flow_net_amount"] == 500000000.0
    assert context["sector_fund_flow_rate"] == 3.5


def test_local_industry_moneyflow_aggregates_same_day_stock_flow() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 17)

    with Session(engine) as db:
        first = _security("000001", exchange="SZ", industry="元器件")
        second = _security("000002", exchange="SZ", industry="元器件")
        unsupported_bj = _security("920001", exchange="BJ", industry="元器件")
        first_bar = _bar("000001", signal_date)
        second_bar = _bar("000002", signal_date)
        unsupported_bj_bar = _bar("920001", signal_date)
        first_bar.amount = Decimal("5000000")
        second_bar.amount = Decimal("10000000")
        db.add_all(
            [
                first,
                second,
                unsupported_bj,
                first_bar,
                second_bar,
                unsupported_bj_bar,
                TushareMoneyflowDc(
                    ts_code="000001.SZ",
                    trade_date=signal_date,
                    net_amount=Decimal("100"),
                ),
                TushareMoneyflowDc(
                    ts_code="000002.SZ",
                    trade_date=signal_date,
                    net_amount=Decimal("-25"),
                ),
                TushareMoneyflowDc(
                    ts_code="000001.SZ",
                    trade_date=date(2026, 7, 18),
                    net_amount=Decimal("999999"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=signal_date,
                    content_type="行业",
                    ts_code="BK0001.DC",
                    name="元件",
                    net_amount=Decimal("-999999999"),
                    net_amount_rate=Decimal("-99"),
                ),
            ]
        )
        db.commit()

        context = load_tushare_industry_moneyflow_map(
            db,
            ["元器件"],
            signal_date,
        )["元器件"]

    assert context["sector_fund_flow_source"] == "local_stock_moneyflow_dc"
    assert context["sector_fund_flow_coverage_ratio"] == 1.0
    assert context["sector_fund_flow_net_amount"] == 750000.0
    assert context["sector_fund_flow_rate"] == 5.0
    assert context["sector_fund_flow_score"] == 75.0


def test_local_industry_moneyflow_falls_back_when_stock_coverage_is_incomplete() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 17)

    with Session(engine) as db:
        db.add_all(
            [
                _security("000001", exchange="SZ", industry="银行"),
                _security("000002", exchange="SZ", industry="银行"),
                _bar("000001", signal_date),
                _bar("000002", signal_date),
                TushareMoneyflowDc(
                    ts_code="000001.SZ",
                    trade_date=signal_date,
                    net_amount=Decimal("100"),
                ),
                TushareMoneyflowIndDc(
                    trade_date=signal_date,
                    content_type="行业",
                    ts_code="BK0002.DC",
                    name="银行",
                    net_amount=Decimal("500000000"),
                    net_amount_rate=Decimal("3.5"),
                ),
            ]
        )
        db.commit()

        context = load_tushare_industry_moneyflow_map(
            db,
            ["银行"],
            signal_date,
        )["银行"]

    assert context["sector_fund_flow_source"] == "tushare_industry_moneyflow"
    assert context["sector_fund_flow_net_amount"] == 500000000.0
    assert context["sector_fund_flow_rate"] == 3.5
    assert context["sector_fund_flow_score"] == 67.5


def test_local_industry_moneyflow_uses_full_turnover_at_minimum_coverage() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 17)

    with Session(engine) as db:
        rows = []
        for index in range(1, 51):
            symbol = f"{index:06d}"
            bar = _bar(symbol, signal_date)
            bar.amount = Decimal("51000000" if index == 50 else "1000000")
            rows.extend([_security(symbol, exchange="SZ", industry="银行"), bar])
            if index < 50:
                rows.append(
                    TushareMoneyflowDc(
                        ts_code=f"{symbol}.SZ",
                        trade_date=signal_date,
                        net_amount=Decimal("1"),
                    )
                )
        db.add_all(rows)
        db.commit()

        context = load_tushare_industry_moneyflow_map(
            db,
            ["银行"],
            signal_date,
        )["银行"]

    assert context["sector_fund_flow_coverage_ratio"] == 0.98
    assert context["sector_fund_flow_net_amount"] == 490000.0
    assert context["sector_fund_flow_rate"] == 0.49
    assert context["sector_fund_flow_score"] == 52.45


def test_local_industry_moneyflow_does_not_use_current_active_status_for_history() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 17)
    inactive = _security("000002", exchange="SZ", industry="银行")
    inactive.is_active = False

    with Session(engine) as db:
        db.add_all(
            [
                _security("000001", exchange="SZ", industry="银行"),
                inactive,
                _bar("000001", signal_date),
                _bar("000002", signal_date),
                TushareMoneyflowDc(
                    ts_code="000001.SZ",
                    trade_date=signal_date,
                    net_amount=Decimal("100"),
                ),
                TushareMoneyflowDc(
                    ts_code="000002.SZ",
                    trade_date=signal_date,
                    net_amount=Decimal("-100"),
                ),
            ]
        )
        db.commit()

        context = load_tushare_industry_moneyflow_map(
            db,
            ["银行"],
            signal_date,
        )["银行"]

    assert context["sector_fund_flow_coverage_ratio"] == 1.0
    assert context["sector_fund_flow_rate"] == 0.0
    assert context["sector_fund_flow_score"] == 50.0


def test_watchlist_batches_industry_moneyflow_for_same_date(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 17)
    calls: list[tuple[list[str], date]] = []

    def fake_load(_db, sector_codes, trade_date):
        calls.append((list(sector_codes), trade_date))
        return {"银行": {"sector_fund_flow_score": 60.0}}

    monkeypatch.setattr(
        watchlist,
        "load_tushare_industry_moneyflow_map",
        fake_load,
        raising=False,
    )
    with Session(engine) as db:
        db.add_all(
            [
                _security("000001", exchange="SZ", industry="银行"),
                _security("000002", exchange="SZ", industry="银行"),
                _feature("000001", signal_date),
                _feature("000002", signal_date),
                _bar("000001", signal_date),
                _bar("000002", signal_date),
            ]
        )
        db.commit()

        watchlist.generate_watchlist_observation_plans(
            db=db,
            plan_date=signal_date.isoformat(),
            trade_date="2026-07-20",
            feature_date=signal_date.isoformat(),
            symbols=["000001", "000002"],
        )

    assert calls == [(["银行"], signal_date)]


def test_multi_symbol_backtest_batches_industry_moneyflow_by_date(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    signal_date = date(2026, 7, 17)
    calls: list[tuple[list[str], date]] = []

    def fake_load(_db, sector_codes, trade_date):
        calls.append((list(sector_codes), trade_date))
        return {"银行": {"sector_fund_flow_score": 60.0}}

    monkeypatch.setattr(
        backtest_repository,
        "load_tushare_industry_moneyflow_map",
        fake_load,
        raising=False,
    )
    with Session(engine) as db:
        db.add_all(
            [
                _security("000001", exchange="SZ", industry="银行"),
                _security("000002", exchange="SZ", industry="银行"),
                _feature("000001", signal_date),
                _feature("000002", signal_date),
                _bar("000001", signal_date),
                _bar("000002", signal_date),
            ]
        )
        db.commit()

        backtest_repository.load_many_backtest_inputs(
            db,
            symbols=["000001", "000002"],
            start_date=signal_date,
            end_date=signal_date,
        )

    assert calls == [(["银行"], signal_date)]


def test_build_strategy_context_uses_sector_breadth_and_momentum_from_sector_features() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        security = Security(
            symbol="603083",
            name="剑桥科技",
            exchange="SH",
            industry="通信设备",
            sector_style="growth_cycle",
            holding_style="monthly_trend",
            analysis_framework="tech_growth_cycle",
            is_active=True,
        )
        feature_row = StockFeatureDaily(
            symbol="603083",
            trade_date=date(2026, 6, 24),
            features={"trend_score": 80, "relative_strength_score": 72},
        )
        bar = DailyBar(
            symbol="603083",
            trade_date=date(2026, 6, 24),
            open=Decimal("12.46"),
            high=Decimal("12.51"),
            low=Decimal("12.34"),
            close=Decimal("12.34"),
            pre_close=Decimal("12.46"),
            volume=Decimal("1012818.01"),
            amount=Decimal("1255113.972"),
            turnover_rate=Decimal("1.23"),
            limit_up=Decimal("13.71"),
            limit_down=Decimal("11.21"),
            is_suspended=False,
        )
        db.add_all([security, feature_row, bar])
        db.commit()

        context = build_strategy_context(
            db,
            feature_row=feature_row,
            security=security,
            bar=bar,
            sector_feature_map={
                "通信设备": {
                    "sector_strength_score": 76,
                    "sector_breadth_score": 61,
                    "sector_momentum_score": 63,
                    "sector_sample_confidence": 0.4,
                }
            },
        )

    assert context["sector_breadth_score"] == 61
    assert context["sector_momentum_score"] == 63
