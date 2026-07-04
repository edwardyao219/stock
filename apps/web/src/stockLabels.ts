export interface StockPoolLabelInput {
  symbol: string;
  manual_tags: string[];
}

function isStarMarketSymbol(symbol: string) {
  return symbol.trim().startsWith("688");
}

function isNextSessionCandidateTags(tags: string[]) {
  return tags.includes("after_close_candidate") || tags.includes("next_session");
}

const styleLabels: Record<string, string> = {
  growth_cycle: "科技成长",
  cyclical: "周期资源",
  consumer_quality: "消费质量",
  property_chain: "地产链",
  compound: "防守复利",
  healthcare: "医药",
  market_beta: "市场弹性",
  theme: "题材",
  unknown: "未分类",
};

const strategyLabels: Record<string, string> = {
  short_term: "短线",
  swing: "波段",
  long_term: "长线",
  filter: "过滤",
  watch_breakout: "观察突破",
};

const modeLabels: Record<string, string> = {
  exploration: "探索池",
  observation: "观察池",
  potential_watch: "潜力观察",
  formal_strategy: "策略池",
};

const tierLabels: Record<string, string> = {
  core_action: "核心行动",
  watch_wait: "观察等待",
  risk_reject: "淘汰/风险",
};

const styleGateLabels: Record<string, string> = {
  upgrade_allowed: "盘中重点观察",
  observe_only: "只观察",
  stand_down: "暂不升级",
};

const holdStyleLabels: Record<string, string> = {
  low_turnover_compound: "低换手复利",
  valuation_reversion: "估值修复",
  trend_with_catalyst: "催化趋势",
  fast_in_fast_out: "快进快出",
  cycle_trend: "周期趋势",
  beta_timing: "弹性择时",
  compound: "复利持有",
};

export function styleLabelForValue(value: string | null | undefined) {
  if (!value) return "未分类";
  return styleLabels[value] ?? "未分类";
}

function readableDateTime(value: string) {
  return value.replace("T", " ");
}

function cleanDisplayText(value: string) {
  return value.replace(/\bWeb\b/g, "网页端").replace(/\bweb\b/g, "网页端");
}

export function candidatePoolTextForStock(stock: StockPoolLabelInput) {
  const isStartupPreheat = stock.manual_tags.includes("candidate_pool:startup_preheat");
  const isExpansionConfirm = stock.manual_tags.includes("candidate_pool:expansion_confirm");
  if (isStarMarketSymbol(stock.symbol) && isStartupPreheat) return "科创池 / 启动前夜";
  if (isStarMarketSymbol(stock.symbol) && isExpansionConfirm) return "科创池 / 扩散确认";
  if (isStarMarketSymbol(stock.symbol)) return "科创池";
  if (isStartupPreheat) return "启动前夜池";
  if (isExpansionConfirm) return "扩散确认池";
  if (isNextSessionCandidateTags(stock.manual_tags)) return "普通池";
  return null;
}

export function manualTagTextForStock(value: string, stock: StockPoolLabelInput) {
  const baseLabels: Record<string, string> = {
    after_close_candidate: "盘后筛选",
    next_session: "下一交易日",
    manual_focus: "手动关注",
  };
  if (baseLabels[value]) return baseLabels[value];
  if (value === "star_pool") {
    return isStarMarketSymbol(stock.symbol) ? "科创池" : "历史分池";
  }
  if (value.startsWith("mode:")) {
    const mode = value.slice("mode:".length);
    return modeLabels[mode] ?? "候选模式";
  }
  if (value.startsWith("tier:")) {
    const tier = value.slice("tier:".length);
    return `分层：${tierLabels[tier] ?? "观察"}`;
  }
  if (value.startsWith("tier_reason:")) {
    return cleanDisplayText(value.slice("tier_reason:".length));
  }
  if (value.startsWith("candidate_summary:")) {
    return cleanDisplayText(value.slice("candidate_summary:".length));
  }
  if (value.startsWith("style:")) {
    const style = value.slice("style:".length);
    return styleLabelForValue(style);
  }
  if (value.startsWith("style_horizon:")) {
    const horizon = value.slice("style_horizon:".length).replace(/d$/, "");
    return `建议${horizon}日观察`;
  }
  if (value.startsWith("style_gate:")) {
    const status = value.slice("style_gate:".length);
    return `门控：${styleGateLabels[status] ?? "观察"}`;
  }
  if (value.startsWith("style_gate_reason:")) {
    return cleanDisplayText(value.slice("style_gate_reason:".length));
  }
  if (value === "candidate_pool:startup_preheat") return "启动前夜池";
  if (value === "candidate_pool:expansion_confirm") return "扩散确认池";
  if (value.startsWith("candidate_pool_reason:")) {
    return cleanDisplayText(value.slice("candidate_pool_reason:".length));
  }
  if (value.startsWith("rule:")) return `策略：${value.slice("rule:".length)}`;
  if (value.startsWith("strategy:")) {
    const strategy = value.slice("strategy:".length);
    return `策略：${strategyLabels[strategy] ?? "观察"}`;
  }
  if (value.startsWith("rank:")) return `排序：${value.slice("rank:".length)}`;
  if (value.startsWith("score:")) return `分数：${value.slice("score:".length)}`;
  if (value.startsWith("batch:")) return `批次：${readableDateTime(value.slice("batch:".length))}`;
  if (value.startsWith("hold_until:")) return `观察到：${value.slice("hold_until:".length)}`;
  if (value.startsWith("dropped:")) return `降级日：${value.slice("dropped:".length)}`;
  if (value.startsWith("watch_keep:")) return `保留观察：${value.slice("watch_keep:".length)}次`;
  if (value.startsWith("hold_style:")) {
    const style = value.slice("hold_style:".length);
    return `持有风格：${holdStyleLabels[style] ?? "趋势观察"}`;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return /[A-Za-z_]/.test(value) ? "系统标签" : value;
}
