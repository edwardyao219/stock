from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from services.notifications.dingtalk import DingTalkNotifier
from services.shared.config import get_settings
from services.shared.symbols import is_star_market_symbol

HOT_SECTOR_FOCUS_MIN = 60.0
HOT_SECTOR_CONTINUITY_MIN = 65.0
HOT_SECTOR_RETURN_20D_MIN = 8.0
HOT_SECTOR_POSITIVE_RATIO_MIN = 0.55
ACTION_CANDIDATE_LIMIT = 3
LONG_ACTION_PARTICIPATION_MIN = 45.0
LONG_ACTION_LIQUIDITY_MIN = 35.0
LONG_ACTION_TREND_STYLES = {"growth_cycle", "cyclical", "property_chain"}
LONG_ACTION_STYLE_KEYWORDS = {
    "growth_cycle": (
        "半导体",
        "元器件",
        "通信设备",
        "光学光电子",
        "软件服务",
        "互联网",
        "IT设备",
        "电子化学品",
        "电器仪表",
        "专用机械",
        "机器人",
        "PCB",
    ),
    "cyclical": ("化工", "有色", "铜", "铝", "小金属", "矿", "煤炭", "石油"),
    "property_chain": ("房地产", "建材", "家居", "装修"),
}


@dataclass(frozen=True)
class NotificationResult:
    channel: str
    status: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _enabled_channels() -> set[str]:
    channels = get_settings().notification_channels
    return {item.strip().lower() for item in channels.split(",") if item.strip()}


def _split_message(content: str, max_chars: int = 1800) -> list[str]:
    if len(content) <= max_chars:
        return [content]
    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0
    for line in content.splitlines():
        line_len = len(line) + 1
        if current_lines and current_len + line_len > max_chars:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
            current_len = len(line)
            continue
        current_lines.append(line)
        current_len += line_len
    if current_lines:
        chunks.append("\n".join(current_lines))
    return chunks


def _send_text(content: str) -> list[NotificationResult]:
    settings = get_settings()
    channels = _enabled_channels()
    results: list[NotificationResult] = []
    payloads = _split_message(content)

    if "dingtalk" in channels:
        if not settings.dingtalk_webhook_url:
            results.append(
                NotificationResult(
                    channel="dingtalk",
                    status="skipped",
                    message="DINGTALK_WEBHOOK_URL is not configured",
                )
            )
        else:
            notifier = DingTalkNotifier(
                webhook_url=settings.dingtalk_webhook_url,
                secret=settings.dingtalk_secret,
            )
            for index, payload in enumerate(payloads, start=1):
                final_payload = (
                    payload if len(payloads) == 1 else (f"【{index}/{len(payloads)}】\n{payload}")
                )
                result = notifier.send_text(final_payload)
                results.append(
                    NotificationResult(
                        channel=result.channel,
                        status=result.status,
                        message=result.message,
                    )
                )

    return results


def _compact_reason_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "；".join(str(item) for item in value if item)
    return str(value)


def _alert_judgment_label(alert_type: Any) -> str:
    mapping = {
        "paper_entry_filled": "已买入",
        "paper_entry_deferred": "暂缓买入",
        "stop_loss_touched": "止损触发",
        "take_profit_touched": "止盈触发",
        "limit_up_touched": "接近涨停",
        "limit_down_touched": "接近跌停",
        "t_rhythm_reduce_watch": "做T减仓观察",
        "t_rhythm_add_watch": "做T接回观察",
    }
    return mapping.get(str(alert_type or ""), "提醒")


def _pct_text(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:+.1f}%"


def _snapshot_text(snapshot: Any) -> str:
    if not isinstance(snapshot, dict):
        return ""
    market_risk = snapshot.get("market_risk")
    if isinstance(market_risk, dict):
        return str(market_risk.get("summary") or "")

    parts = []
    label = snapshot.get("label")
    if label:
        parts.append(str(label))
    parts.extend(
        [
            f"昨收{_pct_text(snapshot.get('session_change_pct'))}",
            f"开盘{_pct_text(snapshot.get('open_gap_pct'))}",
            f"较开盘{_pct_text(snapshot.get('change_from_open_pct'))}",
            f"最高{_pct_text(snapshot.get('intraday_high_gain_pct'))}",
            f"回撤{_pct_text(snapshot.get('pullback_from_high_pct'))}",
        ]
    )
    if snapshot.get("range_position") is not None:
        parts.append(f"日内位置{float(snapshot.get('range_position')):.0%}")
    if snapshot.get("volume_pressure_ratio") is not None:
        parts.append(f"量压{float(snapshot.get('volume_pressure_ratio')):.1f}x")
    flags = []
    if snapshot.get("failed_near_limit_up"):
        flags.append("近涨停未封")
    if snapshot.get("spike_reversed_to_red"):
        flags.append("冲高翻绿")
    if flags:
        parts.append("/".join(flags))
    return " | ".join(part for part in parts if part)


