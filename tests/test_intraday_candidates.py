from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.engine.intraday.candidates import discover_intraday_candidates
from services.shared.database import Base
from services.shared.models import (
    RealtimeQuote,
    ResearchPoolItem,
    SectorFeatureDaily,
    Security,
    TushareMoneyflowIndDc,
)


def _security(symbol: str, name: str, industry: str = "通信设备") -> Security:
    return Security(
        symbol=symbol,
        name=name,
        exchange="SH" if symbol.startswith("6") else "SZ",
        industry=industry,
        is_active=True,
        is_st=False,
    )


def _quote(
    symbol: str,
    quote_time: datetime,
    *,
    price: str,
    open_price: str = "10",
    high: str = "10.8",
    low: str = "9.8",
    pre_close: str = "10",
    volume: str = "1000000",
) -> RealtimeQuote:
    return RealtimeQuote(
        symbol=symbol,
        trade_date=quote_time.date(),
        quote_time=quote_time,
        price=Decimal(price),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        pre_close=Decimal(pre_close),
        pct_change=None,
        volume=Decimal(volume),
        amount=Decimal("1000000"),
        turnover_rate=Decimal("1.2"),
    )


def _candidate(symbol: str, *, rank: int, score: float) -> ResearchPoolItem:
    return ResearchPoolItem(
        pool_name="experiment",
        symbol=symbol,
        tags_json={
            "tags": [
                "after_close_candidate",
                "next_session",
                f"rank:{rank}",
                f"score:{score}",
            ]
        },
        status="active",
    )


def _sector_features(
    sector: str,
    trade_date: date,
    *,
    strength: float,
    continuity: float,
    momentum: float,
    breadth: float,
    avg_return_20d: float,
    positive_20d_rate: float,
) -> SectorFeatureDaily:
    return SectorFeatureDaily(
        sector_code=sector,
        trade_date=trade_date,
        features={
            "sector_strength_score": strength,
            "sector_trend_continuity_score": continuity,
            "sector_momentum_score": momentum,
            "sector_breadth_score": breadth,
            "sector_avg_return_20d": avg_return_20d,
            "sector_positive_20d_rate": positive_20d_rate,
            "sector_stock_count": 12,
        },
    )


def test_discover_intraday_candidates_prioritizes_live_supportive_candidate() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600001", "低开修复"),
                _security("600002", "放量分歧"),
                _candidate("600001", rank=3, score=84),
                _candidate("600002", rank=2, score=86),
                _quote(
                    "600001",
                    datetime(2026, 6, 30, 9, 55),
                    price="9.75",
                    open_price="9.75",
                    high="10.05",
                    low="9.70",
                    volume="100000",
                ),
                _quote(
                    "600001",
                    datetime(2026, 6, 30, 10, 5),
                    price="10.08",
                    open_price="9.75",
                    high="10.12",
                    low="9.70",
                    volume="220000",
                ),
                _quote(
                    "600002",
                    datetime(2026, 6, 30, 9, 55),
                    price="10.85",
                    high="10.95",
                    low="10.2",
                    volume="100000",
                ),
                _quote(
                    "600002",
                    datetime(2026, 6, 30, 10, 5),
                    price="10.1",
                    high="10.95",
                    low="10.0",
                    volume="260000",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    assert result["trade_date"] == "2026-06-30"
    assert [item["symbol"] for item in result["candidates"]] == ["600001", "600002"]
    assert result["candidates"][0]["intraday_state"] == "gap_down_repair"
    assert "intraday_gap_down_repair" in result["candidates"][0]["support_flags"]
    assert result["candidates"][0]["intraday_score"] > result["candidates"][1]["intraday_score"]
    assert result["candidates"][1]["intraday_state"] == "distribution"
    assert "intraday_distribution" in result["candidates"][1]["risk_flags"]


def test_discover_intraday_candidates_uses_latest_candidate_feature_date_only() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600171", "上海贝岭", industry="半导体"),
                _security("600360", "华微电子", industry="半导体"),
                _security("002558", "巨人网络", industry="游戏"),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="600360",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "2026-06-29",
                            "hold_until:2026-07-01",
                            "rank:1",
                            "score:77.06",
                        ]
                    },
                    status="active",
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="600171",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "2026-06-30",
                            "hold_until:2026-07-01",
                            "rank:1",
                            "score:75.32",
                        ]
                    },
                    status="active",
                ),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="002558",
                    tags_json={
                        "tags": [
                            "manual_focus",
                            "after_close_candidate",
                            "next_session",
                            "2026-06-24",
                            "hold_until:2026-06-30",
                            "rank:9",
                        ]
                    },
                    status="active",
                ),
                _quote("600360", datetime(2026, 6, 30, 10, 5), price="10.5"),
                _quote("600171", datetime(2026, 6, 30, 10, 5), price="10.4"),
                _quote("002558", datetime(2026, 6, 30, 10, 5), price="10.3"),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    assert [item["symbol"] for item in result["candidates"]] == ["600171", "002558"]
    assert result["candidate_batch"] == {
        "auto_feature_date": "2026-06-30",
        "auto_hold_until": None,
        "auto_batch_id": None,
        "source_item_count": 3,
        "usable_item_count": 2,
        "current_auto_candidate_count": 1,
        "manual_focus_count": 1,
        "stale_auto_candidate_count": 1,
    }


