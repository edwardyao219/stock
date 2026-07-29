export interface StockPoolLabelInput {
  symbol: string;
  manual_tags: string[];
}

interface EarningsLabelInput {
  earnings_sustainability_grade?: string | null;
  earnings_sustainability_score?: number | null;
}

interface ValuationLabelInput {
  valuation_space_label?: string | null;
  valuation_upside_low?: number | null;
}

export interface CandidateQualityLabel {
  label: string;
  detail: string | null;
  tone: "positive" | "warning" | "neutral" | "negative";
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
  sector_watch: "板块观察",
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

export function candidateRuleName(tags: string[]) {
  const tag = tags.find((item) => item.startsWith("rule_name:"));
  return tag ? tag.slice("rule_name:".length) : null;
}

export function meanReversionLabel(
  ruleId?: string | null,
  ruleName?: string | null,
) {
  return ruleId === "R008" || ruleName?.startsWith("[均值回归]") ? "均值回归" : null;
}

export function earningsSustainabilityLabel(
  item: EarningsLabelInput,
): CandidateQualityLabel | null {
  const grade = item.earnings_sustainability_grade;
  if (!grade) return null;
  const meta = {
    sustainable: ["盈利可持续", "positive"],
    general: ["盈利持续性一般", "warning"],
    pending: ["财报持续性待确认", "neutral"],
    unsustainable: ["盈利不可持续", "negative"],
  }[grade] as [string, CandidateQualityLabel["tone"]] | undefined;
  if (!meta) return null;
  const score = item.earnings_sustainability_score;
  return {
    label: meta[0],
    detail:
      score !== null && score !== undefined && Number.isFinite(score)
        ? `评分 ${score.toFixed(1)}`
        : null,
    tone: meta[1],
  };
}

export function valuationSpaceLabel(
  item: ValuationLabelInput,
): CandidateQualityLabel | null {
  const value = item.valuation_space_label;
  if (!value) return null;
  const meta = {
    near_double_valuation_space: ["接近翻倍估值空间", "positive"],
    valuation_reversion_space: ["存在估值回归空间", "warning"],
    pending: ["估值空间待确认", "neutral"],
  }[value] as [string, CandidateQualityLabel["tone"]] | undefined;
  if (!meta) return null;
  const upside = item.valuation_upside_low;
  return {
    label: meta[0],
    detail:
      upside !== null && upside !== undefined && Number.isFinite(upside)
        ? `保守空间 ${upside >= 0 ? "+" : ""}${(upside * 100).toFixed(1)}%`
        : null,
    tone: meta[1],
  };
}

function readableDateTime(value: string) {
  return value.replace("T", " ");
}

const displayTokenLabels: Record<string, string> = {
  ...styleLabels,
  ...modeLabels,
  ...styleGateLabels,
  ...holdStyleLabels,
  action: "行动池",
  action_long: "长期行动池",
  all: "全候选池",
  core_candidate: "核心候选",
  low_sample: "样本不足",
  observe_only: "只观察",
  risk_off: "弱市防守",
  risk_on: "风险偏好",
  caution: "谨慎观察",
  simple_sum_no_compounding: "简单相加不复利",
  stand_down: "休息",
  startup_confirmed: "启动确认池",
  startup_preheat: "启动前夜池",
  tactical_observe: "战术观察",
  watch_wait: "观察等待",
};

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function cleanDisplayText(value: string | null | undefined) {
  if (!value) return "";
  const base = value
    .replace(/\bWeb\b/g, "网页端")
    .replace(/\bweb\b/g, "网页端")
    .replace(/策略PK/g, "策略对比")
    .replace(/\bPK\b/g, "对比");
  return Object.entries(displayTokenLabels)
    .sort(([left], [right]) => right.length - left.length)
    .reduce(
      (text, [token, label]) => text.replace(new RegExp(`\\b${escapeRegExp(token)}\\b`, "g"), label),
      base,
    );
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
  if (value.startsWith("rule_name:")) return `策略：${value.slice("rule_name:".length)}`;
  if (value.startsWith("strategy:")) {
    const strategy = value.slice("strategy:".length);
    return `策略：${strategyLabels[strategy] ?? "观察"}`;
  }
  if (value.startsWith("rank:")) return `排序：${value.slice("rank:".length)}`;
  if (value.startsWith("score:")) return `分数：${value.slice("score:".length)}`;
  if (value.startsWith("startup_signal_score:")) {
    return `启动信号：${value.slice("startup_signal_score:".length)}分`;
  }
  if (value.startsWith("startup_signal_label:")) {
    return cleanDisplayText(value.slice("startup_signal_label:".length));
  }
  if (value.startsWith("startup_signal_reason:")) {
    return cleanDisplayText(value.slice("startup_signal_reason:".length));
  }
  if (value.startsWith("earnings_grade:")) {
    return earningsSustainabilityLabel({
      earnings_sustainability_grade: value.slice("earnings_grade:".length),
    })?.label ?? "财报持续性待确认";
  }
  if (value.startsWith("earnings_score:")) {
    return `财报评分：${value.slice("earnings_score:".length)}`;
  }
  if (value.startsWith("earnings_reason:")) {
    return cleanDisplayText(value.slice("earnings_reason:".length));
  }
  if (value.startsWith("valuation_space:")) {
    return valuationSpaceLabel({
      valuation_space_label: value.slice("valuation_space:".length),
    })?.label ?? "估值空间待确认";
  }
  if (value.startsWith("fair_value_")) return "估值区间已计算";
  if (value.startsWith("valuation_upside_")) return "估值回归空间已计算";
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
