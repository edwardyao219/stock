from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from services.engine.plans.context import build_strategy_context, load_sector_feature_map
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
        "tushare_moneyflow_dc": 1,
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