def test_discover_intraday_candidates_excludes_growth_board_by_default() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("300001", "创业板"),
                _candidate("300001", rank=1, score=90),
                _quote("300001", datetime(2026, 6, 30, 10, 5), price="10.5"),
            ]
        )
        db.commit()

        default_result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
        )
        growth_result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            include_growth_board=True,
        )

    assert default_result["candidates"] == []
    assert [item["symbol"] for item in growth_result["candidates"]] == ["300001"]


def test_discover_intraday_candidates_prefers_strong_sector_without_hard_filtering() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600101", "强板块个股", industry="半导体"),
                _security("600102", "弱板块个股", industry="地产服务"),
                _candidate("600101", rank=4, score=78),
                _candidate("600102", rank=1, score=82),
                _sector_features(
                    "半导体",
                    date(2026, 6, 30),
                    strength=78,
                    continuity=74,
                    momentum=72,
                    breadth=64,
                    avg_return_20d=0.11,
                    positive_20d_rate=68,
                ),
                _sector_features(
                    "地产服务",
                    date(2026, 6, 30),
                    strength=43,
                    continuity=39,
                    momentum=42,
                    breadth=36,
                    avg_return_20d=-0.04,
                    positive_20d_rate=31,
                ),
                _quote("600101", datetime(2026, 6, 30, 10, 0), price="10.1"),
                _quote("600101", datetime(2026, 6, 30, 10, 30), price="10.55"),
                _quote("600102", datetime(2026, 6, 30, 10, 0), price="10.1"),
                _quote("600102", datetime(2026, 6, 30, 10, 30), price="10.55"),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    assert [item["symbol"] for item in result["candidates"]] == ["600101", "600102"]
    strong, weak = result["candidates"]
    assert strong["sector_signal"] == "strong_sector"
    assert "sector_mainline_confirmed" in strong["support_flags"]
    assert weak["sector_signal"] == "weak_sector"
    assert "sector_weak_context" in weak["risk_flags"]
    assert "板块弱势" in "；".join(weak["caution_reasons"])


