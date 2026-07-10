import type { WorkspaceStock } from "./api";

export type TrackingStage =
  | "trend_holding"
  | "startup_confirming"
  | "watching"
  | "risk_review"
  | "archived";

export interface TrackingTimelineItem {
  title: string;
  date: string | null;
  tone: "good" | "warn" | "bad" | "neutral";
  lines: string[];
}

export interface TrackingMetric {
  label: string;
  value: string;
  tone: "good" | "warn" | "bad" | "neutral";
}

export interface StockTrackingProfile {
  symbol: string;
  name: string | null;
  industry: string | null;
  stage: TrackingStage;
  stageLabel: string;
  score: number;
  scoreTone: "good" | "warn" | "bad" | "neutral";
  nextAction: string;
  evidence: string[];
  risks: string[];
  metrics: TrackingMetric[];
  timeline: TrackingTimelineItem[];
}

const stageLabels: Record<TrackingStage, string> = {
  trend_holding: "趋势持有",
  startup_confirming: "启动确认",
  watching: "持续观察",
  risk_review: "风险复核",
  archived: "资料留存",
};

const styleLabels: Record<string, string> = {
  compound: "稳健复合",
  consumer_quality: "消费质量",
  growth_cycle: "科技成长",
  theme: "主题弹性",
  cyclical: "周期修复",
  market_beta: "市场弹性",
  unknown: "未分类",
};

