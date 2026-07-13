from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.collector import sync as collector_sync
from services.collector import tushare_proxy_client as client
from services.collector import tushare_sync
from services.collector.tushare_sync import (
    sync_tushare_daily,
    sync_tushare_daily_basic,
    sync_tushare_index_daily,
    sync_tushare_moneyflow,
    sync_tushare_moneyflow_ind_dc,
    sync_tushare_stk_limit,
    sync_tushare_stock_basic,
)
from services.shared import models
from services.shared.database import Base
from services.shared.models import (
    DailyBar,
    Security,
    TradingCalendar,
    TushareDaily,
    TushareDailyBasic,
    TushareMoneyflow,
    TushareMoneyflowIndDc,
    TushareStkLimit,
)


def test_tushare_5000_sync_writes_idempotent_daily_rows(monkeypatch) -> None:
    assert hasattr(models, "TushareMoneyflowDc")
    assert hasattr(models, "TushareLimitListD")
    assert hasattr(models, "TushareCyqPerf")
    assert hasattr(tushare_sync, "sync_tushare_moneyflow_dc")
    assert hasattr(tushare_sync, "sync_tushare_limit_list_d")
    assert hasattr(tushare_sync, "sync_tushare_cyq_perf")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    class FakeResponse:
        def __init__(self, fields, items):
            self.fields = fields
            self.items = items

    responses = {
        "moneyflow_dc": FakeResponse(
            [
                "trade_date",
                "ts_code",
                "name",
                "pct_change",
                "close",
                "net_amount",
                "net_amount_rate",
                "buy_elg_amount",
                "buy_elg_amount_rate",
                "buy_lg_amount",
                "buy_lg_amount_rate",
                "buy_md_amount",
                "buy_md_amount_rate",
                "buy_sm_amount",
                "buy_sm_amount_rate",
            ],
            [
                [
                    "20260710",
                    "000001.SZ",
                    "样本",
                    2.1,
                    10.5,
                    120.0,
                    1.23,
                    20.0,
                    0.2,
                    60.0,
                    0.6,
                    40.0,
                    0.4,
                    -120.0,
                    -1.2,
                ]
            ],
        ),
        "limit_list_d": FakeResponse(
            [
                "trade_date",
                "ts_code",
                "industry",
                "name",
                "close",
                "pct_chg",
                "amount",
                "limit_amount",
                "float_mv",
                "total_mv",
                "turnover_ratio",
                "fd_amount",
                "first_time",
                "last_time",
                "open_times",
                "up_stat",
                "limit_times",
                "limit",
            ],
            [
                [
                    "20260710",
                    "000001.SZ",
                    "软件开发",
                    "样本",
                    10.5,
                    10.0,
                    1000,
                    500,
                    10000,
                    12000,
                    5.2,
                    300,
                    "093100",
                    "094800",
                    2,
                    "2/3",
                    2,
                    "U",
                ]
            ],
        ),
        "cyq_perf": FakeResponse(
            [
                "ts_code",
                "trade_date",
                "his_low",
                "his_high",
                "cost_5pct",
                "cost_15pct",
                "cost_50pct",
                "cost_85pct",
                "cost_95pct",
                "weight_avg",
                "winner_rate",
            ],
            [["000001.SZ", "20260710", 8, 15, 8.5, 9, 10.2, 11.4, 12, 10.4, 91.5]],
        ),
    }
    monkeypatch.setattr(client, "query", lambda api_name, params=None: responses[api_name])

    with Session(engine) as db:
        for _ in range(2):
            assert tushare_sync.sync_tushare_moneyflow_dc(db, trade_date="20260710") == 1
            assert tushare_sync.sync_tushare_limit_list_d(db, trade_date="20260710") == 1
            assert tushare_sync.sync_tushare_cyq_perf(db, trade_date="20260710") == 1
            db.commit()

        assert db.query(models.TushareMoneyflowDc).count() == 1
        assert db.query(models.TushareLimitListD).count() == 1
        assert db.query(models.TushareCyqPerf).count() == 1
        assert db.query(models.TushareMoneyflowDc).one().net_amount_rate == Decimal("1.230000")
        assert db.query(models.TushareLimitListD).one().open_times == 2
        assert db.query(models.TushareCyqPerf).one().winner_rate == Decimal("91.500000")


def test_tushare_5000_sync_rejects_missing_primary_keys(monkeypatch) -> None:
    assert hasattr(tushare_sync, "sync_tushare_moneyflow_dc")

    class FakeResponse:
        fields = ["trade_date", "ts_code", "net_amount_rate"]
        items = [["20260710", None, 1.23]]

    monkeypatch.setattr(client, "query", lambda api_name, params=None: FakeResponse())
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db, pytest.raises(ValueError, match="ts_code or trade_date"):
        tushare_sync.sync_tushare_moneyflow_dc(db, trade_date="20260710")