def test_discover_intraday_candidates_explains_midday_and_late_session_cautions() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600201", "午间未确认", industry="通信设备"),
                _security("600202", "尾盘回落", industry="通信设备"),
                _candidate("600201", rank=1, score=80),
                _candidate("600202", rank=2, score=82),
                _quote(
                    "600201",
                    datetime(2026, 6, 30, 11, 20),
                    price="10.18",
                    open_price="10.0",
                    high="10.35",
                    low="9.95",
                ),
                _quote(
                    "600202",
                    datetime(2026, 6, 30, 14, 40),
                    price="10.05",
                    open_price="10.0",
                    high="10.9",
                    low="10.0",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    by_symbol = {item["symbol"]: item for item in result["candidates"]}
    midday = by_symbol["600201"]
    late = by_symbol["600202"]
    assert midday["review_window"] == "midday"
    assert "午间先看上午承接" in "；".join(midday["caution_reasons"])
    assert late["review_window"] == "late_session"
    assert late["intraday_state"] == "distribution"
    assert "尾盘前不追回落" in "；".join(late["caution_reasons"])


def test_discover_intraday_candidates_marks_after_close_snapshots() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600301", "盘后快照"),
                _candidate("600301", rank=1, score=80),
                _quote("600301", datetime(2026, 6, 30, 15, 5), price="10.2"),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    assert result["candidates"][0]["review_window"] == "after_close"


def test_discover_intraday_candidates_marks_afternoon_tracking_before_late_session() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600302", "下午跟踪"),
                _candidate("600302", rank=1, score=80),
                _quote("600302", datetime(2026, 6, 30, 14, 15), price="10.2"),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    assert result["candidates"][0]["review_window"] == "afternoon"


def test_discover_intraday_candidates_uses_only_snapshots_at_or_before_as_of() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600401", "真实午间"),
                _candidate("600401", rank=1, score=80),
                _quote(
                    "600401",
                    datetime(2026, 6, 30, 10, 30),
                    price="10.1",
                    open_price="10.0",
                    high="10.2",
                    low="9.9",
                ),
                _quote(
                    "600401",
                    datetime(2026, 6, 30, 11, 20),
                    price="10.2",
                    open_price="10.0",
                    high="10.25",
                    low="9.9",
                ),
                _quote(
                    "600401",
                    datetime(2026, 6, 30, 14, 50),
                    price="9.7",
                    open_price="10.0",
                    high="10.9",
                    low="9.65",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
            as_of=datetime(2026, 6, 30, 11, 30),
        )

    candidate = result["candidates"][0]
    assert candidate["quote_time"] == "2026-06-30T11:20:00"
    assert candidate["review_window"] == "midday"
    assert candidate["price"] == 10.2
    assert candidate["intraday_state"] != "distribution"
    assert "intraday_distribution" not in candidate["risk_flags"]


def test_discover_intraday_candidates_marks_volume_confirmation_and_distribution_risk() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600501", "放量上行", industry="半导体"),
                _security("600502", "放量回落", industry="半导体"),
                _candidate("600501", rank=2, score=80),
                _candidate("600502", rank=1, score=84),
                _quote(
                    "600501",
                    datetime(2026, 6, 30, 10, 0),
                    price="10.05",
                    high="10.10",
                    low="9.95",
                    volume="100000",
                ),
                _quote(
                    "600501",
                    datetime(2026, 6, 30, 10, 30),
                    price="10.55",
                    high="10.60",
                    low="9.95",
                    volume="360000",
                ),
                _quote(
                    "600502",
                    datetime(2026, 6, 30, 10, 0),
                    price="10.50",
                    high="10.80",
                    low="10.10",
                    volume="100000",
                ),
                _quote(
                    "600502",
                    datetime(2026, 6, 30, 10, 30),
                    price="10.05",
                    high="10.85",
                    low="10.00",
                    volume="380000",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    by_symbol = {item["symbol"]: item for item in result["candidates"]}
    assert "intraday_volume_confirmed" in by_symbol["600501"]["support_flags"]
    assert "volume_expansion_on_weakness" in by_symbol["600502"]["risk_flags"]
    assert "放量回落" in "；".join(by_symbol["600502"]["caution_reasons"])
    assert by_symbol["600501"]["intraday_score"] > by_symbol["600502"]["intraday_score"]


def test_discover_intraday_candidates_applies_sector_feedback_lightly() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600601", "反馈好板块", industry="半导体"),
                _security("600602", "反馈弱板块", industry="地产服务"),
                _candidate("600601", rank=2, score=80),
                _candidate("600602", rank=1, score=82),
                _quote("600601", datetime(2026, 6, 30, 10, 0), price="10.1"),
                _quote("600601", datetime(2026, 6, 30, 10, 30), price="10.55"),
                _quote("600602", datetime(2026, 6, 30, 10, 0), price="10.1"),
                _quote("600602", datetime(2026, 6, 30, 10, 30), price="10.55"),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
            sector_feedback={
                "半导体": {"held_strength_count": 5, "weakened_count": 0},
                "地产服务": {"held_strength_count": 0, "weakened_count": 4},
            },
        )

    assert [item["symbol"] for item in result["candidates"]] == ["600601", "600602"]
    good, weak = result["candidates"]
    assert "sector_feedback_strength_holding" in good["support_flags"]
    assert "sector_feedback_intraday_weakened" in weak["risk_flags"]
    assert "板块近几日盘中转弱偏多" in "；".join(weak["caution_reasons"])


def test_discover_intraday_candidates_marks_formal_tier_for_confirmed_volume() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600701", "主线放量", industry="半导体"),
                _candidate("600701", rank=2, score=80),
                _sector_features(
                    "半导体",
                    date(2026, 6, 30),
                    strength=80,
                    continuity=76,
                    momentum=74,
                    breadth=66,
                    avg_return_20d=0.12,
                    positive_20d_rate=70,
                ),
                _quote(
                    "600701",
                    datetime(2026, 6, 30, 10, 0),
                    price="10.10",
                    high="10.15",
                    low="9.95",
                    volume="100000",
                ),
                _quote(
                    "600701",
                    datetime(2026, 6, 30, 10, 30),
                    price="10.60",
                    high="10.65",
                    low="9.95",
                    volume="220000",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    candidate = result["candidates"][0]
    assert candidate["selection_tier"] == "formal"
    assert candidate["selection_tier_label"] == "正式候选"
    assert "intraday_volume_confirmed" in candidate["support_flags"]
    assert "强势板块" in candidate["selection_reason"]


def test_discover_intraday_candidates_marks_watch_tier_when_pullback_needs_confirmation() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600801", "午间修复", industry="通信设备"),
                _candidate("600801", rank=1, score=76),
                _sector_features(
                    "通信设备",
                    date(2026, 6, 30),
                    strength=58,
                    continuity=56,
                    momentum=55,
                    breadth=52,
                    avg_return_20d=0.01,
                    positive_20d_rate=51,
                ),
                _quote(
                    "600801",
                    datetime(2026, 6, 30, 11, 20),
                    price="10.30",
                    open_price="10.35",
                    high="10.70",
                    low="10.00",
                    volume="160000",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    candidate = result["candidates"][0]
    assert candidate["intraday_state"] == "pullback_repair"
    assert candidate["selection_tier"] == "watch"
    assert candidate["selection_tier_label"] == "观察确认"
    assert "确认" in candidate["selection_reason"]


def test_discover_intraday_candidates_marks_defer_tier_for_weak_sector() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600901", "弱板块反抽", industry="地产服务"),
                _candidate("600901", rank=1, score=86),
                _sector_features(
                    "地产服务",
                    date(2026, 6, 30),
                    strength=43,
                    continuity=39,
                    momentum=42,
                    breadth=36,
                    avg_return_20d=-0.04,
                    positive_20d_rate=31,
                ),
                _quote("600901", datetime(2026, 6, 30, 10, 0), price="10.10"),
                _quote("600901", datetime(2026, 6, 30, 10, 30), price="10.55"),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    candidate = result["candidates"][0]
    assert candidate["intraday_state"] == "strong_continuation"
    assert candidate["selection_tier"] == "defer"
    assert candidate["selection_tier_label"] == "暂缓"
    assert "板块弱势" in candidate["selection_reason"]


def test_discover_intraday_candidates_keeps_potential_watch_repair_as_watch() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600673", "东阳光", industry="综合类"),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="600673",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "rank:6",
                            "score:51.49",
                            "mode:potential_watch",
                        ]
                    },
                    status="active",
                ),
                _sector_features(
                    "综合类",
                    date(2026, 6, 30),
                    strength=45,
                    continuity=38,
                    momentum=40,
                    breadth=36,
                    avg_return_20d=-0.04,
                    positive_20d_rate=30,
                ),
                _quote(
                    "600673",
                    datetime(2026, 6, 30, 10, 0),
                    price="9.80",
                    open_price="9.72",
                    high="10.05",
                    low="9.70",
                    volume="100000",
                ),
                _quote(
                    "600673",
                    datetime(2026, 6, 30, 10, 35),
                    price="10.18",
                    open_price="9.72",
                    high="10.25",
                    low="9.70",
                    volume="230000",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    candidate = result["candidates"][0]
    assert candidate["symbol"] == "600673"
    assert candidate["intraday_state"] == "gap_down_repair"
    assert candidate["selection_tier"] == "watch"
    assert "板块未确认" in candidate["selection_reason"]
    assert "candidate_potential_watch" in candidate["support_flags"]
    assert "sector_weak_context" in candidate["risk_flags"]


def test_discover_intraday_candidates_keeps_manual_focus_strength_as_watch() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("002050", "三花智控", industry="家用电器"),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="002050",
                    tags_json={"tags": ["manual_focus"]},
                    status="active",
                ),
                _sector_features(
                    "家用电器",
                    date(2026, 6, 30),
                    strength=46,
                    continuity=42,
                    momentum=43,
                    breadth=40,
                    avg_return_20d=-0.02,
                    positive_20d_rate=37,
                ),
                _quote(
                    "002050",
                    datetime(2026, 6, 30, 10, 0),
                    price="10.20",
                    open_price="10.05",
                    high="10.35",
                    low="10.00",
                    volume="100000",
                ),
                _quote(
                    "002050",
                    datetime(2026, 6, 30, 10, 35),
                    price="10.62",
                    open_price="10.05",
                    high="10.70",
                    low="10.00",
                    volume="220000",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    candidate = result["candidates"][0]
    assert candidate["symbol"] == "002050"
    assert candidate["intraday_state"] == "strong_continuation"
    assert candidate["selection_tier"] == "watch"
    assert "手动关注" in candidate["selection_reason"]
    assert "candidate_manual_focus" in candidate["support_flags"]


def test_discover_intraday_candidates_marks_single_strong_manual_snapshot_as_watch() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("002050", "三花智控", industry="家用电器"),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="002050",
                    tags_json={"tags": ["manual_focus"]},
                    status="active",
                ),
                _sector_features(
                    "家用电器",
                    date(2026, 6, 30),
                    strength=46,
                    continuity=42,
                    momentum=43,
                    breadth=40,
                    avg_return_20d=-0.02,
                    positive_20d_rate=37,
                ),
                _quote(
                    "002050",
                    datetime(2026, 6, 30, 10, 35),
                    price="10.46",
                    open_price="10.14",
                    high="10.58",
                    low="9.98",
                    pre_close="10.00",
                    volume="220000",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    candidate = result["candidates"][0]
    assert candidate["symbol"] == "002050"
    assert candidate["intraday_state"] == "strong_continuation"
    assert candidate["selection_tier"] == "watch"
    assert "手动关注" in candidate["selection_reason"]


def test_discover_intraday_candidates_uses_manual_theme_moneyflow_as_watch_support() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("002050", "三花智控", industry="家用电器"),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="002050",
                    tags_json={"tags": ["manual_focus", "theme:机器人"]},
                    status="active",
                ),
                _sector_features(
                    "家用电器",
                    date(2026, 6, 30),
                    strength=42,
                    continuity=38,
                    momentum=35,
                    breadth=36,
                    avg_return_20d=-0.04,
                    positive_20d_rate=32,
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="概念",
                    ts_code="BK001",
                    name="虚拟机器人",
                    pct_change=Decimal("0.0495"),
                    close=Decimal("120"),
                    net_amount=Decimal("4025509888"),
                    net_amount_rate=Decimal("8.11"),
                ),
                _quote(
                    "002050",
                    datetime(2026, 6, 30, 10, 0),
                    price="10.20",
                    open_price="10.10",
                    high="10.65",
                    low="10.00",
                    volume="100000",
                ),
                _quote(
                    "002050",
                    datetime(2026, 6, 30, 10, 35),
                    price="10.42",
                    open_price="10.10",
                    high="10.65",
                    low="10.00",
                    volume="180000",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    candidate = result["candidates"][0]
    assert candidate["symbol"] == "002050"
    assert candidate["intraday_state"] == "pullback_repair"
    assert candidate["selection_tier"] == "watch"
    assert "主题资金" in candidate["selection_reason"]
    assert candidate["theme_signal_label"] == "主题资金支撑"
    assert candidate["theme_signal_reason"] == (
        "虚拟机器人主题资金有支撑（涨幅4.95%，净流入率8.11%），"
        "只作为观察支撑，不单独触发买入"
    )
    assert "theme_moneyflow_supported" in candidate["support_flags"]
    assert "theme:虚拟机器人" in candidate["support_flags"]
    assert "sector_weak_context" in candidate["risk_flags"]


def test_discover_intraday_candidates_infers_theme_moneyflow_from_manual_note() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("002050", "三花智控", industry="家用电器"),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="002050",
                    note="手动关注：机器人趋势龙头观察，行业标签暂时偏粗。",
                    tags_json={"tags": ["manual_focus"]},
                    status="active",
                ),
                _sector_features(
                    "家用电器",
                    date(2026, 6, 30),
                    strength=42,
                    continuity=38,
                    momentum=35,
                    breadth=36,
                    avg_return_20d=-0.04,
                    positive_20d_rate=32,
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="概念",
                    ts_code="BK001",
                    name="虚拟机器人",
                    pct_change=Decimal("0.0495"),
                    close=Decimal("120"),
                    net_amount=Decimal("4025509888"),
                    net_amount_rate=Decimal("8.11"),
                ),
                _quote(
                    "002050",
                    datetime(2026, 6, 30, 10, 0),
                    price="10.20",
                    open_price="10.10",
                    high="10.65",
                    low="10.00",
                    volume="100000",
                ),
                _quote(
                    "002050",
                    datetime(2026, 6, 30, 10, 35),
                    price="10.42",
                    open_price="10.10",
                    high="10.65",
                    low="10.00",
                    volume="180000",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    candidate = result["candidates"][0]
    assert candidate["selection_tier"] == "watch"
    assert "主题资金" in candidate["selection_reason"]
    assert "theme_moneyflow_supported" in candidate["support_flags"]
    assert "theme:虚拟机器人" in candidate["support_flags"]


def test_discover_intraday_candidates_does_not_match_numeric_scores_as_theme_note() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600673", "东阳光", industry="综合类"),
                ResearchPoolItem(
                    pool_name="experiment",
                    symbol="600673",
                    note="策略 POT001 潜力启动观察；趋势 100.0 / 量能 55.0。",
                    tags_json={
                        "tags": [
                            "after_close_candidate",
                            "next_session",
                            "mode:potential_watch",
                        ]
                    },
                    status="active",
                ),
                _sector_features(
                    "综合类",
                    date(2026, 6, 30),
                    strength=42,
                    continuity=38,
                    momentum=35,
                    breadth=36,
                    avg_return_20d=-0.04,
                    positive_20d_rate=32,
                ),
                TushareMoneyflowIndDc(
                    trade_date=date(2026, 6, 30),
                    content_type="概念",
                    ts_code="BK002",
                    name="深证100R",
                    pct_change=Decimal("0.0495"),
                    close=Decimal("120"),
                    net_amount=Decimal("4025509888"),
                    net_amount_rate=Decimal("8.11"),
                ),
                _quote(
                    "600673",
                    datetime(2026, 6, 30, 10, 0),
                    price="10.20",
                    open_price="10.10",
                    high="10.65",
                    low="10.00",
                    volume="100000",
                ),
                _quote(
                    "600673",
                    datetime(2026, 6, 30, 10, 35),
                    price="10.42",
                    open_price="10.10",
                    high="10.65",
                    low="10.00",
                    volume="180000",
                ),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    candidate = result["candidates"][0]
    assert "theme_moneyflow_supported" not in candidate["support_flags"]
    assert "theme:深证100R" not in candidate["support_flags"]


def test_discover_intraday_candidates_orders_formal_before_defer() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _security("600911", "主线确认", industry="半导体"),
                _security("600912", "弱板块高分", industry="地产服务"),
                _candidate("600911", rank=3, score=78),
                _candidate("600912", rank=1, score=95),
                _sector_features(
                    "半导体",
                    date(2026, 6, 30),
                    strength=80,
                    continuity=76,
                    momentum=74,
                    breadth=66,
                    avg_return_20d=0.12,
                    positive_20d_rate=70,
                ),
                _sector_features(
                    "地产服务",
                    date(2026, 6, 30),
                    strength=43,
                    continuity=39,
                    momentum=42,
                    breadth=36,
                    avg_return_20d=-0.04,
                    positive_20d_rate=31,
                ),
                _quote(
                    "600911",
                    datetime(2026, 6, 30, 10, 0),
                    price="10.10",
                    volume="100000",
                ),
                _quote(
                    "600911",
                    datetime(2026, 6, 30, 10, 30),
                    price="10.55",
                    volume="220000",
                ),
                _quote("600912", datetime(2026, 6, 30, 10, 0), price="10.10"),
                _quote("600912", datetime(2026, 6, 30, 10, 30), price="10.55"),
            ]
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    assert [item["symbol"] for item in result["candidates"]] == ["600911", "600912"]
    assert result["candidates"][0]["selection_tier"] == "formal"
    assert result["candidates"][1]["selection_tier"] == "defer"


