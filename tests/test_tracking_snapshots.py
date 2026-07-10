from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.app.routers.workspace import (
    create_tracking_snapshots,
    list_tracking_signal_summary,
    list_tracking_snapshot_history,
)
from services.engine.tracking.repository import (
    build_tracking_snapshot_payload,
    list_tracking_snapshots,
    summarize_tracking_signal_alignment,
    upsert_tracking_snapshot,
)
from services.engine.workspace.repository import WorkspaceItem
from services.shared.database import Base
from services.shared.models import (
    DailyBar,
    ResearchPoolItem,
    Security,
    StockFeatureDaily,
    StockTrackingSnapshot,
)


def _workspace_item(**overrides) -> WorkspaceItem:
    values = dict(
        symbol="002558",
        name="测试股份",
        industry="电子",
        sector_style="growth_cycle",
        source="manual",
        manual_note="板块强势，个股放量突破",
        manual_tags=["after_close_candidate", "tier:core_action"],
        candidate_rank=1,
        candidate_score=84.0,
        candidate_tier="core_action",
        candidate_tier_label="核心行动",
        candidate_tier_reason="板块和个股趋势同时在线。",
        startup_signal_score=78.0,
        startup_signal_label="启动观察",
        startup_signal_reasons=["量价开始共振"],
        feature_date="2026-07-09",
        latest_trade_date="2026-07-10",
        latest_close=12.0,
        current_price=12.3,
        day_change_pct=0.021,
        quote_time="2026-07-10T10:30:00",
        return_5d=0.06,
        return_20d=0.16,
        trend_score=82.0,
        relative_strength_score=79.0,
        sector_strength_score=76.0,
        volume_confirmation_score=74.0,
        risk_score=24.0,
        overheat_score=28.0,
        volume_trap_risk_score=18.0,
        distance_to_ma20=0.06,
        amount_percentile_60d=0.72,
        amount_ratio_5d=1.35,
        pullback_volume_ratio=0.82,
        ma20_slope_20d=0.03,
        ma60_slope_20d=0.01,
        ma_alignment_score=78.0,
        trend_quality_score=81.0,
        route_score=82.0,
        route_label="主升趋势",
        route_reason="趋势和量能较好",
        plans=[],
        paper_trade_summaries=[],
        recent_paper_trades=[],
    )
    values.update(overrides)
    return WorkspaceItem(**values)


def test_upsert_tracking_snapshot_replaces_same_symbol_date() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        first = upsert_tracking_snapshot(
            db,
            build_tracking_snapshot_payload(
                _workspace_item(),
                snapshot_date=date(2026, 7, 10),
            ),
        )
        second = upsert_tracking_snapshot(
            db,
            build_tracking_snapshot_payload(
                _workspace_item(
                    trend_score=45.0,
                    sector_strength_score=38.0,
                    volume_trap_risk_score=86.0,
                    risk_score=82.0,
                    candidate_tier="risk_reject",
                    candidate_tier_label="淘汰/风险",
                ),
                snapshot_date=date(2026, 7, 10),
            ),
        )
        db.commit()

        rows = db.query(StockTrackingSnapshot).all()
        assert len(rows) == 1
        assert first.id == second.id
        assert rows[0].stage == "risk_review"
        assert rows[0].stage_label == "风险复核"
        assert rows[0].tracking_score < 70
        assert rows[0].metrics_json["trend_score"] == 45.0
        assert "放量诱多" in "；".join(rows[0].risks_json["items"])


def test_list_tracking_snapshots_returns_recent_first() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        for day, score in [(9, 61.0), (10, 72.0), (11, 68.0)]:
            upsert_tracking_snapshot(
                db,
                build_tracking_snapshot_payload(
                    _workspace_item(trend_score=score, candidate_score=score),
                    snapshot_date=date(2026, 7, day),
                ),
            )
        db.commit()

        rows = list_tracking_snapshots(db, symbol="002558", limit=2)

        assert [row.snapshot_date.isoformat() for row in rows] == ["2026-07-11", "2026-07-10"]
        assert rows[0].symbol == "002558"


def test_summarize_tracking_signal_alignment_counts_divergence() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def row(symbol: str, day: int, score: float, price: float) -> StockTrackingSnapshot:
        return StockTrackingSnapshot(
            symbol=symbol,
            snapshot_date=date(2026, 7, day),
            stage="watching",
            stage_label="持续观察",
            tracking_score=score,
            current_price=price,
            latest_close=price,
            name=f"{symbol}测试",
            industry="电子",
            metrics_json={},
            evidence_json={"items": []},
            risks_json={"items": []},
            source_json={},
        )

    with session() as db:
        db.add_all(
            [
                row("000001", 1, 60, 10),
                row("000001", 2, 66, 11),
                row("000002", 1, 58, 10),
                row("000002", 2, 64, 9.6),
                row("000003", 2, 70, 8),
            ]
        )
        db.commit()

        summary = summarize_tracking_signal_alignment(db, symbols=["000001", "000002", "000003"])

        assert summary.symbol_count == 3
        assert summary.aligned_count == 1
        assert summary.divergent_count == 1
        assert summary.insufficient_count == 1
        assert summary.mature_count == 2
        assert summary.maturity_ratio == 0.6667
        assert summary.maturity_label == "可验证"
        assert "2/3" in summary.maturity_note
        assert summary.items[0].symbol == "000002"
        assert summary.items[0].signal_alignment_label == "分涨价弱"
        assert summary.items[1].symbol == "000001"
        assert summary.items[1].signal_alignment_label == "分价同向"


