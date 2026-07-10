import type { Candle, WorkspaceStock } from "./api";

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

export interface CandleTrendMetric {
  label: string;
  value: string;
  tone: "good" | "warn" | "bad" | "neutral";
}

export interface CandleTrendPath {
  verdictLabel: "趋势延续" | "回踩承接" | "趋势转弱" | "样本不足";
  tone: "good" | "warn" | "bad" | "neutral";
  metrics: CandleTrendMetric[];
  points: string[];
  risks: string[];
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

function numberAverage(values: number[]) {
  if (!values.length) return null;
  return values.reduce((total, item) => total + item, 0) / values.length;
}

function closeReturn(candles: Candle[], days: number) {
  if (candles.length <= days) return null;
  const latest = candles[candles.length - 1];
  const base = candles[candles.length - 1 - days];
  if (!latest || !base || base.close <= 0) return null;
  return latest.close / base.close - 1;
}

function recentHighDrawdown(candles: Candle[], windowSize: number) {
  const latest = candles[candles.length - 1];
  if (!latest) return null;
  const window = candles.slice(-windowSize);
  const high = Math.max(...window.map((item) => item.high));
  if (!Number.isFinite(high) || high <= 0) return null;
  return latest.close / high - 1;
}

function recentAmountRatio(candles: Candle[]) {
  const amounts = candles
    .map((item) => item.amount)
    .filter((item): item is number => item !== null && item !== undefined && item > 0);
  if (amounts.length < 6) return null;
  const recent = numberAverage(amounts.slice(-5));
  const baseline = numberAverage(amounts.slice(-20));
  if (recent === null || baseline === null || baseline <= 0) return null;
  return recent / baseline;
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

export function buildCandleTrendPath(candles: Candle[]): CandleTrendPath {
  const latest = candles[candles.length - 1] ?? null;
  if (!latest || candles.length < 8) {
    return {
      verdictLabel: "样本不足",
      tone: "neutral",
      metrics: [],
      points: ["K线样本不足，先看当前候选和板块证据。"],
      risks: ["缺少足够历史K线，不能判断中长期路径。"],
    };
  }

  const ret5 = closeReturn(candles, 5);
  const ret10 = closeReturn(candles, 10);
  const ret20 = closeReturn(candles, 20);
  const drawdown20 = recentHighDrawdown(candles, Math.min(20, candles.length));
  const amountRatio = recentAmountRatio(candles);
  const ma20Distance = latest.ma20 && latest.ma20 > 0 ? latest.close / latest.ma20 - 1 : null;
  const aboveMa20 = ma20Distance === null ? null : ma20Distance >= 0;
  const ma20Slope =
    candles.length > 5 && latest.ma20 && candles[candles.length - 6]?.ma20
      ? latest.ma20 / (candles[candles.length - 6].ma20 as number) - 1
      : null;

  const weak =
    aboveMa20 === false &&
    ((drawdown20 !== null && drawdown20 <= -0.1) || (ret10 !== null && ret10 < -0.04));
  const strong =
    aboveMa20 !== false &&
    (ret20 ?? ret10 ?? 0) >= 0.08 &&
    (drawdown20 === null || drawdown20 > -0.08);
  const pullback =
    aboveMa20 !== false &&
    (drawdown20 !== null && drawdown20 <= -0.04) &&
    (ret20 ?? 0) >= 0.03;
  const verdictLabel = weak ? "趋势转弱" : strong ? "趋势延续" : pullback ? "回踩承接" : "回踩承接";
  const tone = weak ? "bad" : strong ? "good" : "warn";

  const points = [
    aboveMa20 === null
      ? "20日线数据不足，先看价格路径。"
      : aboveMa20
        ? `收盘在20日线上方 ${pct(ma20Distance)}，趋势底线暂时还在。`
        : `收盘跌破20日线 ${pct(ma20Distance)}，趋势需要复核。`,
    ma20Slope === null
      ? "20日线斜率样本不足。"
      : ma20Slope >= 0
        ? `20日线仍向上 ${pct(ma20Slope)}，中期结构未坏。`
        : `20日线转弱 ${pct(ma20Slope)}，不能只按普通回调看。`,
    amountRatio === null
      ? "量能样本不足，暂不判断承接。"
      : amountRatio >= 1.12
        ? `量能放大 ${amountRatio.toFixed(2)}倍，若价格站稳可视为承接。`
        : `量能 ${amountRatio.toFixed(2)}倍，承接还不算强。`,
  ];

  const risks = [
    aboveMa20 === false ? "跌破20日线，趋势持有需要降级观察。" : null,
    drawdown20 !== null && drawdown20 <= -0.1 ? `近20日高点回撤 ${pct(drawdown20)}，回撤已经偏深。` : null,
    ret20 !== null && ret20 >= 0.3 ? `20日收益 ${pct(ret20)}，主升后追高风险升高。` : null,
  ].filter((item): item is string => Boolean(item));

  return {
    verdictLabel,
    tone,
    metrics: [
      { label: "5日收益", value: pct(ret5), tone: (ret5 ?? 0) >= 0 ? "good" : "bad" },
      { label: "10日收益", value: pct(ret10), tone: (ret10 ?? 0) >= 0 ? "good" : "bad" },
      { label: "20日收益", value: pct(ret20), tone: (ret20 ?? 0) >= 0 ? "good" : "bad" },
      { label: "高点回撤", value: pct(drawdown20), tone: (drawdown20 ?? 0) <= -0.1 ? "bad" : "neutral" },
      { label: "5日量能", value: amountRatio === null ? "-" : `${amountRatio.toFixed(2)}倍`, tone: (amountRatio ?? 1) >= 1.12 ? "good" : "neutral" },
    ],
    points,
    risks: risks.length ? risks : ["暂未看到K线层面的硬风险，继续看板块和量能是否延续。"],
  };
}