def test_discover_intraday_candidates_surfaces_watch_candidates_across_sectors() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        rows = []
        for index, symbol in enumerate(["600931", "600932", "600933", "600934"], start=1):
            rows.extend(
                [
                    _security(symbol, f"证券观察{index}", industry="证券"),
                    _candidate(symbol, rank=index, score=96 - index),
                    _quote(symbol, datetime(2026, 6, 30, 10, 0), price="10.10"),
                    _quote(symbol, datetime(2026, 6, 30, 10, 30), price="10.55"),
                ]
            )
        for index, symbol in enumerate(["600941", "600942"], start=5):
            rows.extend(
                [
                    _security(symbol, f"消费观察{index}", industry="食品饮料"),
                    _candidate(symbol, rank=index, score=78 - index),
                    _quote(symbol, datetime(2026, 6, 30, 10, 0), price="10.10"),
                    _quote(symbol, datetime(2026, 6, 30, 10, 30), price="10.55"),
                ]
            )
        db.add_all(rows)
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=4,
        )

    sectors = [item["sector"] for item in result["candidates"]]
    assert sectors.count("证券") == 2
    assert "食品饮料" in sectors


def _add_confirmed_formal_candidate(
    db: Session,
    *,
    symbol: str,
    name: str,
    sector: str,
    rank: int,
    score: float,
) -> None:
    db.add_all(
        [
            _security(symbol, name, industry=sector),
            _candidate(symbol, rank=rank, score=score),
            _quote(
                symbol,
                datetime(2026, 6, 30, 10, 0),
                price="10.10",
                volume="100000",
            ),
            _quote(
                symbol,
                datetime(2026, 6, 30, 10, 30),
                price="10.55",
                volume="220000",
            ),
        ]
    )


