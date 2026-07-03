from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from services.collector.akshare_client import _akshare, _without_proxy_env


@dataclass(frozen=True)
class MarketHotMessage:
    source: str
    keyword: str
    title: str
    heat: float | None = None


@dataclass(frozen=True)
class SectorCatalyst:
    sector_name: str
    catalyst_score: float
    catalyst_label: str
    keywords: list[str] = field(default_factory=list)
    related_sectors: list[str] = field(default_factory=list)
    source_titles: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SectorCatalystReport:
    as_of: datetime
    source_count: int
    catalysts: list[SectorCatalyst] = field(default_factory=list)
    message: str = "消息只做板块催化和风险解释，不单独触发买入。"
    snapshot_id: int | None = None
    snapshot_trade_date: str | None = None
    stored: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "source_count": self.source_count,
            "catalysts": [item.to_dict() for item in self.catalysts],
            "message": self.message,
            "snapshot_id": self.snapshot_id,
            "snapshot_trade_date": self.snapshot_trade_date,
            "stored": self.stored,
        }


CATALYST_RULES: tuple[dict[str, Any], ...] = (
    {
        "sector_name": "消费",
        "related_sectors": ["旅游酒店", "影视院线", "食品饮料", "白酒", "免税", "餐饮"],
        "keywords": (
            "暑期",
            "旅游",
            "酒店",
            "文旅",
            "电影",
            "票房",
            "餐饮",
            "白酒",
            "消费",
            "免税",
            "零售",
            "食品",
            "饮料",
            "景区",
        ),
        "risk_notes": (
            "消息只做催化，仍需确认板块月度排名、资金流和个股量能。",
            "暑期和消费消息有季节性，若资金没有持续流入，容易变成一日轮动。",
        ),
    },
    {
        "sector_name": "科技",
        "related_sectors": ["半导体", "算力", "通信设备", "软件服务", "元器件", "PCB"],
        "keywords": (
            "AI",
            "人工智能",
            "算力",
            "服务器",
            "光模块",
            "PCB",
            "半导体",
            "芯片",
            "存储",
            "通信",
            "机器人",
            "数据中心",
        ),
        "risk_notes": (
            "消息只做催化，科技高位时优先看承接和回撤韧性。",
            "高热度板块若盘中放量分歧，不能让新闻热度覆盖风险。",
        ),
    },
    {
        "sector_name": "新能源",
        "related_sectors": ["电池", "光伏", "风电", "电气设备", "储能", "充电桩"],
        "keywords": (
            "新能源",
            "电池",
            "锂电",
            "固态电池",
            "光伏",
            "风电",
            "储能",
            "充电桩",
            "汽车",
            "电动车",
        ),
        "risk_notes": (
            "消息只做催化，新能源需要确认趋势修复而不是单日反弹。",
            "产业链消息容易分化，要看资金集中在哪个细分方向。",
        ),
    },
    {
        "sector_name": "金融地产",
        "related_sectors": ["证券", "保险", "房地产", "银行"],
        "keywords": ("证券", "券商", "保险", "房地产", "地产", "银行", "降息", "信贷"),
        "risk_notes": (
            "消息只做催化，金融地产更像风格切换信号，不默认当作成长主线。",
            "若只是护盘或权重拉指数，需要降低对个股扩散的期待。",
        ),
    },
    {
        "sector_name": "资源周期",
        "related_sectors": ["有色金属", "黄金", "煤炭", "石油", "化工", "钢铁"],
        "keywords": (
            "黄金",
            "有色",
            "铜",
            "铝",
            "稀土",
            "煤炭",
            "石油",
            "原油",
            "化工",
            "钢铁",
        ),
        "risk_notes": (
            "消息只做催化，周期品要同时看商品价格和板块资金。",
            "资源股容易受外盘扰动，不能只看单条新闻。",
        ),
    },
)


def _record_text(raw: dict[str, Any]) -> str:
    return " ".join(
        str(raw.get(key) or "")
        for key in (
            "keyword",
            "title",
            "概念名称",
            "股票简称",
            "股票名称",
            "名称",
            "新闻标题",
            "标题",
        )
    )