function pct(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${(value * 100).toFixed(2)}%`;
}

function score(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(1);
}

function cleanText(value: string | null | undefined) {
  return (value ?? "")
    .replace(/^候选理由：/, "")
    .replace(/\bWeb\b/g, "网页端")
    .replace(/\bgrowth_cycle\b/g, "科技成长")
    .replace(/\bmarket_beta\b/g, "市场弹性")
    .replace(/\bunknown\b/g, "未分类")
    .trim();
}

function styleText(value: string | null | undefined) {
  if (!value) return "未分类";
  return styleLabels[value] ?? "未分类";
}

function clampScore(value: number) {
  return Math.max(0, Math.min(100, value));
}

function average(values: Array<number | null | undefined>) {
  const usable = values.filter(
    (item): item is number => item !== null && item !== undefined && !Number.isNaN(item),
  );
  if (!usable.length) return null;
  return usable.reduce((total, item) => total + item, 0) / usable.length;
}

function primaryTrade(stock: WorkspaceStock) {
  return stock.recent_paper_trades.find((trade) => trade.status === "open") ?? stock.recent_paper_trades[0] ?? null;
}

function latestPlan(stock: WorkspaceStock) {
  return stock.plans[0] ?? null;
}

function hasOpenTrade(stock: WorkspaceStock) {
  return stock.recent_paper_trades.some((trade) => trade.status === "open");
}

function hasTradablePlan(stock: WorkspaceStock) {
  return stock.plans.some((plan) => plan.can_buy_now || plan.execution_status === "tradable");
}

function isNextSessionCandidate(stock: WorkspaceStock) {
  return stock.manual_tags.includes("after_close_candidate") || stock.manual_tags.includes("next_session");
}

function rawTrackingScore(stock: WorkspaceStock) {
  const base =
    average([
      stock.trend_quality_score,
      stock.trend_score,
      stock.relative_strength_score,
      stock.sector_strength_score,
      stock.volume_confirmation_score,
      stock.candidate_score,
      stock.startup_signal_score,
    ]) ?? 45;
  const bonus =
    (hasOpenTrade(stock) ? 4 : 0) +
    (hasTradablePlan(stock) ? 3 : 0) +
    (stock.candidate_tier === "core_action" ? 3 : 0) +
    (stock.startup_signal_score !== null && stock.startup_signal_score >= 75 ? 2 : 0);
  const riskPenalty =
    Math.max(0, (stock.risk_score ?? 0) - 60) * 0.35 +
    Math.max(0, (stock.overheat_score ?? 0) - 70) * 0.25 +
    Math.max(0, (stock.volume_trap_risk_score ?? 0) - 65) * 0.35 +
    ((stock.return_20d ?? 0) >= 0.32 ? 6 : 0);
  return clampScore(base + bonus - riskPenalty);
}

function trackingStage(stock: WorkspaceStock, trackingScore: number): TrackingStage {
  if (
    stock.candidate_tier === "risk_reject" ||
    (stock.risk_score ?? 0) >= 75 ||
    (stock.volume_trap_risk_score ?? 0) >= 80
  ) {
    return "risk_review";
  }
  if (hasOpenTrade(stock) && trackingScore >= 55) return "trend_holding";
  if (hasTradablePlan(stock) || stock.candidate_tier === "core_action" || (stock.startup_signal_score ?? 0) >= 75) {
    return "startup_confirming";
  }
  if (isNextSessionCandidate(stock) || stock.candidate_tier === "watch_wait") return "watching";
  return "archived";
}

function scoreTone(value: number): StockTrackingProfile["scoreTone"] {
  if (value >= 75) return "good";
  if (value >= 58) return "warn";
  if (value < 45) return "bad";
  return "neutral";
}

function nextActionFor(stage: TrackingStage) {
  if (stage === "trend_holding") return "继续跟踪，不因一天涨跌改变结论；重点看板块是否仍强、量能是否健康、止损是否上移。";
  if (stage === "startup_confirming") return "等待启动确认，优先看板块延续、放量后承接和回踩不破趋势线。";
  if (stage === "watching") return "继续观察，先记录证据，不急着交易；等趋势、板块和量能三项同时改善。";
  if (stage === "risk_review") return "降级处理，只做复盘样本；除非风险消退并重新放量承接，否则不升级。";
  return "资料留存，除非重新进入强板块或出现新的启动信号，否则不占用主观察位。";
}

function riskLines(stock: WorkspaceStock) {
  const risks: string[] = [];
  if ((stock.risk_score ?? 0) >= 70) risks.push(`综合风险 ${score(stock.risk_score)}，需要先降权`);
  if ((stock.volume_trap_risk_score ?? 0) >= 65) risks.push(`放量诱多风险 ${score(stock.volume_trap_risk_score)}，不能只看放量`);
  if ((stock.overheat_score ?? 0) >= 70) risks.push(`过热 ${score(stock.overheat_score)}，追高性价比下降`);
  if ((stock.distance_to_ma20 ?? 0) >= 0.14) risks.push(`偏离20日线 ${pct(stock.distance_to_ma20)}，更适合等回踩`);
  if ((stock.return_20d ?? 0) >= 0.3) risks.push(`20日涨幅 ${pct(stock.return_20d)}，主升后回撤风险变大`);
  if ((stock.sector_strength_score ?? 100) < 45) risks.push(`板块强度 ${score(stock.sector_strength_score)}，个股强也要防板块拖累`);
  return risks.length ? risks : ["暂未看到需要立刻降级的硬风险，继续看承接。"];
}

function evidenceLines(stock: WorkspaceStock) {
  const evidence = [
    stock.industry ? `板块 ${stock.industry} / ${styleText(stock.sector_style)} / 强度 ${score(stock.sector_strength_score)}` : null,
    `趋势 ${score(stock.trend_score)} / 质量 ${score(stock.trend_quality_score)} / 相对强度 ${score(stock.relative_strength_score)}`,
    `量能 ${score(stock.volume_confirmation_score)} / 5日量比 ${score(stock.amount_ratio_5d)} / 60日成交分位 ${score(stock.amount_percentile_60d)}`,
    `今日 ${pct(stock.day_change_pct)} / 5日 ${pct(stock.return_5d)} / 20日 ${pct(stock.return_20d)}`,
    stock.candidate_score !== null ? `候选 ${score(stock.candidate_score)} / 启动 ${score(stock.startup_signal_score)}` : null,
    stock.route_label ? `路线 ${stock.route_label}：${cleanText(stock.route_reason)}` : null,
  ].filter((item): item is string => Boolean(item));
  return evidence;
}

function metricLines(stock: WorkspaceStock): TrackingMetric[] {
  return [
    {
      label: "趋势",
      value: score(stock.trend_score ?? stock.trend_quality_score),
      tone: (stock.trend_score ?? 0) >= 70 ? "good" : (stock.trend_score ?? 0) < 45 ? "bad" : "neutral",
    },
    {
      label: "板块",
      value: score(stock.sector_strength_score),
      tone: (stock.sector_strength_score ?? 0) >= 65 ? "good" : (stock.sector_strength_score ?? 0) < 45 ? "bad" : "neutral",
    },
    {
      label: "相对强度",
      value: score(stock.relative_strength_score),
      tone: (stock.relative_strength_score ?? 0) >= 65 ? "good" : (stock.relative_strength_score ?? 0) < 45 ? "bad" : "neutral",
    },
    {
      label: "量能",
      value: score(stock.volume_confirmation_score),
      tone: (stock.volume_confirmation_score ?? 0) >= 65 ? "good" : (stock.volume_confirmation_score ?? 0) < 45 ? "bad" : "neutral",
    },
    {
      label: "风险",
      value: score(stock.risk_score),
      tone: (stock.risk_score ?? 0) >= 70 ? "bad" : (stock.risk_score ?? 0) >= 55 ? "warn" : "good",
    },
  ];
}

function timeline(stock: WorkspaceStock, stage: TrackingStage): TrackingTimelineItem[] {
  const trade = primaryTrade(stock);
  const plan = latestPlan(stock);
  const items: TrackingTimelineItem[] = [
    {
      title: "进入观察",
      date: stock.feature_date,
      tone: "neutral",
      lines: [
        cleanText(stock.manual_note) || stock.candidate_tier_reason || "暂无入池理由，先按当前特征追踪。",
        stock.candidate_tier_label ? `分层：${stock.candidate_tier_label}` : "分层：未记录",
      ],
    },
    {
      title: "板块趋势",
      date: stock.latest_trade_date,
      tone: (stock.sector_strength_score ?? 0) >= 65 ? "good" : (stock.sector_strength_score ?? 0) < 45 ? "bad" : "neutral",
      lines: [
        stock.industry ? `${stock.industry} / ${styleText(stock.sector_style)}` : "暂无板块信息",
        `趋势 ${score(stock.trend_score)} / 板块 ${score(stock.sector_strength_score)} / 相对强度 ${score(stock.relative_strength_score)}`,
      ],
    },
    {
      title: "量能承接",
      date: stock.quote_time ?? stock.latest_trade_date,
      tone: (stock.volume_confirmation_score ?? 0) >= 65 ? "good" : (stock.volume_trap_risk_score ?? 0) >= 65 ? "bad" : "neutral",
      lines: [
        `量能确认 ${score(stock.volume_confirmation_score)} / 诱多风险 ${score(stock.volume_trap_risk_score)}`,
        `5日量比 ${score(stock.amount_ratio_5d)} / 距20日线 ${pct(stock.distance_to_ma20)}`,
      ],
    },
  ];

  if (trade) {
    items.push({
      title: trade.status === "open" ? "模拟持仓" : "最近模拟",
      date: trade.quote_time ?? trade.exit_date ?? trade.entry_date,
      tone: (trade.current_pnl_pct ?? trade.pnl_pct ?? 0) >= 0 ? "good" : "bad",
      lines: [
        `${trade.rule_id} / ${trade.status === "open" ? "持仓中" : "已结束"} / 收益 ${pct(trade.current_pnl_pct ?? trade.pnl_pct)}`,
        `买入 ${trade.entry_date} / 止损 ${score(trade.current_stop)} / 止盈 ${score(trade.take_profit_1)}`,
      ],
    });
  } else if (plan) {
    items.push({
      title: "交易计划",
      date: plan.trade_date,
      tone: plan.can_buy_now ? "good" : "neutral",
      lines: [
        `${plan.rule_id} / ${plan.execution_label} / 置信 ${score(plan.confidence_score)}`,
        plan.execution_note,
      ],
    });
  }

  items.push({
    title: "下一步",
    date: stock.quote_time ?? stock.latest_trade_date,
    tone: stage === "risk_review" ? "bad" : stage === "trend_holding" ? "good" : "neutral",
    lines: [nextActionFor(stage)],
  });
  return items;
}

export function buildStockTrackingProfile(stock: WorkspaceStock): StockTrackingProfile {
  const trackingScore = rawTrackingScore(stock);
  const stage = trackingStage(stock, trackingScore);
  return {
    symbol: stock.symbol,
    name: stock.name,
    industry: stock.industry,
    stage,
    stageLabel: stageLabels[stage],
    score: Number(trackingScore.toFixed(1)),
    scoreTone: scoreTone(trackingScore),
    nextAction: nextActionFor(stage),
    evidence: evidenceLines(stock),
    risks: riskLines(stock),
    metrics: metricLines(stock),
    timeline: timeline(stock, stage),
  };
}

export function sortStockTrackingProfiles(profiles: StockTrackingProfile[]) {
  return [...profiles].sort((left, right) => {
    const leftRisk = left.stage === "risk_review" ? 1 : 0;
    const rightRisk = right.stage === "risk_review" ? 1 : 0;
    if (leftRisk !== rightRisk) return leftRisk - rightRisk;
    const stagePriority: Record<TrackingStage, number> = {
      trend_holding: 0,
      startup_confirming: 1,
      watching: 2,
      archived: 3,
      risk_review: 4,
    };
    const stageDelta = stagePriority[left.stage] - stagePriority[right.stage];
    if (stageDelta) return stageDelta;
    return right.score - left.score || left.symbol.localeCompare(right.symbol);
  });
}
