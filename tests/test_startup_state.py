from datetime import date, datetime

from services.engine.intraday.startup_state import StartupEvidence, resolve_startup_state


def _evidence(**overrides) -> StartupEvidence:
    values = {
        "trade_date": date(2026, 7, 22),
        "as_of": datetime(2026, 7, 22, 10, 30),
        "individual_supportive": True,
        "volume_confirmed": True,
        "sector_sustained": True,
        "sector_strength_holding": False,
        "formal_eligible": True,
        "market_risk_off": False,
        "hard_risk_reasons": (),
    }
    values.update(overrides)
    return StartupEvidence(**values)


def test_confirmation_requires_sector_individual_and_market_evidence() -> None:
    assert resolve_startup_state("probing", _evidence()).state == "confirmed"
    assert (
        resolve_startup_state("probing", _evidence(sector_sustained=False)).state
        == "probing"
    )
    assert (
        resolve_startup_state(
            "probing",
            _evidence(volume_confirmed=False, sector_strength_holding=False),
        ).state
        == "probing"
    )
    assert (
        resolve_startup_state("probing", _evidence(market_risk_off=True)).state
        == "invalidated"
    )


def test_invalidation_is_terminal_for_same_trade_date() -> None:
    result = resolve_startup_state("invalidated", _evidence())

    assert result.state == "invalidated"
    assert result.transitioned is False


def test_missing_sector_before_1030_does_not_invalidate() -> None:
    result = resolve_startup_state(
        "probing",
        _evidence(
            as_of=datetime(2026, 7, 22, 9, 45),
            sector_sustained=False,
        ),
    )

    assert result.state == "probing"
    assert "等待10:30板块持续扩散确认" in result.next_conditions


def test_hard_risk_invalidates_with_reason() -> None:
    result = resolve_startup_state(
        "confirmed",
        _evidence(hard_risk_reasons=("板块转弱",)),
    )

    assert result.state == "invalidated"
    assert result.invalidation_reasons == ("板块转弱",)


def test_confirmed_state_does_not_fall_back_without_invalidation() -> None:
    result = resolve_startup_state(
        "confirmed",
        _evidence(sector_sustained=False, formal_eligible=False),
    )

    assert result.state == "confirmed"
    assert result.transitioned is False


def test_value_reversion_confirmation_does_not_require_sector_or_market_gate() -> None:
    result = resolve_startup_state(
        "probing",
        _evidence(
            confirmation_path="value_reversion",
            confirmation_ready=True,
            sector_sustained=False,
            formal_eligible=False,
            market_risk_off=True,
        ),
    )

    assert result.state == "confirmed"
    assert result.confirmation_evidence == (
        "突破近3日平台",
        "成交额温和放大",
        "日内价格位置偏强",
    )


def test_value_reversion_hard_risk_still_invalidates() -> None:
    result = resolve_startup_state(
        "confirmed",
        _evidence(
            confirmation_path="value_reversion",
            confirmation_ready=True,
            hard_risk_reasons=("跌破近3日平台低点",),
        ),
    )

    assert result.state == "invalidated"
    assert result.invalidation_reasons == ("跌破近3日平台低点",)


def test_value_reversion_not_ready_cannot_fall_back_to_sector_confirmation() -> None:
    result = resolve_startup_state(
        "probing",
        _evidence(
            confirmation_path="value_reversion",
            confirmation_ready=False,
            pending_conditions=("等待成交额温和放大",),
        ),
    )

    assert result.state == "probing"
    assert result.next_conditions == ("等待成交额温和放大",)