def test_discover_intraday_candidates_limits_formal_tier_to_three() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _sector_features(
                    "半导体",
                    date(2026, 6, 30),
                    strength=80,
                    continuity=76,
                    momentum=74,
                    breadth=66,
                    avg_return_20d=0.12,
                    positive_20d_rate=70,
                ),
                _sector_features(
                    "通信设备",
                    date(2026, 6, 30),
                    strength=78,
                    continuity=74,
                    momentum=72,
                    breadth=64,
                    avg_return_20d=0.10,
                    positive_20d_rate=68,
                ),
            ]
        )
        for index, (symbol, sector) in enumerate(
            [
                ("600921", "半导体"),
                ("600922", "半导体"),
                ("600923", "通信设备"),
                ("600924", "通信设备"),
            ],
            start=1,
        ):
            _add_confirmed_formal_candidate(
                db,
                symbol=symbol,
                name=f"强势票{index}",
                sector=sector,
                rank=index,
                score=88 - index,
            )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    formal = [item for item in result["candidates"] if item["selection_tier"] == "formal"]
    watch = [item for item in result["candidates"] if item["selection_tier"] == "watch"]
    assert len(formal) == 3
    assert len(watch) == 1
    assert "正式名额收敛" in watch[0]["selection_reason"]


def test_discover_intraday_candidates_downgrades_formal_on_market_risk_off() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            _sector_features(
                "半导体",
                date(2026, 6, 30),
                strength=82,
                continuity=78,
                momentum=74,
                breadth=66,
                avg_return_20d=0.12,
                positive_20d_rate=70,
            )
        )
        _add_confirmed_formal_candidate(
            db,
            symbol="600925",
            name="强势但弱市",
            sector="半导体",
            rank=1,
            score=90,
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=5,
            market_stress={
                "trade_date": "2026-06-30",
                "snapshot_scope_label": "盘中实时",
                "stress_status": "risk_off",
                "stress_label": "压力大",
                "stress_score": 80.0,
                "risk_action_label": "停止扩散，只做观察和风控",
                "stress_reasons": ["上涨占比仅13%，市场宽度明显不足"],
            },
        )

    item = result["candidates"][0]
    assert result["market_stress"]["trade_date"] == "2026-06-30"
    assert result["market_stress"]["snapshot_scope_label"] == "盘中实时"
    assert result["market_stress"]["stress_status"] == "risk_off"
    assert result["market_stress"]["stress_score"] == 80.0
    assert item["selection_tier"] == "watch"
    assert item["selection_tier_label"] == "观察确认"
    assert "全市场压力大" in item["selection_reason"]
    assert "market_risk_off" in item["risk_flags"]


