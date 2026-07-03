from datetime import date
from decimal import Decimal

from services.engine.theme.attribution import build_theme_moneyflow_signal
from services.shared.models import TushareMoneyflowIndDc


def _moneyflow(
    name: str,
    *,
    pct_change: str = "4.95",
    flow_rate: str = "8.11",
) -> TushareMoneyflowIndDc:
    return TushareMoneyflowIndDc(
        trade_date=date(2026, 6, 30),
        content_type="概念",
        ts_code=f"BK-{name}",
        name=name,
        pct_change=Decimal(pct_change),
        close=Decimal("120"),
        net_amount=Decimal("4025509888"),
        net_amount_rate=Decimal(flow_rate),
    )


def test_build_theme_moneyflow_signal_matches_explicit_theme_tag() -> None:
    signal = build_theme_moneyflow_signal(
        tags=["manual_focus", "theme:机器人"],
        note=None,
        rows=[_moneyflow("虚拟机器人")],
    )

    assert signal.score_delta == 2.0
    assert signal.theme_name == "虚拟机器人"
    assert signal.pct_change == 4.95
    assert signal.net_amount_rate == 8.11
    assert signal.support_flags == ["theme_moneyflow_supported", "theme:虚拟机器人"]
    assert signal.risk_flags == []
    assert signal.caution_reasons == ["主题资金有支撑，但只修正粗行业标签，不单独触发买入"]


def test_build_theme_moneyflow_signal_infers_theme_from_note() -> None:
    signal = build_theme_moneyflow_signal(
        tags=["manual_focus"],
        note="手动关注：机器人趋势龙头观察，行业标签偏粗。",
        rows=[_moneyflow("虚拟机器人")],
    )

    assert signal.score_delta == 2.0
    assert "theme_moneyflow_supported" in signal.support_flags
    assert "theme:虚拟机器人" in signal.support_flags


def test_build_theme_moneyflow_signal_ignores_numeric_note_matches() -> None:
    signal = build_theme_moneyflow_signal(
        tags=["after_close_candidate", "next_session"],
        note="策略 POT001 潜力启动观察；趋势 100.0 / 量能 55.0。",
        rows=[_moneyflow("深证100R")],
    )

    assert signal.score_delta == 0.0
    assert signal.support_flags == []