def _message_from_record(raw: dict[str, Any], source: str) -> MarketHotMessage | None:
    keyword = str(
        raw.get("keyword")
        or raw.get("概念名称")
        or raw.get("股票简称")
        or raw.get("股票名称")
        or raw.get("名称")
        or ""
    ).strip()
    title = str(
        raw.get("title")
        or raw.get("新闻标题")
        or raw.get("标题")
        or raw.get("概念名称")
        or raw.get("股票简称")
        or raw.get("股票名称")
        or raw.get("名称")
        or keyword
    ).strip()
    heat_value = (
        raw.get("heat")
        or raw.get("热度")
        or raw.get("排名")
        or raw.get("当前排名")
        or raw.get("涨跌幅")
    )
    heat: float | None
    try:
        heat = float(heat_value) if heat_value is not None and str(heat_value) else None
    except (TypeError, ValueError):
        heat = None
    if not keyword and not title:
        return None
    if not keyword:
        keyword = title[:24]
    return MarketHotMessage(source=source, keyword=keyword, title=title, heat=heat)


def _messages_from_frame(frame: Any, source: str, limit: int) -> list[MarketHotMessage]:
    messages: list[MarketHotMessage] = []
    for raw in frame.head(limit).to_dict("records"):
        message = _message_from_record(raw, source)
        if message is not None:
            messages.append(message)
    return messages


def fetch_market_hot_messages(limit_per_source: int = 30) -> list[dict[str, Any]]:
    ak = _akshare()
    messages: list[MarketHotMessage] = []
    source_calls = (
        ("akshare.stock_hot_keyword_em", lambda: ak.stock_hot_keyword_em()),
        ("akshare.stock_hot_rank_em", lambda: ak.stock_hot_rank_em()),
        ("akshare.stock_hot_up_em", lambda: ak.stock_hot_up_em()),
    )
    for source, fetcher in source_calls:
        try:
            with _without_proxy_env():
                frame = fetcher()
            messages.extend(_messages_from_frame(frame, source, limit_per_source))
        except Exception:
            continue
    return [asdict(item) for item in messages]


def _label_for_score(score: float) -> str:
    if score >= 75:
        return "强催化"
    if score >= 55:
        return "有催化"
    return "观察"


def _heat_score(value: float | None) -> float:
    if value is None:
        return 45.0
    if value <= 0:
        return 45.0
    if value <= 100:
        return min(80.0, 35.0 + value * 0.45)
    return min(80.0, 40.0 + value / 10.0)


def _unique_append(items: list[str], value: str, limit: int) -> None:
    value = value.strip()
    if value and value not in items and len(items) < limit:
        items.append(value)


def build_sector_catalyst_report(
    messages: list[dict[str, Any]] | None = None,
    *,
    as_of: datetime | None = None,
    limit: int = 8,
) -> SectorCatalystReport:
    raw_messages = messages if messages is not None else fetch_market_hot_messages()
    grouped: dict[str, dict[str, Any]] = {}

    for raw in raw_messages:
        message = _message_from_record(raw, str(raw.get("source") or "unknown"))
        if message is None:
            continue
        text = _record_text({**raw, "keyword": message.keyword, "title": message.title})
        text_lower = text.lower()
        for rule in CATALYST_RULES:
            matched_keywords = [
                keyword
                for keyword in rule["keywords"]
                if keyword.lower() in text_lower
            ]
            if not matched_keywords:
                continue
            sector_name = str(rule["sector_name"])
            bucket = grouped.setdefault(
                sector_name,
                {
                    "score": 0.0,
                    "hits": 0,
                    "keywords": [],
                    "titles": [],
                    "related_sectors": list(rule["related_sectors"]),
                    "risk_notes": list(rule["risk_notes"]),
                },
            )
            bucket["hits"] += len(matched_keywords)
            bucket["score"] += _heat_score(message.heat) + 8 * min(3, len(matched_keywords))
            for keyword in matched_keywords:
                _unique_append(bucket["keywords"], keyword, 8)
            _unique_append(bucket["keywords"], message.keyword, 8)
            _unique_append(bucket["titles"], message.title, 4)

    catalysts: list[SectorCatalyst] = []
    for sector_name, bucket in grouped.items():
        hits = max(1, int(bucket["hits"]))
        score = min(100.0, round((float(bucket["score"]) / hits) + min(18.0, hits * 3), 2))
        catalysts.append(
            SectorCatalyst(
                sector_name=sector_name,
                catalyst_score=score,
                catalyst_label=_label_for_score(score),
                keywords=list(bucket["keywords"]),
                related_sectors=list(bucket["related_sectors"]),
                source_titles=list(bucket["titles"]),
                risk_notes=list(bucket["risk_notes"]),
            )
        )

    catalysts.sort(
        key=lambda item: (
            item.catalyst_score,
            len(item.keywords),
            item.sector_name,
        ),
        reverse=True,
    )
    return SectorCatalystReport(
        as_of=as_of or datetime.now(),
        source_count=len(raw_messages),
        catalysts=catalysts[:limit],
    )