def test_tushare_sync_writes_core_tables(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    class FakeResponse:
        def __init__(self, fields, items):
            self.fields = fields
            self.items = items
            self.has_more = False
            self.count = len(items)

    def fake_query(api_name, params=None):
        if api_name == "daily":
            return FakeResponse(
                [
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "pre_close",
                    "change",
                    "pct_chg",
                    "vol",
                    "amount",
                ],
                [
                    [
                        "000001.SZ",
                        "20250729",
                        12.46,
                        12.51,
                        12.34,
                        12.34,
                        12.46,
                        -0.12,
                        -0.9631,
                        1012818.01,
                        1255113.972,
                    ]
                ],
            )
        if api_name == "daily_basic":
            return FakeResponse(
                [
                    "ts_code",
                    "trade_date",
                    "turnover_rate",
                    "volume_ratio",
                    "pe_ttm",
                    "pb",
                    "total_mv",
                    "circ_mv",
                ],
                [["000001.SZ", "20250729", 1.23, 0.98, 8.76, 1.11, 123456.78, 123456.78]],
            )
        if api_name == "stk_limit":
            return FakeResponse(
                ["ts_code", "trade_date", "up_limit", "down_limit"],
                [["000001.SZ", "20250729", 13.71, 11.21]],
            )
        if api_name == "moneyflow":
            return FakeResponse(
                [
                    "ts_code",
                    "trade_date",
                    "buy_sm_amount",
                    "sell_sm_amount",
                    "buy_md_amount",
                    "sell_md_amount",
                    "buy_lg_amount",
                    "sell_lg_amount",
                    "buy_elg_amount",
                    "sell_elg_amount",
                    "net_mf_amount",
                ],
                [["000001.SZ", "20250729", 1, 2, 3, 4, 5, 6, 7, 8, 9]],
            )
        if api_name == "moneyflow_ind_dc":
            return FakeResponse(
                [
                    "trade_date",
                    "content_type",
                    "ts_code",
                    "name",
                    "pct_change",
                    "close",
                    "net_amount",
                    "net_amount_rate",
                ],
                [["20250729", "行业", "BK1044.DC", "生物制品", 2.49, 1163.63, 1822121040, 6.07]],
            )
        raise AssertionError(api_name)

    monkeypatch.setattr(client, "query", fake_query)

    with Session(engine) as db:
        assert sync_tushare_daily(db, trade_date="20250729") == 1
        assert sync_tushare_daily_basic(db, trade_date="20250729") == 1
        assert sync_tushare_stk_limit(db, trade_date="20250729") == 1
        assert sync_tushare_moneyflow(db, trade_date="20250729") == 1
        assert sync_tushare_moneyflow_ind_dc(db, trade_date="20250729") == 1
        db.commit()

        assert db.query(TushareDaily).count() == 1
        assert db.query(TushareDailyBasic).count() == 1
        assert db.query(TushareStkLimit).count() == 1
        assert db.query(TushareMoneyflow).count() == 1
        assert db.query(TushareMoneyflowIndDc).count() == 1
        tushare_daily = db.query(TushareDaily).one()
        assert tushare_daily.trade_date == date(2025, 7, 29)
        daily_bar = db.query(DailyBar).one()
        assert daily_bar.symbol == "000001"
        assert daily_bar.trade_date == date(2025, 7, 29)
        assert daily_bar.close == tushare_daily.close
        assert float(daily_bar.amount) == 1255113972.0


def test_sync_tushare_index_daily_writes_prefixed_daily_bar(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    class FakeResponse:
        fields = [
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "vol",
            "amount",
        ]
        items = [
            [
                "000001.SH",
                "20260707",
                3460.12,
                3480.55,
                3420.18,
                3432.10,
                3470.30,
                -38.20,
                -1.1008,
                398765432,
                543210987.65,
            ]
        ]
        has_more = False
        count = 1

    monkeypatch.setattr(client, "query", lambda api_name, params=None: FakeResponse())

    with Session(engine) as db:
        rows = sync_tushare_index_daily(
            db,
            ts_code="000001.SH",
            start_date="20260707",
            end_date="20260707",
            symbol="sh000001",
        )
        db.commit()

        bar = db.query(DailyBar).one()

    assert rows == 1
    assert bar.symbol == "sh000001"
    assert bar.trade_date == date(2026, 7, 7)
    assert float(bar.close) == 3432.10
    assert float(bar.pre_close) == 3470.30
    assert float(bar.amount) == 543210987650.0


def test_sync_recent_tushare_sector_moneyflow_backfills_missing_open_dates(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                TradingCalendar(trade_date=date(2026, 6, 20), is_open=False),
                TradingCalendar(trade_date=date(2026, 6, 23), is_open=True),
                TradingCalendar(trade_date=date(2026, 6, 24), is_open=True),
                TradingCalendar(trade_date=date(2026, 6, 25), is_open=True),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 23),
                    content_type="行业",
                    ts_code="BK001",
                    name="半导体",
                    pct_change=None,
                    close=None,
                    net_amount=None,
                    net_amount_rate=None,
                ),
            ]
        )
        db.commit()

    captured: list[str] = []

    def fake_session_local():
        return Session(engine)

    def fake_sync(db, *, trade_date: str) -> int:
        captured.append(trade_date)
        return 89

    monkeypatch.setattr(collector_sync, "SessionLocal", fake_session_local)
    monkeypatch.setattr(collector_sync, "sync_tushare_moneyflow_ind_dc", fake_sync)

    result = collector_sync.sync_recent_tushare_sector_moneyflow(
        "2026-06-25",
        lookback_open_days=5,
    )

    assert captured == ["20260624", "20260625"]
    assert [item.status for item in result] == ["ok", "ok"]
    assert [item.rows for item in result] == [89, 89]


