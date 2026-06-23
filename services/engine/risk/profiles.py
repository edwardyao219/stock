from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RiskProfile:
    name: str = "default"
    scope_type: str = "global"
    scope_value: str | None = None
    strategy_type: str | None = None
    priority: int = 0
    account_equity: float = 1_000_000.0
    risk_per_trade_pct: float = 0.01
    max_position_pct: float = 0.10
    min_position_pct: float = 0.01
    lot_size: int = 100
    atr_stop_multiple: float = 1.5
    structure_stop_buffer_pct: float = 0.003
    max_stop_loss_pct: float = 0.08
    min_stop_loss_pct: float = 0.015
    take_profit_1_r: float = 1.0
    take_profit_2_r: float = 2.0
    trailing_drawdown_pct: float = 0.06
    max_gap_up_pct: float = 0.06
    breakout_buffer_pct: float = 0.0
    default_max_holding_days: int = 5

    def to_dict(self) -> dict[str, float | int | str]:
        return asdict(self)


DEFAULT_RISK_PROFILE = RiskProfile()

BANKING_COMPOUND_PROFILE = RiskProfile(
    name="banking_compound",
    scope_type="sector",
    scope_value="银行",
    strategy_type=None,
    priority=100,
    risk_per_trade_pct=0.006,
    max_position_pct=0.18,
    min_position_pct=0.03,
    atr_stop_multiple=2.5,
    structure_stop_buffer_pct=0.006,
    max_stop_loss_pct=0.12,
    min_stop_loss_pct=0.025,
    take_profit_1_r=2.0,
    take_profit_2_r=4.0,
    trailing_drawdown_pct=0.10,
    max_gap_up_pct=0.035,
    default_max_holding_days=60,
)

COMPOUND_STYLE_PROFILE = RiskProfile(
    name="compound_style",
    scope_type="style",
    scope_value="compound",
    strategy_type=None,
    priority=80,
    risk_per_trade_pct=0.006,
    max_position_pct=0.16,
    min_position_pct=0.03,
    atr_stop_multiple=2.3,
    structure_stop_buffer_pct=0.006,
    max_stop_loss_pct=0.11,
    min_stop_loss_pct=0.025,
    take_profit_1_r=2.0,
    take_profit_2_r=4.0,
    trailing_drawdown_pct=0.10,
    max_gap_up_pct=0.035,
    default_max_holding_days=60,
)

THEME_SHORT_PROFILE = RiskProfile(
    name="theme_short",
    scope_type="style",
    scope_value="theme",
    strategy_type="short_term",
    priority=50,
    risk_per_trade_pct=0.008,
    max_position_pct=0.08,
    min_position_pct=0.01,
    atr_stop_multiple=1.4,
    structure_stop_buffer_pct=0.003,
    max_stop_loss_pct=0.07,
    min_stop_loss_pct=0.018,
    take_profit_1_r=1.0,
    take_profit_2_r=2.0,
    trailing_drawdown_pct=0.055,
    max_gap_up_pct=0.06,
    default_max_holding_days=5,
)