def test_discover_intraday_candidates_keeps_formal_tier_sector_diversified() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _sector_features(
                    "半导体",
                    date(2026, 6, 30),
                    strength=82,
                    continuity=78,
                    momentum=74,
                    breadth=66,
                    avg_return_20d=0.12,
                    positive_20d_rate=70,
                ),
                _sector_features(
                    "通信设备",
                    date(2026, 6, 30),
                    strength=79,
                    continuity=75,
                    momentum=72,
                    breadth=64,
                    avg_return_20d=0.10,
                    positive_20d_rate=68,
                ),
            ]
        )
        for index, symbol in enumerate(["600931", "600932", "600933"], start=1):
            _add_confirmed_formal_candidate(
                db,
                symbol=symbol,
                name=f"半导体强势{index}",
                sector="半导体",
                rank=index,
                score=90 - index,
            )
        _add_confirmed_formal_candidate(
            db,
            symbol="600934",
            name="通信强势",
            sector="通信设备",
            rank=4,
            score=82,
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
        )

    formal = [item for item in result["candidates"] if item["selection_tier"] == "formal"]
    watch = [item for item in result["candidates"] if item["selection_tier"] == "watch"]
    formal_sectors = [item["sector"] for item in formal]
    assert len(formal) == 3
    assert formal_sectors.count("半导体") == 2
    assert "通信设备" in formal_sectors
    assert len(watch) == 1
    assert watch[0]["sector"] == "半导体"
    assert "同板块正式名额" in watch[0]["selection_reason"]