def _candidate_screening_items(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = discovery.get("candidates") or []
    candidates = [
        item
        for item in candidates
        if str(item.get("selection_mode") or "").strip() != "exploration"
    ]
    if any("selection_tier" in item for item in candidates):
        candidates = [
            item for item in candidates if str(item.get("selection_tier") or "").strip() == "formal"
        ]
    return _merge_candidate_items_by_symbol(filter_hot_sector_candidates(discovery, candidates))


def _is_hot_sector_focus(item: dict[str, Any]) -> bool:
    focus_score = float(item.get("focus_score") or 0.0)
    continuity = float(item.get("continuity_score") or 0.0)
    avg_return_20d = float(item.get("avg_return_20d_pct") or 0.0)
    positive_ratio = float(item.get("positive_ratio") or 0.0)
    return (
        focus_score >= HOT_SECTOR_FOCUS_MIN
        or (
            continuity >= HOT_SECTOR_CONTINUITY_MIN
            and positive_ratio >= HOT_SECTOR_POSITIVE_RATIO_MIN
        )
        or (
            avg_return_20d >= HOT_SECTOR_RETURN_20D_MIN
            and positive_ratio >= HOT_SECTOR_POSITIVE_RATIO_MIN
        )
    )


def _hot_sector_names(discovery: dict[str, Any]) -> set[str]:
    return {
        str(item.get("sector") or "").strip()
        for item in _candidate_sector_focus(discovery)
        if str(item.get("sector") or "").strip() and _is_hot_sector_focus(item)
    }


def _candidate_has_hot_sector_reason(item: dict[str, Any]) -> bool:
    reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
    return (
        "板块20日主线扩散较好" in reasons_text
        or "板块中期趋势延续性较好" in reasons_text
        or "先看板块主线" in reasons_text
    )


def _is_potential_watch(item: dict[str, Any]) -> bool:
    return str(item.get("selection_mode") or "").strip() == "potential_watch"


def filter_hot_sector_candidates(
    discovery: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    source_candidates = candidates if candidates is not None else discovery.get("candidates") or []
    candidate_items = list(source_candidates)
    hot_sectors = _hot_sector_names(discovery)
    if hot_sectors:
        return [
            item
            for item in candidate_items
            if str(item.get("sector") or "").strip() in hot_sectors or _is_potential_watch(item)
        ]
    if "sector_focus" in discovery:
        return [
            item
            for item in candidate_items
            if _candidate_has_hot_sector_reason(item) or _is_potential_watch(item)
        ]
    return [
        item
        for item in candidate_items
        if _candidate_has_hot_sector_reason(item) or _is_potential_watch(item)
    ]


def _paper_alert_items(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in alerts if _candidate_has_hot_sector_reason(item)]


def _candidate_sector_groups(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    groups = discovery.get("sector_groups") or []
    return [item for item in groups if str(item.get("sector") or "").strip()]


def _candidate_sector_focus(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    groups = discovery.get("sector_focus") or []
    return [item for item in groups if str(item.get("sector") or "").strip()]


def _append_candidate_diagnostics(lines: list[str], discovery: dict[str, Any]) -> None:
    diagnostics = discovery.get("candidate_diagnostics")
    if not isinstance(diagnostics, dict):
        return
    summary = str(diagnostics.get("summary") or "").strip()
    reasons = [str(item).strip() for item in diagnostics.get("reasons") or [] if str(item).strip()]
    if not summary and not reasons:
        return
    line = f"候选诊断：{summary}" if summary else "候选诊断："
    if reasons:
        line += f" 原因：{'；'.join(reasons[:2])}"
    lines.append(line)


def _strategy_priority(strategy_type: Any) -> int:
    mapping = {
        "long_term": 3,
        "swing": 2,
        "watch_breakout": 1,
        "short_term": 0,
    }
    return mapping.get(str(strategy_type or ""), 0)


def _candidate_position_penalty(item: dict[str, Any]) -> float:
    penalty = 0.0
    for flag in item.get("risk_flags") or []:
        text = str(flag)
        if "距离MA20偏远" in text:
            penalty += 4.0
        elif "今日涨幅较大" in text:
            penalty += 3.0
        elif "20日涨幅偏高" in text:
            penalty += 3.0
        elif "过热分数偏高" in text:
            penalty += 2.5
        elif "放量诱多风险" in text:
            penalty += 2.5
        else:
            penalty += 1.5
    return penalty


def _candidate_display_score(item: dict[str, Any]) -> float:
    reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
    score = float(item.get("score") or 0.0) - _candidate_position_penalty(item)
    if "低维主线：板块趋势和个股强度共振" in reasons_text:
        score += 8.0
    if "中期强者：相对强度或板块扩散足够强" in reasons_text:
        score += 5.0
    if "回调质量符合5月较稳因子" in reasons_text:
        score += 3.5
    if "板块中期趋势延续性较好" in reasons_text:
        score += 2.2
    if "板块回撤韧性还在" in reasons_text:
        score += 1.8
    if "板块20日主线扩散较好" in reasons_text:
        score += 2.4
    if "趋势+相对强度因子仍有支撑" in reasons_text:
        score += 1.0
    if "价格未明显远离MA20" in reasons_text:
        score += 2.0
    return score


def _style_gate_priority(item: dict[str, Any]) -> int:
    mapping = {
        "upgrade_allowed": 2,
        "observe_only": 1,
        "stand_down": 0,
    }
    status = str(item.get("style_gate_status") or "").strip()
    return mapping.get(status, 1)


def _candidate_order_key(item: dict[str, Any]) -> tuple[int, int, float]:
    return (
        _strategy_priority(item.get("selected_strategy_type")),
        _style_gate_priority(item),
        _candidate_display_score(item),
    )


def _ordered_candidate_items(
    candidates: list[dict[str, Any]],
    max_items: int,
) -> list[dict[str, Any]]:
    low_noise = [item for item in candidates if not item.get("risk_flags")]
    needs_pullback = [item for item in candidates if item.get("risk_flags")]
    return (
        sorted(
            low_noise,
            key=_candidate_order_key,
            reverse=True,
        )[:max_items]
        + sorted(
            needs_pullback,
            key=_candidate_order_key,
            reverse=True,
        )[: max(0, max_items - len(low_noise))]
    )


def _unique_texts(values: list[Any]) -> list[str]:
    texts: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        texts.append(text)
        seen.add(text)
    return texts


def _merged_candidate_item(items: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(items, key=_candidate_order_key, reverse=True)
    best = dict(ordered[0])
    rule_ids = _unique_texts(
        [
            rule_id
            for item in ordered
            for rule_id in (
                item.get("matched_rule_ids")
                if isinstance(item.get("matched_rule_ids"), list)
                else [item.get("selected_rule_id")]
            )
        ]
    )
    rule_names = _unique_texts(
        [
            rule_name
            for item in ordered
            for rule_name in (
                item.get("matched_rule_names")
                if isinstance(item.get("matched_rule_names"), list)
                else [
                    " ".join(
                        part
                        for part in (
                            str(item.get("selected_rule_id") or "").strip(),
                            str(item.get("selected_rule_name") or "").strip(),
                        )
                        if part
                    )
                ]
            )
        ]
    )
    reasons = _unique_texts(
        [reason for item in ordered for reason in (item.get("reasons") or [])]
    )
    risks = _unique_texts(
        [risk for item in ordered for risk in (item.get("risk_flags") or [])]
    )
    best["matched_rule_ids"] = rule_ids
    best["matched_rule_names"] = rule_names
    if reasons:
        best["reasons"] = reasons
    if risks:
        best["risk_flags"] = risks
    return best


def _merge_candidate_items_by_symbol(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    anonymous: list[dict[str, Any]] = []
    for item in candidates:
        symbol = str(item.get("symbol") or "").strip()
        if not symbol:
            anonymous.append(item)
            continue
        buckets.setdefault(symbol, []).append(item)
    merged = [_merged_candidate_item(items) for items in buckets.values()]
    return merged + anonymous


def _take_unseen_candidate_items(
    candidates: list[dict[str, Any]],
    seen_symbols: set[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in _merge_candidate_items_by_symbol(candidates):
        symbol = str(item.get("symbol") or "")
        if symbol and symbol in seen_symbols:
            continue
        selected.append(item)
        if symbol:
            seen_symbols.add(symbol)
    return selected


def _has_low_dimensional_reason(item: dict[str, Any]) -> bool:
    reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
    return "低维主线：板块趋势和个股强度共振" in reasons_text


def _has_long_horizon_strength_reason(item: dict[str, Any]) -> bool:
    reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
    return "中期强者：相对强度或板块扩散足够强" in reasons_text


def _has_long_horizon_extension_reason(item: dict[str, Any]) -> bool:
    reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
    return "中期扩展观察：趋势连续性和相对强度接近中期强者" in reasons_text


def _candidate_float(item: dict[str, Any], key: str) -> float | None:
    value = item.get(key)
    return float(value) if value is not None else None


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _passes_long_action_extension_quality(item: dict[str, Any]) -> bool:
    if not _has_long_horizon_extension_reason(item):
        return False
    reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
    volume = _candidate_float(item, "volume_confirmation_score")
    price_volume = _candidate_float(item, "price_volume_trend_score")
    return_20d = _candidate_float(item, "return_20d")
    distance_to_ma20 = _candidate_float(item, "distance_to_ma20")

    volume_confirmed = (volume is not None and volume >= 45.0) or (
        price_volume is not None and price_volume >= 55.0
    )
    position_ok = (
        return_20d is not None
        and distance_to_ma20 is not None
        and 0.02 <= return_20d <= 0.24
        and -0.05 <= distance_to_ma20 <= 0.10
    )
    sector_continuity_ok = (
        "板块中期趋势延续性较好" in reasons_text
        or "板块回撤韧性还在" in reasons_text
    )
    return volume_confirmed and position_ok and sector_continuity_ok


def _passes_long_action_market_gate(discovery: dict[str, Any]) -> bool:
    snapshot = discovery.get("market_participation_snapshot") or {}
    participation_score = float(snapshot.get("participation_score") or 50.0)
    liquidity_score = float(snapshot.get("liquidity_score") or 50.0)
    return (
        participation_score >= LONG_ACTION_PARTICIPATION_MIN
        and liquidity_score >= LONG_ACTION_LIQUIDITY_MIN
    )


def _market_beta_core_block_reason(discovery: dict[str, Any], item: dict[str, Any]) -> str | None:
    if _candidate_sector_style(item) != "market_beta":
        return None
    regime_snapshot = discovery.get("market_regime_snapshot") or {}
    participation_snapshot = discovery.get("market_participation_snapshot") or {}
    emotion_gate = discovery.get("emotion_gate") or {}
    regime = str(discovery.get("market_regime") or regime_snapshot.get("regime") or "")
    gate_state = str(regime_snapshot.get("emotion_gate") or emotion_gate.get("state") or "")
    breadth_score = _safe_float(regime_snapshot.get("breadth_score"), 50.0)
    participation_score = _safe_float(participation_snapshot.get("participation_score"), 50.0)
    liquidity_score = _safe_float(participation_snapshot.get("liquidity_score"), 50.0)
    weak_market = (
        regime == "panic"
        or gate_state == "risk_off"
        or breadth_score <= 42.0
        or (regime == "weak_trend" and breadth_score <= 45.0)
    )
    thin_participation = (
        participation_score < LONG_ACTION_PARTICIPATION_MIN
        or liquidity_score < LONG_ACTION_LIQUIDITY_MIN
    )
    if not weak_market and not thin_participation:
        return None
    return "市场弹性候选遇到弱市缩量，先降为观察；需要指数、市场宽度和成交额重新配合。"


def _market_stress_snapshot(discovery: dict[str, Any]) -> dict[str, Any]:
    snapshot = discovery.get("market_stress")
    return snapshot if isinstance(snapshot, dict) else {}


def _market_stress_core_limit(discovery: dict[str, Any], max_core_items: int) -> int:
    status = str(_market_stress_snapshot(discovery).get("stress_status") or "")
    if status == "risk_off":
        return 0
    if status == "caution":
        return min(max_core_items, 1)
    return max_core_items


def _market_stress_core_block_reason(
    discovery: dict[str, Any],
    *,
    selected_core_count: int,
    max_core_items: int,
) -> str | None:
    snapshot = _market_stress_snapshot(discovery)
    status = str(snapshot.get("stress_status") or "")
    action = str(snapshot.get("risk_action_label") or "").strip()
    reasons = [str(reason) for reason in snapshot.get("stress_reasons") or [] if reason]
    reason_suffix = f"；{reasons[0]}" if reasons else ""

    if status == "risk_off":
        action_text = action or "停止扩散，只做观察和风控"
        return f"大盘压力大：{action_text}{reason_suffix}。"
    if status == "caution" and selected_core_count >= max_core_items:
        action_text = action or "降低频率，等盘中确认"
        return f"大盘谨慎：只保留最强一只，其余{action_text}{reason_suffix}。"
    return None


def _candidate_sector_style(item: dict[str, Any]) -> str:
    explicit_style = str(item.get("sector_style") or "").strip()
    if explicit_style:
        return explicit_style
    sector = str(item.get("sector") or "")
    for style, keywords in LONG_ACTION_STYLE_KEYWORDS.items():
        if any(keyword in sector for keyword in keywords):
            return style
    return "unknown"


def _is_startup_preheat_candidate_item(item: dict[str, Any]) -> bool:
    if str(item.get("selection_mode") or "").strip() != "potential_watch":
        return False
    reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
    return "启动前夜：T-1量价修复" in reasons_text


def _candidate_style_gate_policy(
    discovery: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any] | None:
    if str(item.get("selection_mode") or "").strip() != "potential_watch":
        return None
    policy_key = (
        "startup_preheat_policy"
        if _is_startup_preheat_candidate_item(item)
        else "style_gate_policy"
    )
    policy = discovery.get(policy_key)
    return policy if isinstance(policy, dict) else None


def _candidate_with_style_gate(
    discovery: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    policy = _candidate_style_gate_policy(discovery, item)
    if not policy:
        return item
    style = _candidate_sector_style(item)
    row = next(
        (
            row_item
            for row_item in policy.get("rows") or []
            if str(row_item.get("style") or "") == style
        ),
        None,
    )
    if not isinstance(row, dict):
        return item
    return {
        **item,
        "style_gate_scope": policy.get("scope"),
        "style_gate_horizon": policy.get("horizon"),
        "style_gate_style": style,
        "style_gate_style_label": row.get("label"),
        "style_gate_status": row.get("status"),
        "style_gate_label": row.get("status_label"),
        "style_gate_reason": row.get("summary"),
    }


def _passes_long_action_style_gate(item: dict[str, Any]) -> bool:
    return _candidate_sector_style(item) in LONG_ACTION_TREND_STYLES


def _append_unique_action_items(
    selected: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    max_items: int,
) -> None:
    selected_symbols = {str(item.get("symbol") or "") for item in selected}
    for item in _ordered_candidate_items(candidates, max_items):
        symbol = str(item.get("symbol") or "")
        if not symbol or symbol in selected_symbols:
            continue
        selected.append(item)
        selected_symbols.add(symbol)
        if len(selected) >= max_items:
            return


def select_action_candidates(
    discovery: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
    *,
    max_items: int = ACTION_CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    source_candidates = (
        candidates if candidates is not None else _candidate_screening_items(discovery)
    )
    normal_candidates = [
        item
        for item in source_candidates
        if not is_star_market_symbol(item.get("symbol"))
        and str(item.get("selection_mode") or "").strip()
        not in {"exploration", "potential_watch"}
    ]
    low_noise = [item for item in normal_candidates if not item.get("risk_flags")]
    selected: list[dict[str, Any]] = []
    _append_unique_action_items(
        selected,
        [item for item in low_noise if _has_low_dimensional_reason(item)],
        max_items=max_items,
    )
    _append_unique_action_items(
        selected,
        [item for item in low_noise if _has_long_horizon_strength_reason(item)],
        max_items=max_items,
    )
    _append_unique_action_items(
        selected,
        [
            item
            for item in low_noise
            if str(item.get("selected_strategy_type") or "") in {"long_term", "swing"}
        ],
        max_items=max_items,
    )
    _append_unique_action_items(selected, low_noise, max_items=max_items)
    return selected[:max_items]


def select_long_action_candidates(
    discovery: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
    *,
    max_items: int = ACTION_CANDIDATE_LIMIT,
) -> list[dict[str, Any]]:
    if not _passes_long_action_market_gate(discovery):
        return []
    source_candidates = (
        candidates if candidates is not None else _candidate_screening_items(discovery)
    )
    return select_action_candidates(
        discovery,
        [
            item
            for item in source_candidates
            if _passes_long_action_style_gate(item)
            and (
                _has_long_horizon_strength_reason(item)
                or _passes_long_action_extension_quality(item)
            )
        ],
        max_items=max_items,
    )


def _candidate_symbols(items: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("symbol") or "") for item in items if item.get("symbol")}


def _is_heavy_risk_candidate(item: dict[str, Any]) -> bool:
    flags = [str(flag) for flag in item.get("risk_flags") or []]
    if len(flags) >= 2:
        return True
    heavy_keywords = (
        "放量诱多风险",
        "放量回落",
        "冲高翻绿",
        "近涨停未封",
        "板块20日涨幅/扩散已偏拥挤",
    )
    return any(any(keyword in flag for keyword in heavy_keywords) for flag in flags)


def _tiered_candidate(
    item: dict[str, Any],
    *,
    tier: str,
    label: str,
    reason: str,
) -> dict[str, Any]:
    return {
        **item,
        "candidate_tier": tier,
        "candidate_tier_label": label,
        "tier_reason": reason,
    }


def _defensive_sector_watch_enabled(discovery: dict[str, Any]) -> bool:
    return str(_market_stress_snapshot(discovery).get("stress_status") or "") == "risk_off"


def _sector_watch_policy_status_by_style(discovery: dict[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for policy_key in ("style_gate_policy", "startup_preheat_policy"):
        policy = discovery.get(policy_key)
        if not isinstance(policy, dict):
            continue
        for row in policy.get("rows") or []:
            if not isinstance(row, dict):
                continue
            style = str(row.get("style") or "").strip()
            status = str(row.get("status") or "").strip()
            if style and status:
                statuses[style] = status
    return statuses


def _sector_watch_gate_rank(
    discovery: dict[str, Any],
    item: dict[str, Any],
) -> int:
    style = _candidate_sector_style(item)
    status = str(item.get("style_gate_status") or "").strip()
    policy_statuses = _sector_watch_policy_status_by_style(discovery)
    if not status:
        status = policy_statuses.get(style, "")
    if status == "upgrade_allowed":
        return 2
    if status == "observe_only":
        return 1
    if status == "stand_down":
        return 0
    if policy_statuses:
        return 0
    return 1 if style in LONG_ACTION_TREND_STYLES else 0


def _sector_watch_style_label(item: dict[str, Any]) -> str:
    label = str(item.get("style_gate_style_label") or "").strip()
    if label:
        return label
    sector = str(item.get("sector") or "").strip()
    if sector:
        return sector
    return str(item.get("sector_style") or "板块").strip() or "板块"


def _sector_watch_reason(item: dict[str, Any]) -> str:
    style_label = _sector_watch_style_label(item)
    return _append_style_gate_reason(
        item,
        _append_horizon_reason(
            item,
            f"防守阶段板块观察：{style_label}方向保留代表票，交给人盘中判断，非买点。",
        ),
    )


def _select_sector_watch_candidates(
    discovery: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    excluded_symbols: set[str],
    max_per_sector: int = 2,
    max_per_style: int = 2,
    max_items: int = 8,
) -> list[dict[str, Any]]:
    if not _defensive_sector_watch_enabled(discovery):
        return []
    selected: list[dict[str, Any]] = []
    selected_symbols: set[str] = set()
    selected_by_sector: dict[str, int] = {}
    selected_by_style: dict[str, int] = {}

    ordered_items = sorted(
        _ordered_candidate_items(candidates, max_items=len(candidates)),
        key=lambda item: (
            _sector_watch_gate_rank(discovery, item),
            _candidate_order_key(item),
        ),
        reverse=True,
    )
    for sector_round_limit in range(1, max_per_sector + 1):
        for item in ordered_items:
            symbol = str(item.get("symbol") or "")
            if (
                not symbol
                or symbol in excluded_symbols
                or symbol in selected_symbols
                or is_star_market_symbol(symbol)
            ):
                continue
            if _is_heavy_risk_candidate(item):
                continue
            if _sector_watch_gate_rank(discovery, item) <= 0:
                continue
            style = _candidate_sector_style(item)
            sector = str(item.get("sector") or style or "未分类").strip()
            if selected_by_sector.get(sector, 0) >= sector_round_limit:
                continue
            if selected_by_style.get(style, 0) >= max_per_style:
                continue
            selected.append(
                _tiered_candidate(
                    item,
                    tier="sector_watch",
                    label="板块观察",
                    reason=_sector_watch_reason(item),
                )
            )
            selected_symbols.add(symbol)
            selected_by_sector[sector] = selected_by_sector.get(sector, 0) + 1
            selected_by_style[style] = selected_by_style.get(style, 0) + 1
            if len(selected) >= max_items:
                return selected
    return selected


def _append_horizon_reason(item: dict[str, Any], reason: str) -> str:
    horizon_reason = str(item.get("horizon_reason") or "").strip()
    if not horizon_reason:
        horizon_days = item.get("suggested_horizon_days")
        if horizon_days is not None:
            horizon_reason = f"建议{int(horizon_days)}日观察"
    if not horizon_reason or horizon_reason in reason:
        return reason
    return f"{reason} {horizon_reason}。"


def _append_style_gate_reason(item: dict[str, Any], reason: str) -> str:
    gate_reason = str(item.get("style_gate_reason") or "").strip()
    if not gate_reason or gate_reason in reason:
        return reason
    return f"{reason} 门控：{gate_reason}"


def _watch_wait_reason(item: dict[str, Any]) -> str:
    if str(item.get("selection_mode") or "") == "potential_watch":
        reasons_text = " ".join(str(reason) for reason in item.get("reasons") or [])
        if "启动前夜：T-1量价修复" in reasons_text:
            signal_label = str(item.get("startup_signal_label") or "").strip()
            signal_score = item.get("startup_signal_score")
            signal_prefix = ""
            if signal_label and signal_score is not None:
                signal_prefix = f"{signal_label}{float(signal_score):.1f}分："
            elif signal_label:
                signal_prefix = f"{signal_label}："
            return _append_style_gate_reason(
                item,
                _append_horizon_reason(
                    item,
                    f"{signal_prefix}启动前夜：T-1量价已经修复，不代表买点，先盯次日承接。",
                ),
            )
        return _append_style_gate_reason(
            item,
            _append_horizon_reason(
                item,
                "个股有启动迹象，但板块或买点还没确认，先放观察等待。",
            ),
        )
    if item.get("risk_flags"):
        return _append_horizon_reason(
            item,
            "趋势仍可跟踪，但当前位置不舒服，等回踩和承接确认。",
        )
    return _append_horizon_reason(
        item,
        "条件接近行动池，但还需要板块延续或盘中承接确认。",
    )


def _core_block_reason(
    candidates: list[dict[str, Any]],
    core_action: list[dict[str, Any]],
    blocked_core_reasons: list[str] | None = None,
) -> str | None:
    if core_action:
        return None
    if blocked_core_reasons:
        if any("大盘压力大" in reason for reason in blocked_core_reasons):
            return "没有核心行动：大盘压力大，停止扩散，只做观察和风控。"
        if any("市场弹性" in reason and "弱市缩量" in reason for reason in blocked_core_reasons):
            return "没有核心行动：市场弹性候选遇到弱市缩量，先降为观察。"
        return blocked_core_reasons[0]
    if not candidates:
        return "没有核心行动：当前没有候选进入分层池。"
    potential_count = sum(1 for item in candidates if _is_potential_watch(item))
    heavy_risk_count = sum(1 for item in candidates if _is_heavy_risk_candidate(item))
    actionable_modes = [
        item
        for item in candidates
        if str(item.get("selection_mode") or "").strip()
        not in {"exploration", "potential_watch"}
    ]
    if potential_count and heavy_risk_count:
        return "没有核心行动：候选仍以潜力观察/买点未确认为主，正式票又带较重风险。"
    if potential_count == len(candidates):
        return "没有核心行动：当前候选都是潜力观察，板块或买点还没确认。"
    if actionable_modes and all(item.get("risk_flags") for item in actionable_modes):
        return "没有核心行动：正式候选都有风险或位置问题，先等回踩和承接。"
    return "没有核心行动：条件接近但还没同时满足板块、个股和风险约束。"


def build_candidate_tiers(
    discovery: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
    *,
    max_core_items: int = ACTION_CANDIDATE_LIMIT,
) -> dict[str, Any]:
    source_candidates = list(
        candidates if candidates is not None else discovery.get("candidates") or []
    )
    source_candidates = _merge_candidate_items_by_symbol([
        _candidate_with_style_gate(discovery, item) for item in source_candidates
    ])
    long_action_candidates = discovery.get("long_action_candidates")
    action_candidates = discovery.get("action_candidates")
    core_source = (
        long_action_candidates
        if isinstance(long_action_candidates, list) and long_action_candidates
        else action_candidates
        if isinstance(action_candidates, list) and action_candidates
        else select_long_action_candidates(discovery, source_candidates, max_items=max_core_items)
        or select_action_candidates(discovery, source_candidates, max_items=max_core_items)
    )
    core_source_items = _merge_candidate_items_by_symbol(list(core_source))
    market_core_limit = _market_stress_core_limit(discovery, max_core_items)
    blocked_core_items: list[dict[str, Any]] = []
    blocked_core_reasons: list[str] = []
    filtered_core_source: list[dict[str, Any]] = []
    for item in core_source_items:
        block_reason = _market_stress_core_block_reason(
            discovery,
            selected_core_count=len(filtered_core_source),
            max_core_items=market_core_limit,
        )
        if block_reason:
            blocked_core_items.append(
                _tiered_candidate(
                    item,
                    tier="watch_wait",
                    label="观察等待",
                    reason=_append_horizon_reason(item, block_reason),
                )
            )
            blocked_core_reasons.append(block_reason)
            continue
        block_reason = _market_beta_core_block_reason(discovery, item)
        if block_reason:
            blocked_core_items.append(
                _tiered_candidate(
                    item,
                    tier="watch_wait",
                    label="观察等待",
                    reason=_append_horizon_reason(item, block_reason),
                )
            )
            blocked_core_reasons.append(block_reason)
            continue
        filtered_core_source.append(item)
    core_action = [
        _tiered_candidate(
            item,
            tier="core_action",
            label="核心行动",
            reason=_append_horizon_reason(
                item,
                "板块和个股趋势同时在线，作为核心行动候选；盘中仍看承接。",
            ),
        )
        for item in filtered_core_source[:market_core_limit]
    ]
    core_symbols = _candidate_symbols(core_action)
    blocked_core_symbols = _candidate_symbols(blocked_core_items)
    sector_watch = _select_sector_watch_candidates(
        discovery,
        source_candidates,
        excluded_symbols=core_symbols | blocked_core_symbols,
    )
    sector_watch_symbols = _candidate_symbols(sector_watch)
    watch_wait: list[dict[str, Any]] = list(blocked_core_items)
    risk_reject: list[dict[str, Any]] = []
    for item in source_candidates:
        symbol = str(item.get("symbol") or "")
        if (
            not symbol
            or symbol in core_symbols
            or symbol in blocked_core_symbols
            or symbol in sector_watch_symbols
        ):
            continue
        if _is_heavy_risk_candidate(item):
            risks = "；".join(str(flag) for flag in (item.get("risk_flags") or [])[:2])
            risk_reject.append(
                _tiered_candidate(
                    item,
                    tier="risk_reject",
                    label="淘汰/风险",
                    reason=f"风险信号偏重：{risks or '条件不足'}，暂不纳入行动池。",
                )
            )
            continue
        watch_wait.append(
            _tiered_candidate(
                item,
                tier="watch_wait",
                label="观察等待",
                reason=_watch_wait_reason(item),
            )
        )
    return {
        "core_action": core_action,
        "sector_watch": sector_watch,
        "watch_wait": watch_wait,
        "risk_reject": risk_reject,
        "summary": {
            "core_action_count": len(core_action),
            "sector_watch_count": len(sector_watch),
            "watch_wait_count": len(watch_wait),
            "risk_reject_count": len(risk_reject),
            "core_block_reason": _core_block_reason(
                source_candidates,
                core_action,
                blocked_core_reasons=blocked_core_reasons,
            ),
        },
    }


def _candidate_reason_preview(reasons: Any, *, max_items: int = 4) -> str:
    if not isinstance(reasons, list):
        return _compact_reason_text(reasons)

    priority_keywords = (
        "低维主线：板块趋势和个股强度共振",
        "中期强者：相对强度或板块扩散足够强",
        "先看板块主线",
        "板块中期趋势延续性较好",
        "板块回撤韧性还在",
        "板块主线地位靠前",
        "板块20日主线扩散较好",
        "启动前夜",
        "回调质量符合5月较稳因子",
        "趋势+相对强度因子仍有支撑",
        "潜力观察",
        "中期口径",
        "弱环境",
        "资金参与偏弱",
        "等回落",
    )
    route_keywords = ("路线判断", "路线 ")
    selected: list[str] = []

    for keyword_group in (priority_keywords, route_keywords):
        for reason in reasons:
            text = str(reason)
            if text in selected:
                continue
            if any(keyword in text for keyword in keyword_group):
                selected.append(text)
            if len(selected) >= max_items:
                return "；".join(selected)

    for reason in reasons:
        text = str(reason)
        if text and text not in selected:
            selected.append(text)
        if len(selected) >= max_items:
            break
    return "；".join(selected)


def _format_candidate_group(
    lines: list[str],
    *,
    candidates: list[dict[str, Any]],
    max_items: int,
    title: str,
) -> None:
    candidates = _merge_candidate_items_by_symbol(candidates)
    if not candidates:
        lines.append(f"{title}：暂无候选。")
        return

    lines.append(title)
    low_noise = [item for item in candidates if not item.get("risk_flags")]
    needs_pullback = [item for item in candidates if item.get("risk_flags")]
    ordered = _ordered_candidate_items(candidates, max_items)
    if low_noise:
        names = "、".join(
            f"{item.get('symbol')} {item.get('name') or ''}".strip() for item in low_noise[:5]
        )
        lines.append(f"优先观察：{names}")
    if needs_pullback:
        names = "、".join(
            f"{item.get('symbol')} {item.get('name') or ''}".strip() for item in needs_pullback[:5]
        )
        lines.append(f"高分但等回落：{names}")

    current_group = ""
    for index, item in enumerate(ordered, start=1):
        group = "低噪音观察" if not item.get("risk_flags") else "有追高/位置风险"
        if group != current_group:
            lines.append(group)
            current_group = group
        judgment = {
            "formal_strategy": "正式策略命中",
            "potential_watch": "潜力观察",
        }.get(str(item.get("selection_mode") or ""), "观察候选")
        strategy_label = {
            "long_term": "中期趋势",
            "swing": "波段",
            "short_term": "短线观察",
            "watch_breakout": "观察",
        }.get(str(item.get("selected_strategy_type") or ""), "")
        strategy_prefix = f"{strategy_label} " if strategy_label else ""
        lines.append(
            f"{index}. {item.get('symbol')} {item.get('name') or ''} "
            f"{item.get('sector') or ''} "
            f"{strategy_prefix}{judgment} "
            f"第{item.get('score'):.1f}分"
        )
        lines.append(
            (
                f"规则：{item.get('selected_rule_id') or '-'} "
                f"{item.get('selected_rule_name') or ''}"
            ).strip()
        )
        matched_rule_ids = [
            rule_id
            for rule_id in item.get("matched_rule_ids") or []
            if rule_id and rule_id != "-"
        ]
        if len(matched_rule_ids) > 1:
            lines.append(f"共振规则：{'、'.join(matched_rule_ids)}")
        reasons = item.get("reasons") or []
        if reasons:
            lines.append(f"理由：{_candidate_reason_preview(reasons)}")
        tier_reason = str(item.get("tier_reason") or "")
        if tier_reason:
            lines.append(f"分层：{tier_reason}")
        style_gate_label = str(item.get("style_gate_label") or "").strip()
        style_gate_reason = str(item.get("style_gate_reason") or "").strip()
        if style_gate_label or style_gate_reason:
            gate_parts = [part for part in (style_gate_label, style_gate_reason) if part]
            lines.append(f"门控：{' / '.join(gate_parts)}")
        risks = item.get("risk_flags") or []
        if risks:
            lines.append(f"风险：{'；'.join(str(risk) for risk in risks[:2])}")
    if len(candidates) > max_items:
        lines.append(f"其余 {len(candidates) - max_items} 只已省略。")


def format_paper_alert_text(
    alerts: list[dict[str, Any]],
    *,
    title: str = "股票纸面交易预警",
) -> str:
    lines = [title]
    for alert in _paper_alert_items(alerts):
        judgment = _alert_judgment_label(alert.get("alert_type"))
        header_parts = [
            str(alert.get("symbol") or "-"),
            str(alert.get("name") or ""),
            str(alert.get("rule_id") or ""),
            str(alert.get("strategy_type") or ""),
        ]
        header = " ".join(part for part in header_parts if part).strip()
        if not header:
            header = str(alert.get("symbol") or "-")
        alert_type = str(alert.get("alert_type") or "")
        meta = [
            f"判断={judgment}",
            f"[{alert.get('severity')}]",
            f"价格={alert.get('price')}",
            f"止损={alert.get('current_stop')}",
            f"收益={alert.get('pnl_pct')}",
            f"时间={alert.get('alert_time')}",
        ]
        if alert.get("candidate_rank") is not None:
            meta.append(f"第{alert.get('candidate_rank')}名")
        if alert.get("candidate_score") is not None:
            meta.append(f"评分={float(alert.get('candidate_score')):.1f}")
        lines.append(f"{header} {alert_type} {' '.join(meta)}".strip())
        message = str(alert.get("message") or "")
        if message:
            lines.append(message)
        snapshot = _snapshot_text(alert.get("intraday_snapshot"))
        if snapshot:
            lines.append(f"盘中快照：{snapshot}")
        reasons = _compact_reason_text(alert.get("reasons"))
        if reasons:
            lines.append(f"推荐理由：{reasons}")
        support_flags = _compact_reason_text(alert.get("support_flags"))
        if support_flags:
            lines.append(f"支撑：{support_flags}")
        risk_flags = _compact_reason_text(alert.get("risk_flags"))
        if risk_flags:
            lines.append(f"风险：{risk_flags}")
    return "\n".join(lines)


def format_candidate_screening_text(
    discovery: dict[str, Any],
    *,
    title: str = "盘后股票候选",
    max_items: int = 8,
) -> str:
    screening_candidates = _candidate_screening_items(discovery)
    action_candidates = discovery.get("action_candidates")
    long_action_candidates = discovery.get("long_action_candidates")
    candidate_tiers = discovery.get("candidate_tiers")
    core_action_candidates = (
        candidate_tiers.get("core_action")
        if isinstance(candidate_tiers, dict)
        else None
    )
    uses_candidate_tiers = isinstance(candidate_tiers, dict) and any(
        key in candidate_tiers
        for key in ("core_action", "sector_watch", "watch_wait", "risk_reject")
    )
    uses_core_action_candidates = (
        isinstance(core_action_candidates, list) and bool(core_action_candidates)
    )
    uses_action_candidates = isinstance(action_candidates, list) and bool(action_candidates)
    uses_long_action_candidates = (
        isinstance(long_action_candidates, list) and bool(long_action_candidates)
    )
    if uses_candidate_tiers:
        tiers = candidate_tiers if isinstance(candidate_tiers, dict) else {}
        seen_tier_symbols: set[str] = set()
        core_candidates = _take_unseen_candidate_items(
            list(tiers.get("core_action") or []),
            seen_tier_symbols,
        )
        sector_watch_candidates = _take_unseen_candidate_items(
            list(tiers.get("sector_watch") or []),
            seen_tier_symbols,
        )
        watch_candidates = _take_unseen_candidate_items(
            list(tiers.get("watch_wait") or []),
            seen_tier_symbols,
        )
        risk_candidates = _take_unseen_candidate_items(
            list(tiers.get("risk_reject") or []),
            seen_tier_symbols,
        )
        displayed_candidates = (
            core_candidates + sector_watch_candidates + watch_candidates + risk_candidates
        )
        formal_count = sum(
            1
            for item in displayed_candidates
            if item.get("selection_mode") == "formal_strategy"
        )
        observation_count = len(displayed_candidates) - formal_count
        lines = [title]
        feature_parts = []
        requested_feature_date = discovery.get("requested_feature_date")
        if requested_feature_date:
            feature_parts.append(f"请求日 {requested_feature_date}")
        feature_parts.append(f"特征日 {discovery.get('feature_date') or '-'}")
        feature_coverage_ratio = discovery.get("feature_coverage_ratio")
        if feature_coverage_ratio is not None:
            feature_parts.append(f"覆盖 {float(feature_coverage_ratio):.1%}")
        retired_count = discovery.get("retired") or 0
        lines.append(
            f"{' | '.join(feature_parts)} | "
            f"宇宙 {discovery.get('universe_size') or 0} "
            f"| 正式 {formal_count} | 观察 {observation_count} | 淘汰 {retired_count}"
        )
        warning = discovery.get("universe_warning")
        if warning:
            lines.append(f"提示：{warning}")
        _append_candidate_diagnostics(lines, discovery)
        lines.append(
            f"钉钉分层推送：核心行动 {len(core_candidates)} 只，"
            f"防守板块观察 {len(sector_watch_candidates)} 只，"
            f"学习观察 {len(watch_candidates)} 只，"
            f"暂不升级/风险 {len(risk_candidates)} 只。"
            "核心行动才是交易重点，学习观察不代表买点。"
        )
        core_block_reason = (tiers.get("summary") or {}).get("core_block_reason")
        if core_block_reason:
            lines.append(str(core_block_reason))
        star_pool_count = len(discovery.get("star_candidates") or [])
        if star_pool_count:
            lines.append(f"科创池 {star_pool_count} 只单独看，波动更大，只做学习观察。")
        _format_candidate_group(
            lines,
            candidates=core_candidates,
            max_items=ACTION_CANDIDATE_LIMIT,
            title=f"核心行动（交易重点，最多{ACTION_CANDIDATE_LIMIT}只）",
        )
        _format_candidate_group(
            lines,
            candidates=sector_watch_candidates,
            max_items=max_items,
            title="防守板块观察（交给人判断，非买点）",
        )
        _format_candidate_group(
            lines,
            candidates=watch_candidates,
            max_items=max_items,
            title="学习观察（非买点，盘中验证）",
        )
        _format_candidate_group(
            lines,
            candidates=risk_candidates,
            max_items=5,
            title="暂不升级/风险理由",
        )
        lines.append("口径：先看板块和月级别趋势，再看个股位置；短线信号只做辅助，不直接追。")
        return "\n".join(lines)

    candidates = (
        _merge_candidate_items_by_symbol(
            filter_hot_sector_candidates(discovery, core_action_candidates)
        )
        if uses_core_action_candidates
        else (
            _merge_candidate_items_by_symbol(
                filter_hot_sector_candidates(discovery, long_action_candidates)
            )
            if uses_long_action_candidates
            else (
                _merge_candidate_items_by_symbol(
                    filter_hot_sector_candidates(discovery, action_candidates)
                )
                if uses_action_candidates
                else screening_candidates
            )
        )
    )
    formal_count = sum(1 for item in candidates if item.get("selection_mode") == "formal_strategy")
    observation_count = len(candidates) - formal_count
    lines = [title]
    feature_parts = []
    requested_feature_date = discovery.get("requested_feature_date")
    if requested_feature_date:
        feature_parts.append(f"请求日 {requested_feature_date}")
    feature_parts.append(f"特征日 {discovery.get('feature_date') or '-'}")
    feature_coverage_ratio = discovery.get("feature_coverage_ratio")
    if feature_coverage_ratio is not None:
        feature_parts.append(f"覆盖 {float(feature_coverage_ratio):.1%}")
    lines.append(
        f"{' | '.join(feature_parts)} | "
        f"宇宙 {discovery.get('universe_size') or 0} "
        f"| 正式 {formal_count} | 观察 {observation_count} | 淘汰 {discovery.get('retired') or 0}"
    )
    warning = discovery.get("universe_warning")
    if warning:
        lines.append(f"提示：{warning}")
    _append_candidate_diagnostics(lines, discovery)
    if uses_core_action_candidates:
        tiers = candidate_tiers if isinstance(candidate_tiers, dict) else {}
        watch_count = len(tiers.get("watch_wait") or [])
        risk_count = len(tiers.get("risk_reject") or [])
        lines.append(
            f"钉钉只展示核心行动候选 {len(candidates)} 只；"
            f"观察等待 {watch_count} 只、淘汰/风险 {risk_count} 只在 Web。"
        )
        star_pool_count = len(discovery.get("star_candidates") or [])
        if star_pool_count:
            lines.append(f"科创池 {star_pool_count} 只在 Web，和普通行动票分开看。")
    elif uses_long_action_candidates:
        web_pool_count = len(discovery.get("candidates") or screening_candidates)
        action_pool_count = len(action_candidates or [])
        lines.append(
            f"钉钉优先展示中期行动候选 {len(candidates)} 只；"
            f"普通行动候选 {action_pool_count} 只在 Web；观察池 {web_pool_count} 只在 Web。"
        )
        star_pool_count = len(discovery.get("star_candidates") or [])
        if star_pool_count:
            lines.append(f"科创池 {star_pool_count} 只在 Web，和普通行动票分开看。")
    elif uses_action_candidates:
        web_pool_count = len(discovery.get("candidates") or screening_candidates)
        lines.append(
            f"钉钉只展示行动候选 {len(candidates)} 只；观察池 {web_pool_count} 只在 Web。"
        )
        star_pool_count = len(discovery.get("star_candidates") or [])
        if star_pool_count:
            lines.append(f"科创池 {star_pool_count} 只在 Web，和普通行动票分开看。")
    if candidates and all(item.get("risk_flags") for item in candidates):
        lines.append("执行提醒：这批候选都有位置/追高风险，只做观察清单，等回落和承接确认。")

    normal_candidates = [
        item for item in candidates if not is_star_market_symbol(item.get("symbol"))
    ]
    star_candidates = [item for item in candidates if is_star_market_symbol(item.get("symbol"))]
    main_candidates = [
        item
        for item in normal_candidates
        if uses_core_action_candidates
        or uses_long_action_candidates
        or str(item.get("selected_strategy_type") or "") in {"long_term", "swing"}
    ]
    short_watch_candidates = [
        item
        for item in normal_candidates
        if not uses_long_action_candidates
        and str(item.get("selected_strategy_type") or "") not in {"long_term", "swing"}
    ]
    _format_candidate_group(
        lines,
        candidates=main_candidates,
        max_items=(
            ACTION_CANDIDATE_LIMIT
            if uses_core_action_candidates or uses_action_candidates
            else max_items
        ),
        title=(
            f"核心行动候选（最多{ACTION_CANDIDATE_LIMIT}只）"
            if uses_core_action_candidates
            else (
                f"中期行动候选（最多{ACTION_CANDIDATE_LIMIT}只）"
                if uses_long_action_candidates
                else (
                    f"行动候选（普通版最多{ACTION_CANDIDATE_LIMIT}只）"
                    if uses_action_candidates
                    else f"长期/波段主池（普通版最多{max_items}只）"
                )
            )
        ),
    )
    if short_watch_candidates and not uses_action_candidates:
        _format_candidate_group(
            lines,
            candidates=short_watch_candidates,
            max_items=5,
            title="短线观察池（只做辅助确认）",
        )
    if star_candidates and not uses_action_candidates:
        _format_candidate_group(
            lines,
            candidates=star_candidates,
            max_items=10,
            title="科创板高弹性池（最多10只）",
        )
    lines.append("口径：先看板块和月级别趋势，再看个股位置；短线信号只做辅助，不直接追。")
    return "\n".join(lines)


def dispatch_text(content: str) -> list[NotificationResult]:
    if not content:
        return []
    return _send_text(content)


def dispatch_paper_alerts(alerts: list[dict[str, Any]]) -> list[NotificationResult]:
    clean_alerts = _paper_alert_items(alerts)
    if not clean_alerts:
        return []
    return _send_text(format_paper_alert_text(clean_alerts))


def dispatch_candidate_screening(discovery: dict[str, Any]) -> list[NotificationResult]:
    if not discovery:
        return []
    if not _candidate_screening_items(discovery):
        return []
    return _send_text(format_candidate_screening_text(discovery, max_items=15))


def dispatch_monthly_trade_summary(content: str) -> list[NotificationResult]:
    return []
