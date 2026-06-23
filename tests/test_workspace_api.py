from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.routers.workspace import (
    ManualStockRequest,
    add_manual_stock,
    get_workspace_stock,
    list_workspace_stocks,
)
from services.shared.database import Base
from services.shared.models import (
    BacktestTradeRecord,
    DailyBar,
    ResearchPoolItem,
    Security,
    TradePlan,
)


def test_list_workspace_stocks_merges_auto_plans_and_manual_pool() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="000001", name="平安银行", exchange="SZ", industry="银行"))
        db.add(ResearchPoolItem(pool_name="manual", symbol="600519", tags_json={"tags": ["白酒"]}))
        db.add(Security(symbol="600519", name="贵州茅台", exchange="SH", industry="白酒"))
        for symbol in ["000001", "600519"]:
            for day in range(1, 22):
                db.add(
                    DailyBar(
                        symbol=symbol,
                        trade_date=date(2026, 1, day),
                        open=Decimal(day),
                        high=Decimal(day + 1),
                        low=Decimal(day - 1),
                        close=Decimal(day),
                        pre_close=Decimal(day - 1) if day > 1 else None,
                        volume=Decimal(day * 100),
                        amount=Decimal(day * 1000),
                        turnover_rate=None,
                        limit_up=Decimal(day) * Decimal("1.1"),
                        limit_down=Decimal(day) * Decimal("0.9"),
                        is_suspended=False,
                    )
                )
        db.add(
            TradePlan(
                plan_date=date(2026, 1, 21),
                trade_date=date(2026, 1, 22),
                symbol="000001",
                rule_id="R001",
                strategy_type="short_term",
                sector_code=None,
                entry_condition_json={},
                position_size=Decimal("0.10"),
                confidence_score=Decimal("80"),
                status="planned",
            )
        )
        db.add(
            BacktestTradeRecord(
                run_date=date(2026, 1, 21),
                rule_id="R001",
                symbol="000001",
                signal_date=date(2026, 1, 10),
                entry_date=date(2026, 1, 11),
                entry_price=Decimal("10"),
                exit_date=date(2026, 1, 15),
                exit_price=Decimal("11"),
                holding_days=5,
                pnl_pct=Decimal("0.10"),
                mfe_pct=Decimal("0.15"),
                mae_pct=Decimal("-0.03"),
                exit_reason="take_profit",
            )
        )
        db.commit()

        payload = list_workspace_stocks(db=db)

    assert [item.symbol for item in payload] == ["000001", "600519"]
    assert payload[0].source == "auto"
    assert payload[0].plans[0].rule_id == "R001"
    assert payload[0].strategy_summaries[0].win_rate == 1
    assert payload[0].recent_backtest_trades[0].entry_date == "2026-01-11"
    assert payload[1].source == "manual"
    assert payload[1].manual_tags == ["白酒"]
    assert payload[0].return_5d is not None


def test_workspace_stock_detail_and_manual_add() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        added = add_manual_stock(
            payload=ManualStockRequest(symbol="000001", note="观察银行", tags=["银行"]),
            db=db,
        )
        loaded = get_workspace_stock(symbol="000001", db=db)

    assert added.symbol == "000001"
    assert added.source == "manual"
    assert loaded.manual_note == "观察银行"
    assert loaded.manual_tags == ["银行"]
