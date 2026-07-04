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
  market_beta: "市场Beta",
  theme: "题材",
  unknown: "未分类",
};

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
  if (value === "star_pool") {
    return isStarMarketSymbol(stock.symbol) ? "科创池" : "历史分池";
  }
  if (value.startsWith("style:")) {
    const style = value.slice("style:".length);
    return styleLabels[style] ?? style;
  }
  if (value.startsWith("style_horizon:")) {
    const horizon = value.slice("style_horizon:".length).replace(/d$/, "");
    return `建议${horizon}日观察`;
  }
  if (value === "candidate_pool:startup_preheat") return "启动前夜池";
  if (value === "candidate_pool:expansion_confirm") return "扩散确认池";
  if (value.startsWith("candidate_pool_reason:")) {
    return value.slice("candidate_pool_reason:".length);
  }
  return value;
}
