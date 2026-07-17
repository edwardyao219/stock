from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from services.shared.time import now_local

AFTER_CLOSE_STATUS_TTL_SECONDS = 8 * 24 * 60 * 60


def _after_close_status_key(trade_date: str) -> str:
    return f"stock:after-close-status:{trade_date}"


def _step_dicts(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in result.get("steps") or [] if isinstance(item, dict)]


def _extract_first_int(pattern: str, values: list[str]) -> int:
    for value in values:
        match = re.search(pattern, value)
        if match:
            return int(match.group(1))
    return 0


def _extract_dingtalk_statuses(values: list[str]) -> list[str]:
    statuses: list[str] = []
    for value in values:
        if "钉钉提醒：" not in value:
            continue
        raw_statuses = value.split("钉钉提醒：", 1)[1]
        statuses.extend(
            status.strip()
            for status in re.split(r"[；;]", raw_statuses)
            if status.strip()
        )
    return statuses


def _extract_market_summary(values: list[str]) -> str | None:
    for value in values:
        if value.startswith("市场环境 "):
            return "市场 " + value.removeprefix("市场环境 ").strip()
        if value.startswith("市场 "):
            return value.strip()
    return None


def _step_status(steps: list[dict[str, Any]], name: str) -> str:
    step = next((item for item in steps if item.get("name") == name), None)
    return str(step.get("status") or "not_run") if step else "not_run"


def _dingtalk_status(statuses: list[str]) -> str:
    if not statuses:
        return "not_sent"
    if all(item.endswith(":ok") for item in statuses):
        return "ok"
    if any(item.endswith(":failed") for item in statuses):
        return "failed"
    return "warning"


def build_after_close_status(
    result: dict[str, Any],
    *,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    steps = _step_dicts(result)
    step_statuses = [str(step.get("status") or "") for step in steps]
    result_status = str(result.get("status") or "")
    if result_status in {"scheduled", "running", "skipped", "failed"}:
        status = result_status
    elif any(item == "failed" for item in step_statuses):
        status = "failed"
    elif any(item in {"warning", "skipped"} for item in step_statuses):
        status = "warning"
    else:
        status = "ok"

    step_texts = [
        str(value)
        for step in steps
        for value in [step.get("detail"), step.get("summary"), *(step.get("details") or [])]
        if value
    ]
    discover_step = next(
        (step for step in steps if step.get("name") == "discover_next_session_candidates"),
        None,
    )
    message = (
        str(discover_step.get("summary") or discover_step.get("detail"))
        if discover_step
        else str(result.get("message") or "收盘推送状态已记录。")
    )

    dingtalk_statuses = _extract_dingtalk_statuses(step_texts)
    return {
        "trade_date": str(result.get("trade_date") or ""),
        "next_trade_date": result.get("next_trade_date"),
        "status": status,
        "message": message,
        "updated_at": (updated_at or now_local()).isoformat(),
        "candidate_count": _extract_first_int(r"写入\s+(\d+)\s+只股票", step_texts),
        "plan_count": _extract_first_int(r"生成\s+(\d+)\s+条交易计划", step_texts),
        "dingtalk_statuses": dingtalk_statuses,
        "candidate_web_status": _step_status(steps, "discover_next_session_candidates"),
        "review_status": _step_status(steps, "generate_daily_review"),
        "dingtalk_status": _dingtalk_status(dingtalk_statuses),
        "market_summary": _extract_market_summary(step_texts),
        "tushare_evidence_health": result.get("tushare_evidence_health") or {},
        "scheduler_health": result.get("scheduler_health") or {},
        "source": "cache",
    }


def _write_after_close_status_payload(trade_date: str, payload: dict[str, Any]) -> None:
    try:
        from services.jobs.celery_app import celery_app

        celery_app.backend.client.set(
            _after_close_status_key(trade_date),
            json.dumps(payload, ensure_ascii=False),
            ex=AFTER_CLOSE_STATUS_TTL_SECONDS,
        )
    except Exception:
        return


def write_after_close_status(result: dict[str, Any]) -> None:
    trade_date = str(result.get("trade_date") or "").strip()
    if not trade_date:
        return
    _write_after_close_status_payload(trade_date, build_after_close_status(result))


def merge_after_close_status(trade_date: str, updates: dict[str, Any]) -> None:
    current = read_after_close_status(trade_date)
    if current is None:
        return
    _write_after_close_status_payload(trade_date, {**current, **updates})


def read_after_close_status(trade_date: str) -> dict[str, Any] | None:
    try:
        from services.jobs.celery_app import celery_app

        raw = celery_app.backend.client.get(_after_close_status_key(trade_date))
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
