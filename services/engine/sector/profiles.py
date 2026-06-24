from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class SectorProfileConfig:
    sector_name: str
    sector_style: str
    analysis_framework: str
    default_strategy_type: str
    preferred_holding_style: str
    key_drivers: list[str] = field(default_factory=list)
    risk_notes: str | None = None

    def to_record(self) -> dict[str, object]:
        data = asdict(self)
        data["key_drivers_json"] = {"drivers": self.key_drivers}
        data.pop("key_drivers")
        return data


DEFAULT_SECTOR_PROFILES = [
    SectorProfileConfig(
        sector_name="银行",
        sector_style="compound",
        analysis_framework="banking_compound",
        default_strategy_type="long_term",
        preferred_holding_style="low_turnover_compound",
        key_drivers=["股息率", "净息差", "资产质量", "估值分位", "宏观利率"],
        risk_notes="银行股不适合频繁短炒，重点看回撤、估值和分红复利。",
    ),
    SectorProfileConfig(
        sector_name="白酒",
        sector_style="consumer_quality",
        analysis_framework="consumer_quality",
        default_strategy_type="swing",
        preferred_holding_style="valuation_reversion",
        key_drivers=["品牌力", "批价", "库存", "利润率", "估值分位"],
        risk_notes="消费白马需要关注估值和基本面预期，技术反弹不等于趋势恢复。",
    ),
    SectorProfileConfig(
        sector_name="半导体",
        sector_style="growth_cycle",
        analysis_framework="tech_growth_cycle",
        default_strategy_type="swing",
        preferred_holding_style="trend_with_catalyst",
        key_drivers=["产业周期", "国产替代", "订单", "资本开支", "政策催化"],
        risk_notes="科技成长容易受预期和估值波动影响，需要更严格的趋势确认。",
    ),
    SectorProfileConfig(
        sector_name="AI算力",
        sector_style="theme",
        analysis_framework="theme_momentum",
        default_strategy_type="short_term",
        preferred_holding_style="fast_in_fast_out",
        key_drivers=["政策/产业催化", "龙头强度", "成交额扩散", "涨停梯队", "业绩兑现"],
        risk_notes="题材股重情绪和流动性，退潮时必须快速降仓或退出。",
    ),
    SectorProfileConfig(
        sector_name="液冷温控",
        sector_style="theme",
        analysis_framework="theme_momentum",
        default_strategy_type="short_term",
        preferred_holding_style="fast_in_fast_out",
        key_drivers=["AI服务器", "数据中心资本开支", "订单兑现", "龙头强度", "成交额扩散"],
        risk_notes="液冷题材容易受订单和产业消息驱动，放量高位要防兑现。",
    ),
    SectorProfileConfig(
        sector_name="PCB",
        sector_style="growth_cycle",
        analysis_framework="tech_growth_cycle",
        default_strategy_type="swing",
        preferred_holding_style="trend_with_catalyst",
        key_drivers=["AI服务器PCB", "高速铜连接", "订单景气", "毛利率", "产能扩张"],
        risk_notes="PCB 景气趋势较强时可做波段，但涨幅过热时要看业绩兑现。",
    ),
    SectorProfileConfig(
        sector_name="通信设备",
        sector_style="theme",
        analysis_framework="theme_momentum",
        default_strategy_type="short_term",
        preferred_holding_style="fast_in_fast_out",
        key_drivers=["算力网络", "光模块/交换机", "订单催化", "海外链", "成交额强度"],
        risk_notes="通信设备题材弹性大，冲高回落和高位放量需要重点过滤。",
    ),
    SectorProfileConfig(
        sector_name="有色金属",
        sector_style="cyclical",
        analysis_framework="commodity_cycle",
        default_strategy_type="swing",
        preferred_holding_style="cycle_trend",
        key_drivers=["商品价格", "库存", "美元/利率", "供给扰动", "需求预期"],
        risk_notes="周期股需要跟踪商品价格，单纯技术突破容易被价格回落反杀。",
    ),
    SectorProfileConfig(
        sector_name="证券",
        sector_style="market_beta",
        analysis_framework="market_beta",
        default_strategy_type="short_term",
        preferred_holding_style="beta_timing",
        key_drivers=["成交额", "指数趋势", "政策预期", "风险偏好", "两融活跃度"],
        risk_notes="券商通常是市场 beta，不能脱离大盘环境单独看。",
    ),
]