def test_workspace_api_creates_and_reads_tracking_snapshots() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="002558", name="测试股份", exchange="SZ", industry="电子"))
        db.add(
            ResearchPoolItem(
                pool_name="experiment",
                symbol="002558",
                note="板块强势，个股放量突破",
                tags_json={
                    "tags": [
                        "after_close_candidate",
                        "tier:core_action",
                        "score:84",
                        "startup_signal_score:78",
                    ],
                },
            )
        )
        for day in range(1, 23):
            db.add(
                DailyBar(
                    symbol="002558",
                    trade_date=date(2026, 7, day),
                    open=10 + day,
                    high=11 + day,
                    low=9 + day,
                    close=10 + day,
                    pre_close=9 + day if day > 1 else None,
                    volume=1000 + day,
                    amount=10000 + day,
                    turnover_rate=None,
                    limit_up=None,
                    limit_down=None,
                    is_suspended=False,
                )
            )
        db.add(
            StockFeatureDaily(
                symbol="002558",
                trade_date=date(2026, 7, 22),
                features={
                    "trend_score": 82,
                    "trend_quality_score": 81,
                    "relative_strength_score": 79,
                    "sector_strength_score": 76,
                    "volume_confirmation_score": 74,
                    "risk_score": 24,
                    "overheat_score": 28,
                    "volume_trap_risk_score": 18,
                    "amount_ratio_5d": 1.35,
                    "distance_to_ma20": 0.06,
                    "route_score": 82,
                    "route_label": "主升趋势",
                    "route_reason": "趋势和量能较好",
                },
            )
        )
        db.commit()

        created = create_tracking_snapshots(
            db=db,
            pool_name="experiment",
            snapshot_date=date(2026, 7, 22),
        )
        history = list_tracking_snapshot_history(symbol="002558", db=db)

        assert created.created_count == 1
        assert created.snapshot_date == "2026-07-22"
        assert history[0].symbol == "002558"
        assert history[0].stage_label == "启动确认"
        assert history[0].tracking_score >= 75
        assert history[0].metrics["trend_score"] == 82


def test_workspace_api_returns_tracking_signal_summary() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session() as db:
        db.add(Security(symbol="000001", name="一号股份", exchange="SZ", industry="电子"))
        db.add(Security(symbol="000002", name="二号股份", exchange="SZ", industry="电子"))
        for symbol in ["000001", "000002"]:
            db.add(
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol=symbol,
                    status="active",
                    tags_json={"tags": ["manual_focus"]},
                )
            )
        db.add_all(
            [
                StockTrackingSnapshot(
                    symbol="000001",
                    snapshot_date=date(2026, 7, 1),
                    stage="watching",
                    stage_label="持续观察",
                    tracking_score=60,
                    current_price=10,
                    name="一号股份",
                    industry="电子",
                ),
                StockTrackingSnapshot(
                    symbol="000001",
                    snapshot_date=date(2026, 7, 2),
                    stage="watching",
                    stage_label="持续观察",
                    tracking_score=65,
                    current_price=10.8,
                    name="一号股份",
                    industry="电子",
                ),
                StockTrackingSnapshot(
                    symbol="000002",
                    snapshot_date=date(2026, 7, 1),
                    stage="watching",
                    stage_label="持续观察",
                    tracking_score=60,
                    current_price=10,
                    name="二号股份",
                    industry="电子",
                ),
                StockTrackingSnapshot(
                    symbol="000002",
                    snapshot_date=date(2026, 7, 2),
                    stage="watching",
                    stage_label="持续观察",
                    tracking_score=66,
                    current_price=9.8,
                    name="二号股份",
                    industry="电子",
                ),
            ]
        )
        db.commit()

        summary = list_tracking_signal_summary(db=db, pool_name="experiment")

        assert summary.symbol_count == 2
        assert summary.aligned_count == 1
        assert summary.divergent_count == 1
        assert summary.mature_count == 2
        assert summary.maturity_label == "可验证"
        assert summary.items[0].symbol == "000002"
        assert summary.items[0].signal_alignment_label == "分涨价弱"