def test_discover_intraday_candidates_gives_formal_slots_to_stronger_sector_first() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all(
            [
                _sector_features(
                    "半导体",
                    date(2026, 6, 30),
                    strength=84,
                    continuity=80,
                    momentum=78,
                    breadth=70,
                    avg_return_20d=0.15,
                    positive_20d_rate=74,
                ),
                _sector_features(
                    "通信设备",
                    date(2026, 6, 30),
                    strength=69,
                    continuity=66,
                    momentum=59,
                    breadth=53,
                    avg_return_20d=0.03,
                    positive_20d_rate=53,
                ),
            ]
        )
        _add_confirmed_formal_candidate(
            db,
            symbol="600941",
            name="主线低分",
            sector="半导体",
            rank=5,
            score=78,
        )
        _add_confirmed_formal_candidate(
            db,
            symbol="600942",
            name="次线高分",
            sector="通信设备",
            rank=1,
            score=92,
        )
        db.commit()

        result = discover_intraday_candidates(
            db,
            trade_date=date(2026, 6, 30),
            pool_name="experiment",
            limit=10,
            formal_limit=1,
            formal_per_sector_limit=1,
        )

    assert result["candidates"][0]["symbol"] == "600941"
    assert result["candidates"][0]["selection_tier"] == "formal"
    assert result["candidates"][0]["sector_quality_score"] > result["candidates"][1][
        "sector_quality_score"
    ]
    assert result["candidates"][1]["selection_tier"] == "watch"
    assert "正式名额收敛" in result["candidates"][1]["selection_reason"]