def test_sync_tushare_market_data_resumable_skips_existing_datasets(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            TushareDaily(
                ts_code="000001.SZ",
                trade_date=date(2025, 4, 7),
                open=None,
                high=None,
                low=None,
                close=None,
                pre_close=None,
                change=None,
                pct_chg=None,
                vol=None,
                amount=None,
            )
        )
        db.commit()

    captured: list[str] = []

    def fake_session_local():
        return Session(engine)

    def fake_daily(db, *, trade_date: str, ts_code: str | None = None) -> int:
        raise AssertionError("daily should be skipped when rows already exist")

    def fake_daily_basic(db, *, trade_date: str) -> int:
        captured.append(trade_date)
        return 5000

    monkeypatch.setattr(collector_sync, "SessionLocal", fake_session_local)
    monkeypatch.setattr(collector_sync, "sync_tushare_daily", fake_daily)
    monkeypatch.setattr(collector_sync, "sync_tushare_daily_basic", fake_daily_basic)

    result = collector_sync.sync_tushare_market_data_resumable(
        "20250407",
        datasets=("daily", "daily_basic"),
    )

    assert captured == ["20250407"]
    assert [(item.dataset, item.status, item.rows) for item in result] == [
        ("daily", "skipped", 1),
        ("daily_basic", "ok", 5000),
    ]


def test_sync_tushare_market_data_resumable_keeps_going_after_dataset_failure(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    captured: list[str] = []

    def fake_session_local():
        return Session(engine)

    def failing_daily(db, *, trade_date: str, ts_code: str | None = None) -> int:
        captured.append(f"daily:{trade_date}")
        raise RuntimeError("proxy timeout")

    def working_sector_flow(db, *, trade_date: str) -> int:
        captured.append(f"moneyflow_ind_dc:{trade_date}")
        return 93

    monkeypatch.setattr(collector_sync, "SessionLocal", fake_session_local)
    monkeypatch.setattr(collector_sync, "sync_tushare_daily", failing_daily)
    monkeypatch.setattr(collector_sync, "sync_tushare_moneyflow_ind_dc", working_sector_flow)

    result = collector_sync.sync_tushare_market_data_resumable(
        "20250407",
        datasets=("daily", "moneyflow_ind_dc"),
    )

    assert captured == ["daily:20250407", "moneyflow_ind_dc:20250407"]
    assert [item.dataset for item in result] == ["daily", "moneyflow_ind_dc"]
    assert result[0].status == "failed"
    assert "proxy timeout" in result[0].message
    assert result[1].status == "ok"
    assert result[1].rows == 93


def test_backfill_tushare_market_data_uses_open_calendar_dates(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                TradingCalendar(trade_date=date(2025, 4, 4), is_open=False),
                TradingCalendar(trade_date=date(2025, 4, 7), is_open=True),
                TradingCalendar(trade_date=date(2025, 4, 8), is_open=True),
            ]
        )
        db.commit()

    captured: list[str] = []

    def fake_session_local():
        return Session(engine)

    def fake_resumable(trade_date: str, **kwargs):
        captured.append(trade_date)
        return [
            collector_sync.CollectionResult(
                source="tushare_proxy",
                dataset="daily",
                trade_date=trade_date,
                rows=1,
                status="ok",
            )
        ]

    monkeypatch.setattr(collector_sync, "SessionLocal", fake_session_local)
    monkeypatch.setattr(collector_sync, "sync_tushare_market_data_resumable", fake_resumable)

    result = collector_sync.backfill_tushare_market_data(
        "20250404",
        "20250408",
        datasets=("daily",),
        sync_stock_basic_once=False,
    )

    assert captured == ["20250407", "20250408"]
    assert [item.trade_date for item in result] == ["20250407", "20250408"]


def test_tushare_stock_basic_sync_updates_security_industries(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    class FakeResponse:
        def __init__(self, fields, items):
            self.fields = fields
            self.items = items
            self.has_more = False
            self.count = len(items)

    def fake_query(api_name, params=None):
        if api_name != "stock_basic":
            raise AssertionError(api_name)
        return FakeResponse(
            ["ts_code", "symbol", "name", "industry", "market", "list_date"],
            [
                ["000001.SZ", "000001", "平安银行", "银行", "主板", "19910403"],
                ["600519.SH", "600519", "贵州茅台", "白酒", "主板", "20010827"],
            ],
        )

    monkeypatch.setattr(client, "query", fake_query)

    with Session(engine) as db:
        rows = sync_tushare_stock_basic(db)
        db.commit()

        assert rows == 2
        assert db.query(Security).count() == 2
        assert db.query(Security).filter(Security.symbol == "000001").one().industry == "银行"
        assert db.query(Security).filter(Security.symbol == "600519").one().industry == "白酒"
