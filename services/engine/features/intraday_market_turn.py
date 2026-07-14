from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class IntradayMarketTurnState:
    key: str
    label: str
    summary: str
    confirmed_signals: tuple[str, ...]
    pending_signals: tuple[str, ...]
    startup_watch_allowed: bool
    core_action_allowed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def classify_intraday_market_turn(
    *,
    breadth_ratio: float,
    index_change_pct: float | None,
    prior_index_low_pct: float | None,
    amount_supported: bool,
    sector_expansion_count: int,
    data_ready: bool,
    prior_snapshot_count: int,
) -> IntradayMarketTurnState:
    if not data_ready or prior_snapshot_count < 1:
        return IntradayMarketTurnState(
            key="watch_repair",
            label="观察修复",
            summary="盘中全市场快照或早盘对照不足，先记录，不升级启动观察。",
            confirmed_signals=(),
            pending_signals=("盘中数据完整性", "早盘低点对照"),
            startup_watch_allowed=False,
            core_action_allowed=False,
        )

    signals = {
        "市场宽度修复": breadth_ratio >= 0.55,
        "指数守住早盘低点": (
            index_change_pct is not None
            and prior_index_low_pct is not None
            and index_change_pct >= prior_index_low_pct - 0.001
        ),
        "成交承接": amount_supported,
        "板块同步回流": sector_expansion_count >= 3,
    }
    confirmed = tuple(label for label, value in signals.items() if value)
    pending = tuple(label for label, value in signals.items() if not value)
    if len(confirmed) == len(signals):
        return IntradayMarketTurnState(
            key="repair_confirmed",
            label="修复确认",
            summary="宽度、指数低点、成交承接和板块回流同步，允许跟踪启动观察。",
            confirmed_signals=confirmed,
            pending_signals=pending,
            startup_watch_allowed=True,
            core_action_allowed=False,
        )
    return IntradayMarketTurnState(
        key="watch_repair",
        label="观察修复",
        summary="盘中修复信号尚未同步，只保留观察。",
        confirmed_signals=confirmed,
        pending_signals=pending,
        startup_watch_allowed=False,
        core_action_allowed=False,
    )
