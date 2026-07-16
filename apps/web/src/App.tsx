import {
  BarChart3,
  ArrowUpDown,
  ClipboardList,
  Filter,
  RefreshCw,
  Search,
  TrendingUp,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  AfterCloseStatus,
  Candle,
  CandidateReplayEffectQuery,
  CandidateReplayEffectReport,
  ConfirmedMainlineOutcome,
  DataHealth,
  addManualStock,
  createTrackingSnapshots,
  fetchAfterCloseStatus,
  fetchCandidateReplayEffect,
  fetchCandles,
  fetchConfirmedMainlineOutcomes,
  fetchDataHealth,
  fetchIntradayMarketTurn,
  fetchIntradayCandidateSnapshots,
  fetchIntradayCandidates,
  fetchLowDimensionalReplay,
  fetchMarketOverview,
  fetchMechanicalReview,
  fetchMonthlySummary,
  fetchRuleRegressionStatus,
  fetchSectorCatalysts,
  fetchSectorOverview,
  fetchStartupTracking,
  fetchStrategyFit,
  fetchTrackingSignalSummary,
  fetchTrackingSnapshots,
  fetchWorkspaceStocks,
  ManualRefresh,
  IntradayCandidateList,
  IntradayCandidateSnapshotList,
  IntradayMarketTurn,
  LowDimensionalReplayReport,
  MarketOverview,
  MechanicalReview,
  MonthlySummary,
  ReplayDataCoverage,
  ReplayReturnSummary,
  refreshWorkspaceStocks,
  RuleRegressionStatus,
  SectorCatalysts,
  SectorOverview,
  SectorOverviewItem,
  StrategyFitMetric,
  StrategyFitReport,
  StartupTrackingRow,
  TrackingSnapshot,
  TrackingSignalItem,
  TrackingSignalSummary,
  WorkspaceStock,
} from "./api";
import {
  candidateListGateSummary,
  candidateCoreBlockReason,
  candidatePoolReason,
  candidateTierMeta,
  groupStocksByCandidateTier,
} from "./candidateTiers";
import {
  capitalCurveView,
  candidateGateSummary,
  defensiveValidationRows,
  dingPolicyText,
  dualLineLongReplaySummary,
  lineStatusText,
  longCandidateReplayQuery,
  monthlyDefenseSimulation,
  monthlyDefenseSignals,
  monthlyPerformanceHealth,
  monthlyPerformanceRows,
  monthlyStrategyPkRows,
  replayBreakdownRows,
  replayMonthlyStyleRows,
  replayScopeRows,
  replayStylePreferenceRows,
  strategyPkRows,
  startupSignalStyleReplayRows,
  startupSignalReplayRows,
  startupPreheatRows,
  replayWeakMonthRows,
} from "./replayInsights";
import { StrategyEvidenceChart } from "./StrategyEvidenceChart";
import {
  candidatePoolTextForStock,
  cleanDisplayText,
  manualTagTextForStock,
  styleLabelForValue,
} from "./stockLabels";
import {
  buildCandleTrendPath,
  buildStockTrackingProfile,
  sortStockTrackingProfiles,
  StockTrackingProfile,
} from "./stockTracking";
import {
  buildTrackingHistorySummary,
  buildTrackingPathSummary,
  decisionWithValidation,
} from "./trackingHistory";
import { buildAutoRefreshPlan } from "./refreshPlan";

const AUTO_REFRESH_MS = 15_000;

const sourceLabels: Record<string, string> = {
  auto: "系统筛选",
  manual: "手动关注",
  "auto+manual": "系统+手动",
};

const strategyLabels: Record<string, string> = {
  short_term: "短线",
  swing: "波段",
  long_term: "长线",
  filter: "过滤",
  watch_breakout: "观察突破",
};

const pageItems = [
  { key: "stocks", label: "股票" },
  { key: "tracking", label: "个股追踪" },
  { key: "paper", label: "实盘模拟" },
  { key: "sectors", label: "板块" },
] as const;

type PageKey = (typeof pageItems)[number]["key"];
type PaperTrade = WorkspaceStock["recent_paper_trades"][number];
type StockView = "focus" | "tradable" | "candidate" | "manual";
type StockSortMode = "priority" | "day_return";

type ReviewSummaryItem = {
  title: string;
  lines: string[];
  tone?: "good" | "bad" | "neutral";
};

const stockViewLabels: Record<StockView, string> = {
  focus: "重点",
  tradable: "可买",
  candidate: "明日候选",
  manual: "手动关注",
};

const stockViewTestIds: Record<StockView, string> = {
  focus: "stock-view-focus",
  tradable: "stock-view-tradable",
  candidate: "stock-view-candidate",
  manual: "stock-view-manual",
};

const stockSortLabels: Record<StockSortMode, string> = {
  priority: "交易优先",
  day_return: "当日收益",
};

const CHINA_GROWTH_BOARD_PREFIXES = ["300", "301"];

function pct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function pctPoint(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function replayBarWidth(value: number | null | undefined) {
  if (value === null || value === undefined) return 0;
  return Math.min(100, Math.max(8, Math.abs(value) * 250));
}

function ratioPct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toFixed(1)}%`;
}

function intradayQuoteIntegrityText(turn: IntradayMarketTurn) {
  const integrity = turn.quote_integrity;
  if (!integrity) return "";
  const retryText = integrity.retry_applied ? " / 行情已补拉" : "";
  return ` / 行情 ${integrity.valid_quote_count}/${integrity.expected_symbol_count} ${ratioPct(integrity.coverage_ratio)}${retryText}`;
}

function intradayMainlineStatus(turn: IntradayMarketTurn | null) {
  const mainline = turn?.cross_day_mainline;
  if (!mainline) {
    return { label: "待核验", detail: "暂无跨日主线快照", tone: "down" };
  }
  const sectors = mainline.confirmed_sectors.join("、");
  if (mainline.status === "观察确认" && sectors) {
    if (mainline.checkpoint === "10:30复核") {
      return { label: "启动确认", detail: `${sectors} / 可进入观察候选绑定`, tone: "up" };
    }
    return { label: "启动观察", detail: `${sectors} / 等待10:30复核`, tone: "up" };
  }
  return { label: "未启动", detail: `${mainline.checkpoint} / ${mainline.summary}`, tone: "down" };
}

function price(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return value.toFixed(2);
}

function amountText(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${(value / 100_000_000).toFixed(1)}亿`;
}

function fundFlowRateText(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function fundFlowRateBarWidth(value: number | null | undefined) {
  if (value === null || value === undefined) return 0;
  return Math.min(100, Math.max(8, (Math.abs(value) / 15) * 100));
}

function currentMonthText() {
  return new Date().toISOString().slice(0, 7);
}

function compactAmountText(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${(value / 1_000_000_000_000).toFixed(2)}万亿`;
}

function riskText(plan: WorkspaceStock["plans"][number]) {
  return `仓位 ${(plan.position_size * 100).toFixed(1)}% / 止损 ${price(
    plan.initial_stop,
  )} / 止盈 ${price(plan.take_profit_1)}`;
}

function planStatusText(value: string | null | undefined) {
  const labels: Record<string, string> = {
    planned: "等待触发",
    executed: "已自动买入",
    cancelled: "已取消",
    skipped: "已跳过",
  };
  return value ? labels[value] ?? "未知状态" : "-";
}

function exitReasonText(value: string | null | undefined) {
  const labels: Record<string, string> = {
    stop_loss: "止损",
    take_profit: "止盈",
    trailing_take_profit: "跟踪止盈",
    time_exit: "时间退出",
  };
  return value ? labels[value] ?? "其他退出" : "-";
}

function tradeStatusText(value: string | null | undefined) {
  const labels: Record<string, string> = {
    open: "持仓中",
    closed: "已卖出",
  };
  return value ? labels[value] ?? "未知状态" : "-";
}

function fitStatusText(value: string | null | undefined) {
  const labels: Record<string, string> = {
    fit: "适配",
    weak: "降权",
    validation_failed: "验证失败",
    neutral: "观察",
    profit_giveback: "卖点待优化",
    low_sample: "样本少",
  };
  return value ? labels[value] ?? "观察" : "暂无";
}

function outOfSampleText(value: string | null | undefined) {
  const labels: Record<string, string> = {
    passed: "通过",
    failed: "失败",
    insufficient: "不足",
  };
  return value ? labels[value] ?? "待验证" : "待验证";
}

function strategyText(value: string | null | undefined) {
  if (!value) return "未分类策略";
  return strategyLabels[value] ?? "未分类策略";
}

function primaryPaperTrade(stock: WorkspaceStock): PaperTrade | null {
  return stock.recent_paper_trades.find((trade) => trade.status === "open") ?? stock.recent_paper_trades[0] ?? null;
}

function tradeReturnPct(trade: PaperTrade | null, latestClose: number | null | undefined) {
  if (!trade) return null;
  if (trade.current_pnl_pct !== null && trade.current_pnl_pct !== undefined) {
    return trade.current_pnl_pct;
  }
  if (trade.pnl_pct !== null && trade.pnl_pct !== undefined) return trade.pnl_pct;
  if (trade.status === "open" && latestClose && trade.entry_price) {
    return latestClose / trade.entry_price - 1;
  }
  return null;
}

function latestPlan(stock: WorkspaceStock) {
  return stock.plans[0] ?? null;
}

function displayPrice(stock: WorkspaceStock) {
  return stock.current_price ?? stock.latest_close;
}

function hasOpenAutoTrade(stock: WorkspaceStock) {
  return stock.recent_paper_trades.some((trade) => trade.status === "open");
}

function hasTradablePlan(stock: WorkspaceStock) {
  return stock.plans.some(
    (plan) => plan.can_buy_now || plan.execution_status === "tradable",
  );
}

function isNextSessionCandidate(stock: WorkspaceStock) {
  return (
    stock.manual_tags.includes("after_close_candidate") ||
    stock.manual_tags.includes("next_session")
  );
}

function isManualFocus(stock: WorkspaceStock) {
  return stock.source.includes("manual") || stock.manual_tags.includes("manual_focus");
}

function isGrowthBoardStock(stock: WorkspaceStock) {
  return CHINA_GROWTH_BOARD_PREFIXES.some((prefix) => stock.symbol.startsWith(prefix));
}

function isFocusStock(stock: WorkspaceStock) {
  return hasTradablePlan(stock) || isNextSessionCandidate(stock);
}

function stockSourceLabel(stock: WorkspaceStock) {
  if (isNextSessionCandidate(stock)) return "明日候选";
  return sourceLabels[stock.source] ?? "其他来源";
}

function stockActionLabel(stock: WorkspaceStock) {
  if (hasTradablePlan(stock)) return "可买";
  if (isNextSessionCandidate(stock)) return "明日观察";
  if (latestPlan(stock)) return "等待触发";
  if (isManualFocus(stock)) return "手动观察";
  return "观察";
}

function stockActionClass(stock: WorkspaceStock) {
  if (hasTradablePlan(stock)) return "tradable";
  if (isNextSessionCandidate(stock)) return "candidate";
  if (latestPlan(stock)) return "planned";
  return isManualFocus(stock) ? "manual" : "neutral";
}

function manualTagText(value: string, stock: WorkspaceStock) {
  return manualTagTextForStock(value, stock);
}

function candidatePoolText(stock: WorkspaceStock) {
  return candidatePoolTextForStock(stock);
}

function candidateStrategyText(stock: WorkspaceStock) {
  if (stock.manual_tags.includes("mode:exploration")) return "探索池";
  if (stock.manual_tags.includes("mode:observation")) return "观察池";
  if (stock.manual_tags.includes("mode:potential_watch")) return "潜力观察";
  if (stock.manual_tags.includes("mode:formal_strategy")) return "策略池";
  const ruleTag = stock.manual_tags.find((item) => item.startsWith("rule:"));
  if (ruleTag) return `策略 ${ruleTag.slice(5)}`;
  const strategyTag = stock.manual_tags.find((item) => item.startsWith("strategy:"));
  if (strategyTag) return `策略 ${strategyTag.slice(9)}`;
  return null;
}

function candidateHorizonText(stock: WorkspaceStock) {
  const horizonTag = stock.manual_tags.find((item) => item.startsWith("style_horizon:"));
  if (!horizonTag) return null;
  const horizon = horizonTag.slice("style_horizon:".length).replace(/d$/, "");
  const styleTag = stock.manual_tags.find((item) => item.startsWith("style:"));
  const style = styleTag ? styleTag.slice("style:".length) : stock.sector_style ?? "unknown";
  return `建议${horizon}日观察 / ${styleLabelForValue(style)}`;
}

function startupSignalText(stock: WorkspaceStock) {
  if (!stock.startup_signal_label) return null;
  const score =
    stock.startup_signal_score !== null && stock.startup_signal_score !== undefined
      ? ` ${stock.startup_signal_score.toFixed(1)}分`
      : "";
  return `${stock.startup_signal_label}${score}`;
}

function paperClosedCount(stock: WorkspaceStock) {
  return stock.paper_trade_summaries.reduce((total, item) => total + item.closed_count, 0);
}

function paperWinRate(stock: WorkspaceStock) {
  const closedCount = paperClosedCount(stock);
  if (!closedCount) return null;
  const wins = stock.paper_trade_summaries.reduce(
    (total, item) => total + item.win_rate * item.closed_count,
    0,
  );
  return wins / closedCount;
}

function rowTradeLabel(trade: PaperTrade | null) {
  if (!trade) return "-";
  return trade.status === "open" ? "持仓中" : tradeStatusText(trade.status);
}

function timeText(value: Date | null) {
  if (!value) return "-";
  return value.toLocaleTimeString("zh-CN", { hour12: false });
}

function findFitMetric(
  report: StrategyFitReport | null,
  ruleId: string,
  scopeType: "rule" | "sector" | "symbol",
  scopeValue: string | null | undefined,
): StrategyFitMetric | null {
  if (!report || !scopeValue) return null;
  const rule = report.rules.find((item) => item.rule_id === ruleId);
  if (!rule) return null;
  if (scopeType === "rule") return rule.overall;
  const pool = scopeType === "sector" ? rule.sectors : rule.symbols;
  return pool.find((item) => item.scope_value === scopeValue) ?? null;
}

function metricReason(metric: StrategyFitMetric | null) {
  return metric?.recommendations[0]?.rationale ?? metric?.summary ?? "暂无可用回归样本。";
}

function validationLine(metric: StrategyFitMetric | null) {
  if (!metric || !metric.out_of_sample_status) return "样本外 待验证";
  return [
    `样本外 ${outOfSampleText(metric.out_of_sample_status)}`,
    `训练 ${pct(metric.train_avg_return)}`,
    `验证 ${pct(metric.validation_avg_return)}`,
  ].join(" / ");
}

function decisionTitle(stock: WorkspaceStock) {
  if (hasOpenAutoTrade(stock)) return "持仓跟踪";
  if (hasTradablePlan(stock)) return "当前可买";
  if (isNextSessionCandidate(stock)) return "明日观察";
  if (latestPlan(stock)) return "等待触发";
  return "仅观察";
}

function decisionClass(stock: WorkspaceStock) {
  if (hasOpenAutoTrade(stock)) return "holding";
  if (hasTradablePlan(stock)) return "tradable";
  if (isNextSessionCandidate(stock)) return "candidate";
  if (latestPlan(stock)) return "planned";
  return "neutral";
}

function bestFitMetric(
  report: StrategyFitReport | null,
  stock: WorkspaceStock,
  plan: WorkspaceStock["plans"][number] | null,
) {
  if (!plan) return null;
  return (
    findFitMetric(report, plan.rule_id, "sector", stock.industry) ??
    findFitMetric(report, plan.rule_id, "symbol", stock.symbol) ??
    findFitMetric(report, plan.rule_id, "rule", plan.rule_id)
  );
}

function shortFitText(metric: StrategyFitMetric | null) {
  if (!metric) return "历史样本不足，先轻仓观察";
  if (metric.fit_status === "validation_failed") return "样本外验证转弱，只观察不加权";
  if (metric.fit_status === "weak") return "历史适配偏弱，降低优先级";
  if (metric.fit_status === "fit") return "历史适配较好，但仍按计划风控";
  if (metric.fit_status === "profit_giveback") return "卖点待优化，注意浮盈回撤";
  if (metric.fit_status === "low_sample") return "样本偏少，先观察验证";
  return "历史适配中性，按触发条件执行";
}

function decisionReasons(
  stock: WorkspaceStock,
  report: StrategyFitReport | null,
  trade: PaperTrade | null,
) {
  const plan = latestPlan(stock);
  const fit = bestFitMetric(report, stock, plan);
  if (trade?.status === "open") {
    return [
      `当前浮动收益 ${pct(tradeReturnPct(trade, stock.latest_close))}`,
      `止损 ${price(trade.current_stop)} / 止盈 ${price(trade.take_profit_1)}`,
      `最高浮盈 ${pct(trade.mfe_pct)} / 最大浮亏 ${pct(trade.mae_pct)}`,
    ];
  }
  if (plan) {
    return [
      `${plan.rule_id} ${strategyText(plan.strategy_type)}，置信分 ${price(plan.confidence_score)}`,
      `触发价 ${price(plan.entry_trigger_price)} / 仓位 ${(plan.position_size * 100).toFixed(1)}%`,
      shortFitText(fit),
    ];
  }
  return [
    `今日 ${pct(stock.day_change_pct)} / 5日 ${pct(stock.return_5d)} / 20日 ${pct(stock.return_20d)}`,
    stock.industry ? `行业 ${stock.industry}` : "暂无行业信息",
    "还没有当前交易计划，先放在观察列表",
  ];
}

function mainIndexText(overview: MarketOverview | null) {
  if (!overview?.indexes.length) return "-";
  return overview.indexes
    .slice(0, 3)
    .map((item) => `${item.name} ${pct(item.change_pct)}`)
    .join(" / ");
}

function marketBreadthText(overview: MarketOverview | null) {
  if (!overview) return "-";
  return `${overview.snapshot_scope_label} · ${overview.up_count}涨 ${overview.down_count}跌`;
}

function marketCoverageText(overview: MarketOverview | null) {
  if (!overview) return "-";
  const state = overview.is_full_market ? "覆盖可用" : "覆盖不足";
  return `${overview.stock_count}/${overview.active_security_count} 样本 / ${state} ${pct(
    overview.coverage_ratio,
  )}`;
}

function indexDateText(overview: MarketOverview | null) {
  return overview?.indexes[0]?.quote_date ?? overview?.trade_date ?? "暂无最新交易日";
}

function candidateRankText(stock: WorkspaceStock) {
  if (stock.candidate_rank === null || stock.candidate_rank === undefined) return null;
  const score = stock.candidate_score !== null && stock.candidate_score !== undefined
    ? ` / ${stock.candidate_score.toFixed(1)}分`
    : "";
  return `第${stock.candidate_rank}名${score}`;
}

function cleanCandidateNote(value: string | null | undefined) {
  if (!value) return null;
  return cleanDisplayText(value.replace(/^候选理由：/, "").replace(/^策略\s+/, "策略 "));
}

function latestCandle(candles: Candle[]) {
  return candles.length ? candles[candles.length - 1] : null;
}

function candlePositionText(candle: Candle | null) {
  if (!candle) return "暂无K线数据";
  const range = candle.high - candle.low;
  if (range <= 0) return "当日振幅过小，K线参考价值有限";
  const closePosition = (candle.close - candle.low) / range;
  if (closePosition >= 0.72) return "收盘靠近日内高位，承接还可以";
  if (closePosition <= 0.35) return "收盘靠近日内低位，冲高回落压力较明显";
  return "收盘位于日内中部，方向还需要后续确认";
}

function maReviewText(candle: Candle | null) {
  if (!candle) return "均线结构暂无数据";
  const refs = [
    candle.ma5 ? `MA5 ${price(candle.ma5)}` : null,
    candle.ma10 ? `MA10 ${price(candle.ma10)}` : null,
    candle.ma20 ? `MA20 ${price(candle.ma20)}` : null,
  ].filter(Boolean);
  const aboveMa20 = candle.ma20 ? candle.close >= candle.ma20 : null;
  return `${refs.join(" / ") || "均线数据不足"}；${aboveMa20 === null ? "暂不能判断MA20位置" : aboveMa20 ? "价格仍在MA20上方" : "价格跌到MA20下方"}`;
}

function performanceVerdict(stock: WorkspaceStock) {
  const day = stock.day_change_pct ?? 0;
  const ret5 = stock.return_5d ?? 0;
  const ret20 = stock.return_20d ?? 0;
  if (day >= 0.03 && ret5 >= 0) return "今天表现符合强势候选特征";
  if (day < -0.02 || (ret5 < 0 && ret20 < 0.08)) return "今天表现不符合强势延续，需要降权观察";
  if (ret20 >= 0.28) return "趋势仍强，但短期涨幅偏高，不能按普通回调处理";
  return "今天表现中性，继续看后续是否放量确认";
}

function riskReviewText(stock: WorkspaceStock, candle: Candle | null) {
  const risks = [];
  if ((stock.return_20d ?? 0) >= 0.28) risks.push(`20日涨幅 ${pct(stock.return_20d)}，位置偏高`);
  if ((stock.day_change_pct ?? 0) >= 0.06) risks.push(`当日涨幅 ${pct(stock.day_change_pct)}，不适合追高`);
  if (candle?.ma20 && candle.close / candle.ma20 - 1 >= 0.14) {
    risks.push("价格明显远离MA20，等回踩比追涨更合理");
  }
  return risks.length ? risks.join("；") : "暂未看到明显过热风险，仍需看盘中资金承接";
}

function recentCandleSequenceText(candles: Candle[]) {
  const tail = candles.slice(-5);
  if (tail.length < 2) return "近几日K线数据不足";
  const moves: string[] = [];
  for (let index = 1; index < tail.length; index += 1) {
    const prev = tail[index - 1];
    const current = tail[index];
    moves.push(`${pct(current.close / prev.close - 1)}`);
  }
  const latest = tail[tail.length - 1] ?? null;
  const previous = tail[tail.length - 2] ?? null;
  const direction =
    latest && previous
      ? latest.close >= previous.close
        ? "最新一根收高"
        : "最新一根回落"
      : null;
  return `近${tail.length - 1}日收盘 ${moves.join(" / ")}${direction ? `；${direction}` : ""}`;
}

function marketMoodText(overview: MarketOverview | null) {
  if (!overview) return "暂无市场情绪";
  const upRatio = overview.up_ratio ?? 0;
  const amountChange = overview.amount_change_pct ?? 0;
  if (upRatio >= 0.55 && amountChange >= 0) return "市场情绪偏暖，资金愿意跟随";
  if (upRatio <= 0.45 && amountChange <= 0) return "市场情绪偏弱，强票也要等确认";
  return "市场情绪中性，主要看个股结构";
}

function marketStressTone(overview: MarketOverview | null) {
  if (!overview) return "neutral";
  if (overview.stress_status === "risk_off" || overview.stress_status === "caution") return "down";
  if (overview.stress_status === "supportive") return "up";
  return "neutral";
}

function marketStressDetail(overview: MarketOverview | null) {
  if (!overview) return "暂无大盘压力数据";
  const reason = overview.stress_reasons.slice(0, 2).join("；");
  return `${overview.risk_action_label}${reason ? ` / ${reason}` : ""}`;
}

function dataHealthTone(health: DataHealth | null) {
  if (!health) return "neutral";
  if (health.status === "ok") return "up";
  if (health.status === "critical") return "down";
  return "warn";
}

function dataHealthStatusText(health: DataHealth | null) {
  if (!health) return "暂无诊断";
  if (health.status === "ok") return "数据正常";
  if (health.status === "critical") return "严重异常";
  return "需要关注";
}

function latestIndexDate(overview: MarketOverview | null) {
  const dates = (overview?.indexes ?? [])
    .map((item) => item.quote_date)
    .filter((item): item is string => Boolean(item));
  const sortedDates = dates.sort();
  return sortedDates.length ? sortedDates[sortedDates.length - 1] : null;
}

function dataPipelineStatusText(health: DataHealth | null, overview: MarketOverview | null) {
  if (!health?.trade_date) return "等待数据";
  if (!health.candidate_generation_allowed) return "候选已阻断";
  const indexDate = latestIndexDate(overview);
  if (indexDate && indexDate > health.trade_date) return "等待收盘";
  if (health.status === "ok") return "收盘可用";
  return "需要复核";
}

function dataPipelineDetailText(health: DataHealth | null, overview: MarketOverview | null) {
  const dailyDate = health?.trade_date ?? "-";
  const indexDate = latestIndexDate(overview) ?? "-";
  const dailyCoverage = health ? ` / 日线覆盖 ${pct(health.daily_coverage_ratio)}` : "";
  return `日线日期 ${dailyDate} / 指数日期 ${indexDate}${dailyCoverage}`;
}

function planEvidenceSummary(plan: WorkspaceStock["plans"][number] | null) {
  if (!plan?.evidence.length) return [];
  return plan.evidence.slice(0, 3).map((item) => `${item.category}·${item.label} ${item.value}`);
}

function featureSummary(stock: WorkspaceStock) {
  const items = [
    stock.feature_date ? `特征日 ${stock.feature_date}` : null,
    stock.route_score !== null ? `路线 ${stock.route_label ?? "未知"} ${stock.route_score.toFixed(1)}` : null,
    stock.trend_score !== null ? `趋势 ${stock.trend_score.toFixed(1)}` : null,
    stock.relative_strength_score !== null ? `相对强度 ${stock.relative_strength_score.toFixed(1)}` : null,
    stock.sector_strength_score !== null ? `板块 ${stock.sector_strength_score.toFixed(1)}` : null,
    stock.volume_confirmation_score !== null ? `量能 ${stock.volume_confirmation_score.toFixed(1)}` : null,
    stock.route_reason ? `判断 ${cleanDisplayText(stock.route_reason)}` : null,
  ].filter(Boolean);
  return items.slice(0, 4) as string[];
}

function paperTradeSummaryText(stock: WorkspaceStock) {
  const closed = paperClosedCount(stock);
  const winRateValue = paperWinRate(stock);
  if (!closed) return "纸面交易样本还少，继续观察";
  return `纸面交易 ${closed} 笔，胜率 ${pct(winRateValue)}，先看样本是不是在变好`;
}

function buildStockReviewItems(
  stock: WorkspaceStock,
  candles: Candle[],
  overview: MarketOverview | null,
): ReviewSummaryItem[] {
  const candle = latestCandle(candles);
  const plan = latestPlan(stock);
  const candidateNote = cleanCandidateNote(stock.manual_note);
  const marketText = overview
    ? `${overview.trade_date ?? "-"} 市场 ${overview.up_count}涨/${overview.down_count}跌，成交 ${compactAmountText(overview.total_amount)}`
    : "暂无市场宽度和成交额";
  const marketMood = marketMoodText(overview);
  const sectorText = stock.industry
    ? `板块/行业：${stock.industry}${stock.sector_style ? ` / ${styleLabelForValue(stock.sector_style)}` : ""}`
    : "板块/行业数据缺失，当前只能按个股走势复盘";

  return [
    {
      title: "昨天为什么看好",
      lines: [
        candidateNote ?? "昨天只是观察候选，没有完整候选理由入库",
        candidateRankText(stock) ?? "未进入正式排名",
        ...featureSummary(stock),
        ...(planEvidenceSummary(plan).length ? planEvidenceSummary(plan) : []),
      ],
      tone: "neutral",
    },
    {
      title: "今天是否验证",
      lines: [
        performanceVerdict(stock),
        `今日 ${pct(stock.day_change_pct)} / 5日 ${pct(stock.return_5d)} / 20日 ${pct(stock.return_20d)}`,
        recentCandleSequenceText(candles),
        candlePositionText(candle),
      ],
      tone:
        (stock.day_change_pct ?? 0) >= 0 || (stock.return_5d ?? 0) > 0
          ? "good"
          : "bad",
    },
    {
      title: "K线与位置",
      lines: [
        candle
          ? `O${price(candle.open)} H${price(candle.high)} L${price(candle.low)} C${price(candle.close)}`
          : "暂无当日K线",
        maReviewText(candle),
        riskReviewText(stock, candle),
      ],
      tone: (stock.return_20d ?? 0) >= 0.28 ? "bad" : "neutral",
    },
    {
      title: "环境与下一步",
      lines: [
        sectorText,
        marketText,
        marketMood,
        paperTradeSummaryText(stock),
        plan
          ? "已有计划，明天只按触发条件和风控执行"
          : "没有交易计划，先观察，不因为上涨本身补买",
      ],
      tone: "neutral",
    },
  ];
}

function stockPriority(stock: WorkspaceStock) {
  if (hasTradablePlan(stock)) return 1;
  if (isNextSessionCandidate(stock)) return 2 + (stock.candidate_rank ?? 99) / 1000;
  if (latestPlan(stock)) return 3;
  return 4;
}

function compareNumberDesc(left: number | null | undefined, right: number | null | undefined) {
  if (left === null || left === undefined) return right === null || right === undefined ? 0 : 1;
  if (right === null || right === undefined) return -1;
  return right - left;
}

function scoreText(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return value.toFixed(1);
}

function objectText(item: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number") return String(value);
  }
  return "-";
}

function objectNumber(item: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "number") return value;
    if (typeof value === "string" && value.trim() && !Number.isNaN(Number(value))) {
      return Number(value);
    }
  }
  return null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asRecordList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item): item is Record<string, unknown> => Boolean(item)) : [];
}

function reviewMetricRecord(review: MechanicalReview | null, key: string) {
  return asRecord(review?.metrics?.[key]);
}

function nestedMetricList(parent: Record<string, unknown> | null, key: string) {
  return parent ? asRecordList(parent[key]) : [];
}

function reviewMetricList(review: MechanicalReview | null, key: string) {
  return asRecordList(review?.metrics?.[key]);
}

function reviewHealthTone(status: string | null | undefined) {
  if (status === "ok") return "up";
  if (status === "critical") return "down";
  if (status) return "warn";
  return "neutral";
}

function reviewHealthLabel(status: string | null | undefined) {
  if (status === "ok") return "正常";
  if (status === "critical") return "严重";
  if (status && status !== "-") return "关注";
  return "未知";
}

function reviewBreadthTone(value: number | null | undefined) {
  if (value === null || value === undefined) return "neutral";
  if (value >= 0.55) return "up";
  if (value <= 0.45) return "down";
  return "neutral";
}

function reviewSectorLine(item: Record<string, unknown>) {
  const name = objectText(item, ["sector", "sector_name"]);
  const avg = objectNumber(item, ["avg_change_pct"]);
  const upRatio = objectNumber(item, ["up_ratio"]);
  const flow = objectNumber(item, ["fund_flow_rate"]);
  return `${name} / 均涨 ${pct(avg)} / 上涨 ${ratioPct(upRatio)} / 资金 ${fundFlowRateText(flow)}`;
}

function reviewSectorBarWidth(item: Record<string, unknown>) {
  const avg = objectNumber(item, ["avg_change_pct"]);
  if (avg === null) return 0;
  return Math.min(100, Math.max(10, Math.abs(avg) * 1800));
}

function factorInsightLabel(item: Record<string, unknown>) {
  const name = objectText(item, ["factor_name", "factor_id", "name"]);
  const avgReturn = objectNumber(item, ["avg_return", "return", "avg_pnl"]);
  const sample = objectNumber(item, ["sample_count", "count"]);
  return `${name} / 样本 ${sample ?? "-"} / 平均 ${pct(avgReturn)}`;
}

function sectorOpportunityLabel(item: Record<string, unknown>) {
  const sector = objectText(item, ["sector", "sector_name"]);
  const avgReturn = objectNumber(item, ["avg_return", "monthly_return", "return"]);
  const count = objectNumber(item, ["sample_count", "trade_count", "count"]);
  return `${sector} / 样本 ${count ?? "-"} / 平均 ${pct(avgReturn)}`;
}

function sectorFlowText(item: SectorOverviewItem) {
  const net = amountText(item.fund_flow_net_amount);
  const rate = fundFlowRateText(item.fund_flow_rate);
  if (net === "-" && rate === "-") return "暂无资金流";
  return `${net} / ${rate}`;
}

type SectorRadarKind = "monthly" | "activity" | "continuity";

function sectorRadarValue(item: SectorOverviewItem, kind: SectorRadarKind) {
  if (kind === "activity") return item.fund_flow_rate;
  if (kind === "continuity") return item.sector_strength_score;
  return item.monthly_return_pct;
}

function sectorRadarValueText(item: SectorOverviewItem, kind: SectorRadarKind) {
  const value = sectorRadarValue(item, kind);
  if (kind === "continuity") return scoreText(value);
  if (kind === "activity") return fundFlowRateText(value);
  return pct(value);
}

function sectorRadarWidth(item: SectorOverviewItem, kind: SectorRadarKind) {
  const value = sectorRadarValue(item, kind);
  if (value === null || value === undefined) return 0;
  if (kind === "activity") return fundFlowRateBarWidth(value);
  if (kind === "continuity") return Math.min(100, Math.max(8, value));
  return Math.min(100, Math.max(8, Math.abs(value) * 280));
}

function sectorRadarTone(item: SectorOverviewItem, kind: SectorRadarKind) {
  const value = sectorRadarValue(item, kind);
  if (value === null || value === undefined) return "neutral";
  if (kind === "continuity") {
    if (value >= 60) return "up";
    if (value < 45) return "down";
    return "neutral";
  }
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "neutral";
}

function sectorBreadthText(item: SectorOverviewItem) {
  if (item.sector_up_count === null || item.sector_up_count === undefined) return "样本不足";
  if (item.sector_stock_count === null || item.sector_stock_count === undefined) return `${item.sector_up_count}家上涨`;
  return `${item.sector_up_count}/${item.sector_stock_count} 上涨`;
}

function sectorSignalText(item: SectorOverviewItem) {
  const parts = [
    item.sector_strength_score !== null ? `强度 ${scoreText(item.sector_strength_score)}` : null,
    item.sector_breadth_score !== null ? `广度 ${scoreText(item.sector_breadth_score)}` : null,
    item.sector_momentum_score !== null ? `动量 ${scoreText(item.sector_momentum_score)}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" / ") : "暂无技术侧特征";
}

function sectorGateText(item: SectorOverviewItem) {
  if (!item.sector_gate_label) return "门控待确认";
  return `${item.sector_gate_label} / ${scoreText(item.sector_gate_score)}分`;
}

function replayCacheText(report: CandidateReplayEffectReport | null) {
  const cache = report?.replay_cache;
  if (!cache) return null;
  if (cache.hit) return "缓存命中";
  if (cache.mode === "monthly_shards") {
    return `分片计算 ${cache.shard_hits ?? 0}/${cache.shard_count ?? 0}`;
  }
  return "刚刚计算";
}

function sectorTone(item: SectorOverviewItem) {
  const gateScore = item.sector_gate_score;
  if (gateScore !== null && gateScore !== undefined) {
    if (gateScore >= 70) return "up";
    if (gateScore < 50) return "down";
  }
  const strength = item.sector_strength_score ?? 0;
  const month = item.monthly_return_pct ?? 0;
  if (strength >= 72 || month >= 0.12) return "up";
  if (strength <= 48 || month <= -0.03) return "down";
  return "neutral";
}

function catalystTone(score: number) {
  if (score >= 75) return "up";
  if (score >= 55) return "neutral";
  return "down";
}

function intradayTone(state: string) {
  if (["gap_down_repair", "strong_continuation", "pullback_repair"].includes(state)) {
    return "up";
  }
  if (["distribution", "fading", "downside"].includes(state)) return "down";
  return "neutral";
}

function intradayItemTone(state: string, sectorSignal: string) {
  if (sectorSignal === "weak_sector") return "down";
  if (sectorSignal === "strong_sector" && !["distribution", "fading", "downside"].includes(state)) {
    return "up";
  }
  return intradayTone(state);
}

function selectionTierTone(tier: string) {
  if (tier === "formal") return "formal";
  if (tier === "defer") return "defer";
  return "watch";
}

function timeOnly(value: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(11, 16) || value;
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function dateTimeText(value: string | null | undefined) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function catalystMetaText(catalysts: SectorCatalysts | null) {
  if (!catalysts) return "等待快照";
  const source = `来源 ${catalysts.source_count}`;
  if (catalysts.stored && catalysts.snapshot_id) {
    return `快照 ${catalysts.snapshot_id} / ${source}`;
  }
  return `实时 / ${source}`;
}

function cautionText(item: { selection_reason?: string; caution_reasons: string[]; summary: string }) {
  if (item.selection_reason) return cleanDisplayText(item.selection_reason);
  return cleanDisplayText(item.caution_reasons.length ? item.caution_reasons.join("；") : item.summary);
}

function candidateExplanationText(item: {
  selection_reason?: string;
  caution_reasons: string[];
  summary: string;
  theme_signal_reason?: string | null;
}) {
  const base = cautionText(item);
  if (!item.theme_signal_reason || base.includes(item.theme_signal_reason)) return base;
  return cleanDisplayText(`${base}；${item.theme_signal_reason}`);
}

function candidateBatchText(batch: IntradayCandidateList["candidate_batch"] | undefined) {
  if (!batch) return "等待实时快照";
  const batchDate = batch.auto_feature_date ?? batch.auto_hold_until ?? "暂无自动批次";
  const parts = [
    `筛选 ${batchDate}`,
    `自动 ${batch.current_auto_candidate_count}`,
    `手动 ${batch.manual_focus_count}`,
  ];
  if (batch.stale_auto_candidate_count > 0) {
    parts.push(`旧批过滤 ${batch.stale_auto_candidate_count}`);
  }
  return parts.join(" / ");
}

function intradaySectorDistributionText(
  distribution: IntradayCandidateList["sector_distribution"] | null | undefined,
) {
  if (!distribution) return "候选板块等待";
  const sectors = distribution.top_sectors
    .slice(0, 3)
    .map((item) => `${item.sector}${item.count}`)
    .join("、");
  return `候选板块 ${sectors || "-"} / ${distribution.sector_count}个板块 / 可用${distribution.eligible_count}只`;
}

function intradayMarketStressText(stress: IntradayCandidateList["market_stress"] | undefined) {
  if (!stress) return "市场压力未接入";
  const scope = stress.snapshot_scope_label ?? stress.trade_date ?? "盘面";
  const action = stress.risk_action_label ? ` / ${stress.risk_action_label}` : "";
  return `${scope} ${stress.stress_label}${action}`;
}

function intradayQuoteCoverageText(coverage: IntradayCandidateList["quote_coverage"] | undefined) {
  if (!coverage) return "快照覆盖等待";
  if (!coverage.target_symbol_count) return "热门板块待刷 0";
  return `热门板块快照 ${coverage.valid_quote_count}/${coverage.target_symbol_count} / ${ratioPct(
    coverage.coverage_ratio,
  )}`;
}

function intradayQuoteCoverageGapText(coverage: IntradayCandidateList["quote_coverage"] | undefined) {
  if (!coverage || !coverage.target_symbol_count) return "";
  const missingCount = coverage.target_symbol_count - coverage.valid_quote_count;
  if (missingCount <= 0) return "热门板块快照已覆盖";
  const weakSector = coverage.sectors.find((item) => item.missing_symbols.length);
  const sectorText = weakSector
    ? `${weakSector.sector} ${weakSector.valid_quote_count}/${weakSector.target_symbol_count}`
    : "板块明细等待";
  return `缺 ${missingCount} 只 / ${sectorText}`;
}

function learningTone(verdict: string) {
  if (["repaired", "held_strength", "improved"].includes(verdict)) return "up";
  if (["weakened", "stayed_weak", "softened"].includes(verdict)) return "down";
  return "neutral";
}

function signedScore(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}`;
}

function replayHorizonMetric(report: LowDimensionalReplayReport | null, horizon: number) {
  return report?.horizons[horizon]?.guarded ?? null;
}

function replayMonthlyItems(report: LowDimensionalReplayReport | null, horizon: number) {
  const rows = report?.monthly_horizons[horizon] ?? {};
  return Object.entries(rows)
    .filter(([, item]) => item.guarded.sample_count > 0)
    .sort(([left], [right]) => right.localeCompare(left));
}

function replayExitText(metric: { exit_reasons?: Record<string, number> } | null) {
  const reasons = metric?.exit_reasons ?? {};
  const labels: Record<string, string> = {
    horizon: "持满",
    stop_loss: "止损",
    trailing_drawdown: "回撤",
  };
  return Object.entries(reasons)
    .map(([key, value]) => `${labels[key] ?? "其他退出"}${value}`)
    .join(" / ");
}

function replayCoverageGradeLabel(grade: string | undefined) {
  const labels: Record<string, string> = {
    strong: "覆盖扎实",
    usable: "可用",
    partial: "部分可用",
    no_data: "无数据",
  };
  return labels[grade ?? ""] ?? "待确认";
}

function replayCoverageSummary(coverage: ReplayDataCoverage | null) {
  if (!coverage) return "";
  const { overall } = coverage;
  return `可用月份 ${overall.usable_months}/${overall.months}，风险月份 ${overall.warning_months}，活跃样本 ${overall.active_symbols}`;
}

function ruleRegressionStatusLabel(status: RuleRegressionStatus["status"] | undefined) {
  if (status === "running") return "运行中";
  if (status === "queued") return "排队中";
  if (status === "idle") return "空闲";
  if (status === "never_run") return "未运行";
  return "待确认";
}

function afterCloseStatusLabel(status: string | undefined) {
  if (status === "ok") return "已完成";
  if (status === "warning") return "需关注";
  if (status === "failed") return "失败";
  if (status === "skipped") return "已跳过";
  if (status === "unknown") return "未记录";
  return "待确认";
}

function afterCloseStatusTone(status: string | undefined) {
  if (status === "ok") return "ok";
  if (status === "warning" || status === "skipped") return "warn";
  if (status === "failed") return "failed";
  return "unknown";
}

function afterCloseDingText(status: AfterCloseStatus | null) {
  const statuses = status?.dingtalk_statuses ?? [];
  if (!statuses.length) return "钉钉未记录";
  const okCount = statuses.filter((item) => item.endsWith(":ok")).length;
  if (okCount === statuses.length) return `钉钉已发送 ${okCount} 条`;
  return statuses.join(" / ");
}

function uiText(value: string | null | undefined) {
  return cleanDisplayText(value);
}

function dualLineLeaderText(value: string) {
  if (value === "main") return "核心线";
  if (value === "support") return "启动线";
  return "无明显领先";
}

function trackingSnapshotTone(item: TrackingSnapshot) {
  if (item.tracking_state_key === "risk_review" || item.tracking_state_key === "weakening") {
    return "bad";
  }
  if (item.tracking_state_key === "overheat_review" || item.tracking_state_key === "startup_preheat") {
    return "warn";
  }
  if (item.stage === "risk_review") return "bad";
  if (item.stage === "startup_confirming") return "warn";
  if (item.stage === "trend_holding") return "good";
  if ((item.tracking_score ?? 0) >= 70) return "good";
  if ((item.tracking_score ?? 0) < 45) return "bad";
  return "neutral";
}

function trackingHistoryBarWidth(value: number | null | undefined) {
  if (value === null || value === undefined) return 6;
  return Math.min(100, Math.max(6, value));
}

function trackingScoreDeltaText(
  latest: TrackingSnapshot | null,
  previous: TrackingSnapshot | null,
) {
  if (!latest || !previous || latest.tracking_score === null || previous.tracking_score === null) {
    return "-";
  }
  const delta = latest.tracking_score - previous.tracking_score;
  return `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`;
}

export function App() {
  const [activePage, setActivePage] = useState<PageKey>("stocks");
  const [stocks, setStocks] = useState<WorkspaceStock[]>([]);
  const [startupTracking, setStartupTracking] = useState<StartupTrackingRow[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [manualSymbol, setManualSymbol] = useState("");
  const [manualNote, setManualNote] = useState("");
  const [manualAdding, setManualAdding] = useState(false);
  const [manualError, setManualError] = useState<string | null>(null);
  const [manualRefreshInfo, setManualRefreshInfo] = useState<ManualRefresh | null>(null);
  const [stockView, setStockView] = useState<StockView>("focus");
  const [stockSortMode, setStockSortMode] = useState<StockSortMode>("priority");
  const [includeGrowthBoard, setIncludeGrowthBoard] = useState(false);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [tradeDialogOpen, setTradeDialogOpen] = useState(false);
  const [marketOverview, setMarketOverview] = useState<MarketOverview | null>(null);
  const [intradayMarketTurn, setIntradayMarketTurn] = useState<IntradayMarketTurn | null>(null);
  const [confirmedMainlineOutcomes, setConfirmedMainlineOutcomes] = useState<
    ConfirmedMainlineOutcome[]
  >([]);
  const [intradayCandidates, setIntradayCandidates] = useState<IntradayCandidateList | null>(null);
  const [intradaySnapshots, setIntradaySnapshots] =
    useState<IntradayCandidateSnapshotList | null>(null);
  const [sectorOverview, setSectorOverview] = useState<SectorOverview | null>(null);
  const [sectorCatalysts, setSectorCatalysts] = useState<SectorCatalysts | null>(null);
  const [dataHealth, setDataHealth] = useState<DataHealth | null>(null);
  const [selectedSectorCode, setSelectedSectorCode] = useState<string | null>(null);
  const [mechanicalReview, setMechanicalReview] = useState<MechanicalReview | null>(null);
  const [afterCloseStatus, setAfterCloseStatus] = useState<AfterCloseStatus | null>(null);
  const [afterCloseStatusError, setAfterCloseStatusError] = useState<string | null>(null);
  const [monthlySummary, setMonthlySummary] = useState<MonthlySummary | null>(null);
  const [lowDimensionalReplay, setLowDimensionalReplay] =
    useState<LowDimensionalReplayReport | null>(null);
  const [lowDimensionalReplayLoading, setLowDimensionalReplayLoading] = useState(false);
  const [lowDimensionalReplayError, setLowDimensionalReplayError] = useState<string | null>(null);
  const [candidateReplayEffect, setCandidateReplayEffect] =
    useState<CandidateReplayEffectReport | null>(null);
  const [candidateReplayEffectLoading, setCandidateReplayEffectLoading] = useState(false);
  const [candidateReplayEffectError, setCandidateReplayEffectError] = useState<string | null>(null);
  const [ruleRegressionStatus, setRuleRegressionStatus] =
    useState<RuleRegressionStatus | null>(null);
  const [ruleRegressionStatusLoading, setRuleRegressionStatusLoading] = useState(false);
  const [ruleRegressionStatusError, setRuleRegressionStatusError] = useState<string | null>(null);
  const [strategyFit, setStrategyFit] = useState<StrategyFitReport | null>(null);
  const [strategyFitError, setStrategyFitError] = useState<string | null>(null);
  const [trackingHistory, setTrackingHistory] = useState<TrackingSnapshot[]>([]);
  const [trackingSignalSummary, setTrackingSignalSummary] =
    useState<TrackingSignalSummary | null>(null);
  const [trackingHistoryLoading, setTrackingHistoryLoading] = useState(false);
  const [trackingHistoryError, setTrackingHistoryError] = useState<string | null>(null);
  const [trackingSnapshotCreating, setTrackingSnapshotCreating] = useState(false);
  const [postCloseDrawerOpen, setPostCloseDrawerOpen] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const boardFilteredStocks = useMemo(
    () =>
      includeGrowthBoard
        ? stocks
        : stocks.filter((item) => !isGrowthBoardStock(item)),
    [stocks, includeGrowthBoard],
  );

  const selected = useMemo(
    () =>
      boardFilteredStocks.find((item) => item.symbol === selectedSymbol) ??
      boardFilteredStocks[0] ??
      null,
    [selectedSymbol, boardFilteredStocks],
  );

  const filteredStocks = useMemo(() => {
    const keyword = query.trim();
    const filtered = boardFilteredStocks.filter((item) => {
      const matchView =
        stockView === "focus"
          ? isFocusStock(item)
          : stockView === "tradable"
            ? hasTradablePlan(item)
            : stockView === "candidate"
              ? isNextSessionCandidate(item)
              : isManualFocus(item);
      const matchKeyword =
        !keyword ||
        item.symbol.includes(keyword) ||
        (item.name ?? "").includes(keyword) ||
        (item.industry ?? "").includes(keyword);
      const matchGrowthBoard = includeGrowthBoard || !isGrowthBoardStock(item);
      return matchView && matchKeyword && matchGrowthBoard;
    });
    return [...filtered].sort((left: WorkspaceStock, right: WorkspaceStock) => {
      const leftScore = left.candidate_score ?? left.plans[0]?.confidence_score;
      const rightScore = right.candidate_score ?? right.plans[0]?.confidence_score;
      const leftReturn = left.day_change_pct;
      const rightReturn = right.day_change_pct;

      if (stockSortMode === "day_return") {
        const returnDelta = compareNumberDesc(leftReturn, rightReturn);
        if (returnDelta) return returnDelta;
        const priorityDelta = stockPriority(left) - stockPriority(right);
        if (priorityDelta) return priorityDelta;
        const scoreDelta = compareNumberDesc(leftScore, rightScore);
        if (scoreDelta) return scoreDelta;
      } else {
        const priorityDelta = stockPriority(left) - stockPriority(right);
        if (priorityDelta) return priorityDelta;
        const scoreDelta = compareNumberDesc(leftScore, rightScore);
        if (scoreDelta) return scoreDelta;
        const returnDelta = compareNumberDesc(leftReturn, rightReturn);
        if (returnDelta) return returnDelta;
      }

      return left.symbol.localeCompare(right.symbol);
    });
  }, [boardFilteredStocks, query, stockSortMode, stockView]);

  const paperTradeStocks = useMemo(() => {
    return boardFilteredStocks
      .filter((item) => item.recent_paper_trades.length > 0)
      .sort((left, right) => {
        const leftTrade = primaryPaperTrade(left);
        const rightTrade = primaryPaperTrade(right);
        const openDelta =
          Number(rightTrade?.status === "open") - Number(leftTrade?.status === "open");
        if (openDelta) return openDelta;
        const leftTime = leftTrade?.quote_time ?? leftTrade?.exit_date ?? leftTrade?.entry_date ?? "";
        const rightTime = rightTrade?.quote_time ?? rightTrade?.exit_date ?? rightTrade?.entry_date ?? "";
        const timeDelta = rightTime.localeCompare(leftTime);
        if (timeDelta) return timeDelta;
        return left.symbol.localeCompare(right.symbol);
      });
  }, [boardFilteredStocks]);

  const trackingSignalBySymbol = useMemo(
    () => new Map((trackingSignalSummary?.items ?? []).map((item) => [item.symbol, item])),
    [trackingSignalSummary],
  );

  const trackingProfiles = useMemo(
    () => sortStockTrackingProfiles(
      boardFilteredStocks.map(buildStockTrackingProfile),
      trackingSignalBySymbol,
    ),
    [boardFilteredStocks, trackingSignalBySymbol],
  );

  const selectedTrackingProfile = useMemo(
    () =>
      trackingProfiles.find((item) => item.symbol === selectedSymbol) ??
      trackingProfiles[0] ??
      null,
    [selectedSymbol, trackingProfiles],
  );
  const selectedCandleTrendPath = useMemo(() => buildCandleTrendPath(candles), [candles]);
  const trackingHistoryOldestFirst = useMemo(() => [...trackingHistory].reverse(), [trackingHistory]);
  const trackingHistorySummary = useMemo(
    () => buildTrackingHistorySummary(trackingHistory),
    [trackingHistory],
  );
  const trackingPathSummary = useMemo(
    () => buildTrackingPathSummary(trackingHistory),
    [trackingHistory],
  );
  const selectedTrackingDecision = useMemo(
    () =>
      selectedTrackingProfile
        ? decisionWithValidation(selectedTrackingProfile.decision, trackingPathSummary)
        : null,
    [selectedTrackingProfile, trackingPathSummary],
  );
  const trackingHistoryLatest = trackingHistory[0] ?? null;
  const trackingHistoryPrevious = trackingHistory[1] ?? null;
  const selectedTrackingState = {
    key: trackingHistoryLatest?.tracking_state_key ?? selectedTrackingProfile?.stage ?? "watching",
    label: trackingHistoryLatest?.tracking_state_label ?? selectedTrackingProfile?.stageLabel ?? "持续观察",
    reason:
      trackingHistoryLatest?.tracking_state_reason ??
      selectedTrackingProfile?.nextAction ??
      "生成快照后显示追踪状态",
  };
  const selectedStartupPhase = {
    key: trackingHistoryLatest?.startup_phase_key ?? "no_signal",
    label: trackingHistoryLatest?.startup_phase_label ?? "待生成快照",
    reason: trackingHistoryLatest?.startup_phase_reason ?? "生成今日快照后显示启动阶段",
  };

  const selectedIndustry = selected?.industry ?? null;
  const selectedSymbolValue = selected?.symbol ?? null;

  const selectedPlanFitRows = useMemo(
    () =>
      selected
        ? selected.plans.map((plan) => ({
            plan,
            overall: findFitMetric(strategyFit, plan.rule_id, "rule", plan.rule_id),
            sector: findFitMetric(strategyFit, plan.rule_id, "sector", selectedIndustry),
            symbol: findFitMetric(strategyFit, plan.rule_id, "symbol", selectedSymbolValue),
          }))
        : [],
    [selected, selectedIndustry, selectedSymbolValue, strategyFit],
  );

  const selectedSector = useMemo(
    () =>
      sectorOverview?.sectors.find((item) => item.sector_code === selectedSectorCode)
      ?? sectorOverview?.sectors[0]
      ?? null,
    [sectorOverview, selectedSectorCode],
  );

  const paperStats = useMemo(() => {
    const summaries = boardFilteredStocks.flatMap((item) => item.paper_trade_summaries);
    const closedCount = summaries.reduce((total, item) => total + item.closed_count, 0);
    const totalReturn = summaries.reduce((total, item) => total + item.total_return, 0);
    const today = marketOverview?.trade_date;
    const todayTrades = boardFilteredStocks
      .flatMap((item) => item.recent_paper_trades)
      .filter((trade) => trade.status === "closed" && trade.exit_date === today);
    const todayWins = todayTrades.filter((trade) => (trade.pnl_pct ?? 0) > 0).length;
    return {
      closedCount,
      totalReturn,
      todayClosedCount: todayTrades.length,
      todayWinRate: todayTrades.length ? todayWins / todayTrades.length : null,
    };
  }, [boardFilteredStocks, marketOverview?.trade_date]);

  async function loadTrackingSignalSummary() {
    try {
      setTrackingSignalSummary(await fetchTrackingSignalSummary("experiment", includeGrowthBoard));
    } catch {
      setTrackingSignalSummary(null);
    }
  }

  async function loadWorkspace(
    options: { refreshQuotes?: boolean; silent?: boolean; focusSymbol?: string } = {},
  ) {
    if (options.silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const nextStocks = options.refreshQuotes
        ? await refreshWorkspaceStocks("experiment", includeGrowthBoard)
        : await fetchWorkspaceStocks("experiment", includeGrowthBoard);
      setStocks(nextStocks);
      setStartupTracking(await fetchStartupTracking("experiment"));
      setIntradayCandidates(
        await fetchIntradayCandidates(
          "experiment",
          includeGrowthBoard,
          Boolean(options.refreshQuotes),
        ),
      );
      setIntradaySnapshots(
        await fetchIntradayCandidateSnapshots("experiment", includeGrowthBoard),
      );
      await loadTrackingSignalSummary();
      setSelectedSymbol((current) => {
        if (options.focusSymbol && nextStocks.some((item) => item.symbol === options.focusSymbol)) {
          return options.focusSymbol;
        }
        if (current && nextStocks.some((item) => item.symbol === current)) return current;
        return nextStocks[0]?.symbol ?? null;
      });
      setLastRefreshedAt(new Date());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载失败");
    } finally {
      if (options.silent) {
        setRefreshing(false);
      } else {
        setLoading(false);
      }
    }
  }

  async function loadCandles(symbol: string) {
    try {
      setCandles(await fetchCandles(symbol));
    } catch {
      setCandles([]);
    }
  }

  async function loadStrategyFit(symbol?: string | null) {
    try {
      setStrategyFit(await fetchStrategyFit(symbol));
      setStrategyFitError(null);
    } catch (exc) {
      setStrategyFit(null);
      setStrategyFitError(exc instanceof Error ? exc.message : "策略适配加载失败");
    }
  }

  async function loadLowDimensionalReplay() {
    setLowDimensionalReplayLoading(true);
    setLowDimensionalReplayError(null);
    try {
      setLowDimensionalReplay(await fetchLowDimensionalReplay());
    } catch (exc) {
      setLowDimensionalReplay(null);
      setLowDimensionalReplayError(exc instanceof Error ? exc.message : "长期回归加载失败");
    } finally {
      setLowDimensionalReplayLoading(false);
    }
  }

  async function loadCandidateReplayEffect(query?: CandidateReplayEffectQuery) {
    setCandidateReplayEffectLoading(true);
    setCandidateReplayEffectError(null);
    try {
      setCandidateReplayEffect(await fetchCandidateReplayEffect(query));
    } catch (exc) {
      setCandidateReplayEffect(null);
      setCandidateReplayEffectError(exc instanceof Error ? exc.message : "策略效果加载失败");
    } finally {
      setCandidateReplayEffectLoading(false);
    }
  }

  async function loadRuleRegressionStatus() {
    setRuleRegressionStatusLoading(true);
    setRuleRegressionStatusError(null);
    try {
      setRuleRegressionStatus(await fetchRuleRegressionStatus());
    } catch (exc) {
      setRuleRegressionStatus(null);
      setRuleRegressionStatusError(exc instanceof Error ? exc.message : "规则回归状态加载失败");
    } finally {
      setRuleRegressionStatusLoading(false);
    }
  }

  async function loadMarketOverview(live = true) {
    try {
      setMarketOverview(await fetchMarketOverview(live));
    } catch {
      setMarketOverview(null);
    }
  }

  async function loadIntradayMarketTurn() {
    try {
      setIntradayMarketTurn(await fetchIntradayMarketTurn());
    } catch {
      setIntradayMarketTurn(null);
    }
  }

  async function loadConfirmedMainlineOutcomes() {
    try {
      setConfirmedMainlineOutcomes(await fetchConfirmedMainlineOutcomes());
    } catch {
      setConfirmedMainlineOutcomes([]);
    }
  }

  async function loadIntradayCandidates(refreshQuotes = false) {
    try {
      setIntradayCandidates(
        await fetchIntradayCandidates("experiment", includeGrowthBoard, refreshQuotes),
      );
      setIntradaySnapshots(
        await fetchIntradayCandidateSnapshots("experiment", includeGrowthBoard),
      );
    } catch {
      setIntradayCandidates(null);
      setIntradaySnapshots(null);
    }
  }

  async function loadSectorOverview() {
    try {
      const next = await fetchSectorOverview();
      setSectorOverview(next);
      setSelectedSectorCode((current) => {
        if (current && next.sectors.some((item) => item.sector_code === current)) return current;
        return next.sectors[0]?.sector_code ?? null;
      });
    } catch {
      setSectorOverview(null);
    }
  }

  async function loadSectorCatalysts() {
    try {
      setSectorCatalysts(await fetchSectorCatalysts());
    } catch {
      setSectorCatalysts(null);
    }
  }

  async function loadDataHealth(tradeDate?: string | null) {
    try {
      setDataHealth(await fetchDataHealth(tradeDate));
    } catch {
      setDataHealth(null);
    }
  }

  async function loadMonthlySummary() {
    try {
      setMonthlySummary(await fetchMonthlySummary(currentMonthText()));
    } catch {
      setMonthlySummary(null);
    }
  }

  async function loadMechanicalReview() {
    try {
      setMechanicalReview(await fetchMechanicalReview());
    } catch {
      setMechanicalReview(null);
    }
  }

  async function loadAfterCloseStatus(tradeDate?: string | null) {
    try {
      setAfterCloseStatus(await fetchAfterCloseStatus(tradeDate));
      setAfterCloseStatusError(null);
    } catch (exc) {
      setAfterCloseStatus(null);
      setAfterCloseStatusError(exc instanceof Error ? exc.message : "6点推送状态加载失败");
    }
  }

  async function generateTrackingSnapshot() {
    const symbol = selectedTrackingProfile?.symbol;
    if (!symbol) return;
    setTrackingSnapshotCreating(true);
    setTrackingHistoryError(null);
    try {
      await createTrackingSnapshots("experiment", includeGrowthBoard);
      setTrackingHistory(await fetchTrackingSnapshots(symbol));
      await loadTrackingSignalSummary();
      setLastRefreshedAt(new Date());
    } catch (exc) {
      setTrackingHistoryError(exc instanceof Error ? exc.message : "追踪快照生成失败");
    } finally {
      setTrackingSnapshotCreating(false);
    }
  }

  async function addManualFocus() {
    const symbol = manualSymbol.trim();
    if (!symbol) return;
    setManualError(null);
    setManualAdding(true);
    try {
      const added = await addManualStock(symbol, manualNote, []);
      setManualSymbol("");
      setManualNote("");
      setQuery("");
      setStockView("manual");
      setSelectedSymbol(added.symbol);
      setManualRefreshInfo(added.manual_refresh ?? null);
      await loadWorkspace({ focusSymbol: added.symbol });
    } catch (exc) {
      setManualError(exc instanceof Error ? exc.message : "关注失败");
    } finally {
      setManualAdding(false);
    }
  }

  function switchPage(page: PageKey) {
    setActivePage(page);
    if (page === "sectors") {
      loadSectorOverview();
      loadSectorCatalysts();
      loadConfirmedMainlineOutcomes();
      loadDataHealth(marketOverview?.trade_date);
    }
  }

  useEffect(() => {
    loadWorkspace();
  }, [includeGrowthBoard]);

  useEffect(() => {
    loadMarketOverview();
    loadIntradayMarketTurn();
    loadConfirmedMainlineOutcomes();
    loadIntradayCandidates();
    loadSectorOverview();
    loadSectorCatalysts();
    loadDataHealth();
    loadMechanicalReview();
    loadAfterCloseStatus();
    loadMonthlySummary();
    loadRuleRegressionStatus();
  }, []);

  useEffect(() => {
    loadStrategyFit(selectedSymbolValue);
  }, [selectedSymbolValue]);

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const timer = window.setInterval(() => {
      const plan = buildAutoRefreshPlan({
        activePage,
        selectedSymbol,
        isDocumentVisible: document.visibilityState !== "hidden",
        isHeavyTaskRunning: lowDimensionalReplayLoading || candidateReplayEffectLoading,
      });
      if (plan.workspace) loadWorkspace({ refreshQuotes: true, silent: true });
      if (plan.marketOverview) loadMarketOverview();
      if (plan.marketOverview) loadIntradayMarketTurn();
      if (plan.intradayCandidates) loadIntradayCandidates();
      if (plan.sectorOverview) loadSectorOverview();
      if (plan.sectorOverview) loadConfirmedMainlineOutcomes();
      if (plan.sectorCatalysts) loadSectorCatalysts();
      if (plan.dataHealth) loadDataHealth(marketOverview?.trade_date);
      if (plan.candles && selectedSymbol) loadCandles(selectedSymbol);
    }, AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [
    activePage,
    autoRefresh,
    selectedSymbol,
    includeGrowthBoard,
    marketOverview?.trade_date,
    lowDimensionalReplayLoading,
    candidateReplayEffectLoading,
  ]);

  useEffect(() => {
    if (selected?.symbol) loadCandles(selected.symbol);
    setTradeDialogOpen(false);
  }, [selected?.symbol]);

  useEffect(() => {
    const symbol = selectedTrackingProfile?.symbol;
    if (activePage !== "tracking" || !symbol) {
      setTrackingHistory([]);
      setTrackingHistoryError(null);
      setTrackingHistoryLoading(false);
      return undefined;
    }
    let cancelled = false;
    setTrackingHistory([]);
    setTrackingHistoryLoading(true);
    setTrackingHistoryError(null);
    fetchTrackingSnapshots(symbol)
      .then((items) => {
        if (!cancelled) setTrackingHistory(items);
      })
      .catch((exc) => {
        if (!cancelled) {
          setTrackingHistory([]);
          setTrackingHistoryError(exc instanceof Error ? exc.message : "追踪历史加载失败");
        }
      })
      .finally(() => {
        if (!cancelled) setTrackingHistoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activePage, selectedTrackingProfile?.symbol]);

  const marketTrendText = mainIndexText(marketOverview);
  const marketWidthText = marketBreadthText(marketOverview);
  const marketStressScopeText = marketOverview?.stress_scope_label ?? "盘面压力";
  const marketStressText = marketOverview?.stress_label ?? "-";
  const capitalText = marketOverview ? compactAmountText(marketOverview.total_amount) : "-";
  const coverageText = marketCoverageText(marketOverview);
  const reviewMarketSummary = reviewMetricRecord(mechanicalReview, "market_summary");
  const reviewDisplayMarketSummary = reviewMarketSummary ?? {
    trade_date: marketOverview?.trade_date ?? null,
    up_count: marketOverview?.up_count ?? null,
    down_count: marketOverview?.down_count ?? null,
    up_ratio: marketOverview?.up_ratio ?? null,
    avg_change_pct: marketOverview?.avg_change_pct ?? null,
    amount_change_pct: marketOverview?.amount_change_pct ?? null,
    total_amount: marketOverview?.total_amount ?? null,
  };
  const reviewDataHealth = reviewMetricRecord(mechanicalReview, "data_health");
  const reviewCrossSection = reviewMetricRecord(mechanicalReview, "market_cross_section");
  const reviewIndexes = reviewMetricList(mechanicalReview, "market_indexes");
  const reviewStrongSectors = nestedMetricList(reviewCrossSection, "strong_sectors");
  const reviewWeakSectors = nestedMetricList(reviewCrossSection, "weak_sectors");
  const reviewUpRatio = objectNumber(reviewDisplayMarketSummary, ["up_ratio"]);
  const reviewAmountChange = objectNumber(reviewDisplayMarketSummary, ["amount_change_pct"]);
  const reviewHealthStatus = objectText(reviewDataHealth ?? {}, ["status"]);
  const tradableCount = boardFilteredStocks.filter(hasTradablePlan).length;
  const openTradeCount = boardFilteredStocks.filter(hasOpenAutoTrade).length;
  const candidateCount = boardFilteredStocks.filter(isNextSessionCandidate).length;
  const paperOpenStocks = paperTradeStocks.filter(hasOpenAutoTrade);
  const paperFloatingReturn = paperOpenStocks.reduce((total, item) => {
    return total + (tradeReturnPct(primaryPaperTrade(item), item.latest_close) ?? 0);
  }, 0);
  const paperClosedTodayCount = paperTradeStocks.filter((item) => {
    const trade = primaryPaperTrade(item);
    return trade?.status === "closed" && trade.exit_date === marketOverview?.trade_date;
  }).length;
  const trackingHoldingCount = trackingProfiles.filter((item) => item.stage === "trend_holding").length;
  const trackingStartupCount = trackingProfiles.filter((item) => item.stage === "startup_confirming").length;
  const trackingRiskCount = trackingProfiles.filter((item) => item.stage === "risk_review").length;
  const trackingAverageScore = trackingProfiles.length
    ? trackingProfiles.reduce((total, item) => total + item.score, 0) / trackingProfiles.length
    : null;
  const selectedTrade = selected ? primaryPaperTrade(selected) : null;
  const selectedTradeReturn = selected
    ? tradeReturnPct(selectedTrade, selected.latest_close)
    : null;
  const selectedPlan = selected ? latestPlan(selected) : null;
  const selectedDecisionReasons = selected
    ? decisionReasons(selected, strategyFit, selectedTrade)
    : [];
  const selectedStockReviewItems = selected
    ? buildStockReviewItems(selected, candles, marketOverview)
    : [];
  const replay5d = replayHorizonMetric(lowDimensionalReplay, 5);
  const replay10d = replayHorizonMetric(lowDimensionalReplay, 10);
  const replay20d = replayHorizonMetric(lowDimensionalReplay, 20);
  const replayCapitalCurve20d = capitalCurveView(lowDimensionalReplay, 20);
  const replayDefensiveValidationRows = defensiveValidationRows(lowDimensionalReplay);
  const replayMetricCards: Array<[string, ReplayReturnSummary | null]> = [
    ["5日", replay5d],
    ["10日", replay10d],
    ["20日", replay20d],
  ];
  const candidateReplayScopeRows = replayScopeRows(candidateReplayEffect, 20);
  const candidateStrategyPk = candidateReplayEffect?.diagnosis.strategy_pk ?? null;
  const candidateStrategyPkRows = strategyPkRows(candidateReplayEffect);
  const candidateDualLineLongSummary = dualLineLongReplaySummary(candidateReplayEffect);
  const candidateMonthlyStrategyPkRows = monthlyStrategyPkRows(candidateReplayEffect, 20, 6);
  const visualStrategyLines = candidateDualLineLongSummary
    ? [candidateDualLineLongSummary.mainLine, candidateDualLineLongSummary.supportLine]
    : [];
  const visualMonthlyRows = candidateMonthlyStrategyPkRows.slice(0, 4);
  const mainLineMonthlyPerformanceAll = monthlyPerformanceRows(
    candidateReplayEffect,
    "action_long",
    20,
    60,
  );
  const mainLineMonthlyPerformance = mainLineMonthlyPerformanceAll.slice(0, 8);
  const mainLineMonthlyHealth = monthlyPerformanceHealth(mainLineMonthlyPerformanceAll, 0.15);
  const mainLineDefenseSignals = monthlyDefenseSignals(mainLineMonthlyPerformanceAll, 0.1, 0.15, 6);
  const mainLineDefenseSimulation = monthlyDefenseSimulation(mainLineMonthlyPerformanceAll, 0.1, 0.15);
  const candidateReplayCacheText = replayCacheText(candidateReplayEffect);
  const candidateReplayWindowLabel = candidateReplayEffect
    ? (
        candidateReplayEffect.start_date === longCandidateReplayQuery.start_date
        && candidateReplayEffect.end_date === longCandidateReplayQuery.end_date
      )
        ? "长周期回放"
        : "近三个月回放"
    : null;
  const replayModeRows = replayBreakdownRows(lowDimensionalReplay, 20, "selection_mode").slice(0, 4);
  const replayStyleRows = replayBreakdownRows(lowDimensionalReplay, 20, "style").slice(0, 5);
  const replayWeakMonths = replayWeakMonthRows(lowDimensionalReplay, 20, 5);
  const replayStylePreferences = replayStylePreferenceRows(lowDimensionalReplay).slice(0, 5);
  const startupPreheatEffectRows = startupPreheatRows(candidateReplayEffect);
  const startupSignalEffectRows = startupSignalReplayRows(candidateReplayEffect);
  const startupSignalStyleEffectRows = startupSignalStyleReplayRows(candidateReplayEffect, 20, 5);
  const potentialWatchStyleRows = replayMonthlyStyleRows(
    candidateReplayEffect?.scopes.potential_watch,
    10,
  ).slice(0, 5);
  const startupPreheatGateRows =
    candidateReplayEffect?.diagnosis.startup_preheat_policy.rows.slice(0, 5) ?? [];
  const styleGateRows = candidateReplayEffect?.diagnosis.style_gate_policy.rows.slice(0, 5) ?? [];
  const replayDataCoverage =
    candidateReplayEffect?.data_coverage ?? lowDimensionalReplay?.data_coverage ?? null;
  const replayCoverageWarnings = replayDataCoverage?.warnings.slice(0, 3) ?? [];
  const candidateTierGroups = useMemo(
    () => groupStocksByCandidateTier(filteredStocks.filter(isNextSessionCandidate)),
    [filteredStocks],
  );
  const candidateBlockReason = useMemo(
    () => candidateCoreBlockReason(filteredStocks.filter(isNextSessionCandidate)),
    [filteredStocks],
  );
  const candidateGate = useMemo(
    () =>
      candidateReplayEffect
        ? candidateGateSummary(candidateReplayEffect, candidateBlockReason)
        : candidateListGateSummary(candidateTierGroups, candidateBlockReason),
    [candidateReplayEffect, candidateBlockReason, candidateTierGroups],
  );
  const candidateTierSections = [
    {
      key: "core-action",
      title: "核心行动",
      hint: "最多只放少数真正值得盯盘的票",
      stocks: candidateTierGroups.coreAction,
    },
    {
      key: "sector-watch",
      title: "防守板块观察",
      hint: "每个方向保留代表票，交给人判断，非买点",
      stocks: candidateTierGroups.sectorWatch,
    },
    {
      key: "startup-preheat",
      title: "启动前夜",
      hint: "T-1量价修复，先盯次日承接，不进核心",
      stocks: candidateTierGroups.startupPreheat,
    },
    {
      key: "expansion-confirm",
      title: "扩散确认",
      hint: "板块扩散和个股启动同步，只在网页端观察承接",
      stocks: candidateTierGroups.expansionConfirm,
    },
    {
      key: "watch-wait",
      title: "观察等待",
      hint: "趋势可跟踪，但买点或板块确认还差一点",
      stocks: candidateTierGroups.watchWait,
    },
    {
      key: "risk-reject",
      title: "淘汰/风险",
      hint: "当前不纳入行动池，只保留风险原因",
      stocks: candidateTierGroups.riskReject,
    },
  ];

  function renderStockRow(item: WorkspaceStock) {
    const rowPlan = latestPlan(item);
    const tierMeta = isNextSessionCandidate(item) ? candidateTierMeta(item) : null;
    const poolReason = isNextSessionCandidate(item) ? candidatePoolReason(item) : null;
    return (
      <button
        key={item.symbol}
        className={`stock-row ${selected?.symbol === item.symbol ? "selected" : ""}`}
        type="button"
        onClick={() => setSelectedSymbol(item.symbol)}
      >
        <span>
          <strong>{item.symbol}</strong>
          <small>{item.name ?? "未命名"} {item.industry ? ` / ${item.industry}` : ""}</small>
          <small>{styleLabelForValue(item.sector_style)} / 分数 {scoreText(item.candidate_score)}</small>
        </span>
        <span className="source-stack">
          <span className={`source-pill ${stockActionClass(item)}`}>
            {stockActionLabel(item)}
          </span>
          {tierMeta ? (
            <span className={`source-pill tier-${tierMeta.tier.replace("_", "-")}`}>
              {tierMeta.label}
            </span>
          ) : null}
          {candidateRankText(item) ? (
            <small>{candidateRankText(item)}</small>
          ) : isNextSessionCandidate(item) ? (
            <small>{item.manual_tags.find((tag) => /^\d{4}-\d{2}-\d{2}$/.test(tag)) ?? "盘后候选"}</small>
          ) : (
            <small>{stockSourceLabel(item)}</small>
          )}
          {candidatePoolText(item) ? <small>{candidatePoolText(item)}</small> : null}
          {candidateStrategyText(item) ? <small>{candidateStrategyText(item)}</small> : null}
          {candidateHorizonText(item) ? <small>{candidateHorizonText(item)}</small> : null}
          {startupSignalText(item) ? <small>{startupSignalText(item)}</small> : null}
          {item.startup_signal_reasons[0] ? (
            <small className="tier-reason">{uiText(item.startup_signal_reasons[0])}</small>
          ) : null}
          {poolReason ? <small className="tier-reason">{uiText(poolReason)}</small> : null}
          {tierMeta?.reason ? <small className="tier-reason">{uiText(tierMeta.reason)}</small> : null}
        </span>
        <span>
          <em className={(item.return_5d ?? 0) >= 0 ? "up" : "down"}>{pct(item.return_5d)}</em>
          <small>今日 {pct(item.day_change_pct)} / 20日 {pct(item.return_20d)}</small>
          <small>现价 {price(displayPrice(item))}</small>
        </span>
        <span className="trade-cell">
          <strong>{rowPlan ? planStatusText(rowPlan.status) : "-"}</strong>
          <small>
            {rowPlan
              ? `触发 ${price(rowPlan.entry_trigger_price)} / 仓位 ${(rowPlan.position_size * 100).toFixed(1)}%`
              : isNextSessionCandidate(item)
                ? "等待次日计划"
                : "无交易计划"}
          </small>
          <small>
            {rowPlan
              ? `置信 ${price(rowPlan.confidence_score)} / 止损 ${price(rowPlan.initial_stop)}`
              : `候选分数 ${scoreText(item.candidate_score)}`}
          </small>
        </span>
      </button>
    );
  }

  function renderTrackingRow(profile: StockTrackingProfile) {
    const signal: TrackingSignalItem | undefined = trackingSignalBySymbol.get(profile.symbol);
    const signalTone = signal?.signal_alignment_tone ?? "neutral";
    const signalLabel = signal?.signal_alignment_label ?? "样本沉淀";
    const sampleText = signal ? `样本 ${signal.sample_count}` : "样本 0";
    const returnText = signal ? `跟踪收益 ${pctPoint(signal.simple_return_pct)}` : "跟踪收益 -";
    return (
      <button
        className={`tracking-row ${profile.stage} ${selectedTrackingProfile?.symbol === profile.symbol ? "selected" : ""}`}
        key={profile.symbol}
        type="button"
        onClick={() => setSelectedSymbol(profile.symbol)}
      >
        <span>
          <strong>{profile.symbol} {profile.name ?? ""}</strong>
          <small>{profile.industry ?? "暂无行业"}</small>
        </span>
        <span>
          <strong>{profile.stageLabel}</strong>
          <small>{profile.nextAction}</small>
        </span>
        <span>
          <strong className={profile.scoreTone}>{profile.score.toFixed(1)}</strong>
          <small>{sampleText} / {returnText}</small>
          <small className={signalTone}>{signalLabel}</small>
        </span>
      </button>
    );
  }

  function renderPaperTradeRow(item: WorkspaceStock) {
    const trade = primaryPaperTrade(item);
    if (!trade) return null;
    const rowReturn = tradeReturnPct(trade, item.latest_close);
    const isOpen = trade.status === "open";
    const currentOrExitPrice = isOpen ? trade.current_price : trade.exit_price;
    return (
      <button
        key={`${item.symbol}-${trade.id}`}
        className={`paper-trade-row ${isOpen ? "open" : "closed"} ${
          selected?.symbol === item.symbol ? "selected" : ""
        }`}
        type="button"
        onClick={() => {
          setSelectedSymbol(item.symbol);
          setActivePage("stocks");
        }}
      >
        <span>
          <strong>{item.symbol} {item.name ?? ""}</strong>
          <small>{item.industry ?? "暂无行业"} / {styleLabelForValue(item.sector_style)}</small>
          <small>{trade.rule_id} / {strategyText(trade.status === "open" ? latestPlan(item)?.strategy_type : null)}</small>
        </span>
        <span>
          <strong>{isOpen ? "持仓中" : tradeStatusText(trade.status)}</strong>
          <small>买入 {trade.entry_date} @ {price(trade.entry_price)}</small>
          <small>
            {isOpen
              ? `报价 ${trade.quote_time ?? item.quote_time ?? "-"}`
              : `卖出 ${trade.exit_date ?? "-"} @ ${price(trade.exit_price)}`}
          </small>
        </span>
        <span>
          <strong className={(rowReturn ?? 0) >= 0 ? "up" : "down"}>{pct(rowReturn)}</strong>
          <small>当前/卖出 {price(currentOrExitPrice)}</small>
          <small>今日 {pct(item.day_change_pct)} / 持有 {trade.holding_days}天</small>
        </span>
        <span>
          <strong>{isOpen ? "风控跟踪" : exitReasonText(trade.exit_reason)}</strong>
          <small>止损 {price(trade.current_stop)} / 止盈 {price(trade.take_profit_1)}</small>
          <small>顶峰 {pct(trade.mfe_pct)} / 最大浮亏 {pct(trade.mae_pct)}</small>
        </span>
        <span className="paper-trade-action">查看个股</span>
      </button>
    );
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand-line">
          <BarChart3 size={24} />
          <div>
            <h1>股票交易辅助系统</h1>
            <p>每天围绕候选股、持仓、交易计划和复盘展开，历史学习在后台持续修正策略适配度。</p>
          </div>
        </div>
        <nav className="page-nav">
          {pageItems.map((page) => (
            <button
              className={activePage === page.key ? "active" : ""}
              key={page.key}
              type="button"
              onClick={() => switchPage(page.key)}
            >
              {page.label}
            </button>
          ))}
        </nav>
        <div className="header-actions">
          <label className="auto-refresh-toggle">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(event) => setAutoRefresh(event.target.checked)}
            />
            <span>自动刷新</span>
            <small>{refreshing ? "更新中" : `上次 ${timeText(lastRefreshedAt)}`}</small>
          </label>
          <button className="refresh-button" type="button" onClick={() => loadWorkspace({ refreshQuotes: true })}>
            <RefreshCw size={16} />
            刷新
          </button>
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}
      {activePage === "stocks" ? (
        <>
          <section className="summary-strip">
            <div>
              <span>主要指数</span>
              <strong className={((marketOverview?.indexes[0]?.change_pct ?? 0) >= 0 ? "up" : "down")}>
                {marketTrendText}
              </strong>
              <small>指数日期 {indexDateText(marketOverview)}</small>
            </div>
            <div>
              <span>市场宽度</span>
              <strong className={((marketOverview?.up_ratio ?? 0) >= 0.5 ? "up" : "down")}>
                {marketWidthText}
              </strong>
              <small>
                {marketOverview
                  ? `${marketOverview.trade_date ?? "-"} / 上涨占比 ${pct(marketOverview.up_ratio)} / ${coverageText}`
                  : ""}
              </small>
            </div>
            <div>
              <span>市场成交</span>
              <strong>{capitalText}</strong>
              <small>
                {marketOverview
                  ? `${marketOverview.trade_date ?? "-"} / 较前日 ${pct(marketOverview.amount_change_pct)}`
                  : "暂无成交额数据"}
              </small>
            </div>
            <div>
              <span>{marketStressScopeText}</span>
              <strong className={marketStressTone(marketOverview)}>{marketStressText}</strong>
              <small>{marketStressDetail(marketOverview)}</small>
            </div>
            <div>
              <span>市场环境</span>
              <strong className={intradayMarketTurn?.startup_watch_allowed ? "up" : "down"}>
                {intradayMarketTurn?.label ?? "待采集"}
              </strong>
              <small>
                {intradayMarketTurn
                  ? `${intradayMarketTurn.confirmed_signals.length}/4 修复，${intradayMarketTurn.snapshot_time ? timeText(new Date(intradayMarketTurn.snapshot_time)) : "等待快照"} / 仅观察启动${intradayQuoteIntegrityText(intradayMarketTurn)}`
                  : "等待全市场快照"}
              </small>
            </div>
            <div>
              <span>主线启动</span>
              <strong className={intradayMainlineStatus(intradayMarketTurn).tone}>
                {intradayMainlineStatus(intradayMarketTurn).label}
              </strong>
              <small>{intradayMainlineStatus(intradayMarketTurn).detail}</small>
            </div>
            <div>
              <span>今日可买</span>
              <strong>{tradableCount}</strong>
              <small>满足当前触发条件</small>
            </div>
            <div>
              <span>当前持仓</span>
              <strong>{openTradeCount}</strong>
              <small>系统已模拟买入</small>
            </div>
            <div>
              <span>明日候选</span>
              <strong>{candidateCount}</strong>
              <small>
                今日胜率 {pct(paperStats.todayWinRate)} / 已平 {paperStats.closedCount} 笔
              </small>
            </div>
          </section>

          <section className="post-close-review-panel">
            <div className="post-close-review-head">
              <div>
                <span>收盘复盘</span>
                <strong>{mechanicalReview?.found ? mechanicalReview.title : "暂无收盘总体复盘"}</strong>
                <small>
                  {mechanicalReview?.found
                    ? `报告 ${mechanicalReview.report_date ?? "-"} / 数据 ${objectText(reviewDisplayMarketSummary, ["trade_date"])}`
                    : "收盘后会展示大盘、板块和候选回看"}
                </small>
              </div>
              <div className="post-close-review-actions">
                <button
                  type="button"
                  onClick={() => {
                    loadMechanicalReview();
                    loadAfterCloseStatus(marketOverview?.trade_date);
                  }}
                  aria-label="刷新收盘复盘"
                >
                  <RefreshCw size={14} />
                </button>
                <button
                  className="post-close-review-open"
                  type="button"
                  onClick={() => setPostCloseDrawerOpen(true)}
                  aria-label="打开收盘复盘抽屉"
                >
                  <ClipboardList size={14} />
                  <span>查看复盘</span>
                </button>
              </div>
            </div>
            <div className="post-close-review-brief">
              <span>
                <b>6点推送</b>
                {afterCloseStatus || afterCloseStatusError
                  ? `${afterCloseStatusLabel(afterCloseStatus?.status)} / ${afterCloseDingText(afterCloseStatus)}`
                  : "未记录"}
              </span>
              <span>
                <b>盘面宽度</b>
                {mechanicalReview?.found
                  ? `${objectNumber(reviewDisplayMarketSummary, ["up_count"]) ?? "-"}涨 ${objectNumber(
                    reviewDisplayMarketSummary,
                    ["down_count"],
                  ) ?? "-"}跌`
                  : "等待收盘复盘"}
              </span>
              <span>
                <b>强弱板块</b>
                {reviewStrongSectors[0]
                  ? `${objectText(reviewStrongSectors[0], ["sector"])} 强 / ${
                    reviewWeakSectors[0] ? `${objectText(reviewWeakSectors[0], ["sector"])} 弱` : "弱势待确认"
                  }`
                  : "样本不足"}
              </span>
            </div>
          </section>

          <section className="intraday-watch-strip">
            <div className="intraday-watch-head">
              <div>
                <span>盘中候选</span>
                <strong>{intradayCandidates?.candidate_count ?? 0}</strong>
                <small>
                  {intradayCandidates?.trade_date ?? "-"} /{" "}
                  {candidateBatchText(intradayCandidates?.candidate_batch)}
                </small>
                <small>{intradaySectorDistributionText(intradayCandidates?.sector_distribution)}</small>
                <small>{intradayMarketStressText(intradayCandidates?.market_stress)}</small>
                <small>{intradayQuoteCoverageText(intradayCandidates?.quote_coverage)}</small>
              </div>
              <button
                type="button"
                onClick={() => loadIntradayCandidates(true)}
                aria-label="刷新盘中候选"
              >
                <RefreshCw size={14} />
              </button>
            </div>
            <div className="intraday-watch-body">
              {intradayCandidates?.quote_coverage ? (
                <div className="intraday-coverage-strip">
                  <div>
                    <span>早盘覆盖</span>
                    <strong
                      className={
                        intradayCandidates.quote_coverage.coverage_ratio >= 0.8 ? "up" : "down"
                      }
                    >
                      {ratioPct(intradayCandidates.quote_coverage.coverage_ratio)}
                    </strong>
                    <small>{intradayQuoteCoverageGapText(intradayCandidates.quote_coverage)}</small>
                  </div>
                  {intradayCandidates.quote_coverage.sectors.slice(0, 3).map((item) => (
                    <div key={item.sector}>
                      <span>{item.sector}</span>
                      <strong>{item.valid_quote_count}/{item.target_symbol_count}</strong>
                      <small>
                        {item.missing_symbols.length
                          ? `缺 ${item.missing_symbols.slice(0, 3).join("、")}`
                          : "已覆盖"}
                      </small>
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="intraday-watch-list">
                {intradayCandidates?.candidates.length ? (
                  intradayCandidates.candidates.slice(0, 8).map((item) => (
                    <button
                      className={`intraday-watch-item ${intradayItemTone(
                        item.intraday_state,
                        item.sector_signal,
                      )}`}
                      key={item.symbol}
                      type="button"
                      onClick={() => setSelectedSymbol(item.symbol)}
                    >
                      <span className="intraday-watch-main">
                        <strong>
                          {item.symbol}
                          <i className={`tier-pill ${selectionTierTone(item.selection_tier)}`}>
                            {item.selection_tier_label}
                          </i>
                        </strong>
                        <small>{item.name ?? "-"} / {item.sector ?? "-"}</small>
                        <em>{candidateExplanationText(item)}</em>
                      </span>
                      <span>
                        <b>{item.intraday_label}</b>
                        <small>
                          {pct(item.day_change_pct)} / {item.intraday_score.toFixed(1)}分
                        </small>
                        <small>
                          {item.review_window_label} / {item.sector_quality_label}
                          {item.sector_quality_score.toFixed(1)}分
                        </small>
                      </span>
                    </button>
                  ))
                ) : (
                  <div className="intraday-empty">暂无盘中候选快照</div>
                )}
              </div>
            </div>
          </section>

          {postCloseDrawerOpen ? (
            <div className="post-close-review-overlay" onClick={() => setPostCloseDrawerOpen(false)}>
              <aside
                className={`post-close-review-drawer ${afterCloseStatusTone(afterCloseStatus?.status)}`}
                role="dialog"
                aria-modal="true"
                aria-label="收盘复盘"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="post-close-review-drawer-head">
                  <div>
                    <span>收盘复盘</span>
                    <strong>{mechanicalReview?.found ? mechanicalReview.title : "暂无收盘总体复盘"}</strong>
                    <small>
                      {mechanicalReview?.found
                        ? `报告 ${mechanicalReview.report_date ?? "-"} / 数据 ${objectText(reviewDisplayMarketSummary, ["trade_date"])}`
                        : "收盘后会展示大盘、板块和候选回看"}
                    </small>
                  </div>
                  <div className="post-close-review-actions">
                    <button
                      type="button"
                      onClick={() => {
                        loadMechanicalReview();
                        loadAfterCloseStatus(marketOverview?.trade_date);
                      }}
                      aria-label="刷新收盘复盘"
                    >
                      <RefreshCw size={14} />
                    </button>
                    <button
                      type="button"
                      onClick={() => setPostCloseDrawerOpen(false)}
                      aria-label="关闭收盘复盘"
                    >
                      <X size={15} />
                    </button>
                  </div>
                </div>
                {afterCloseStatus || afterCloseStatusError ? (
                  <div className={`after-close-push-status ${afterCloseStatusTone(afterCloseStatus?.status)}`}>
                    <div>
                      <span>6点推送</span>
                      <strong>{afterCloseStatusLabel(afterCloseStatus?.status)}</strong>
                      <small>{uiText(afterCloseStatus?.message ?? afterCloseStatusError)}</small>
                    </div>
                    {afterCloseStatus ? (
                      <div className="after-close-push-metrics">
                        <span>日期 {afterCloseStatus.trade_date}</span>
                        <span>候选 {afterCloseStatus.candidate_count}</span>
                        <span>计划 {afterCloseStatus.plan_count}</span>
                        <span>候选 Web {afterCloseStatusLabel(afterCloseStatus.candidate_web_status)}</span>
                        <span>复盘 {afterCloseStatusLabel(afterCloseStatus.review_status)}</span>
                        <span>钉钉 {afterCloseStatusLabel(afterCloseStatus.dingtalk_status)}</span>
                        <span>{afterCloseDingText(afterCloseStatus)}</span>
                        <span>调度健康 {String(afterCloseStatus.scheduler_health?.state ?? "正常") === "failed" ? "需人工处理" : String(afterCloseStatus.scheduler_health?.state ?? "正常") === "completed" ? "正常" : "恢复中"}</span>
                        <span>{uiText(afterCloseStatus.market_summary ?? "市场未记录")}</span>
                        <span>Tushare证据</span>
                        {(afterCloseStatus.tushare_evidence_health?.datasets ?? []).map((dataset) => {
                          const label = {
                            moneyflow_dc: "东财资金流",
                            cyq_perf: "筹码分布",
                            limit_list_d: "涨跌停事件",
                          }[dataset.name] ?? dataset.name;
                          const detail = dataset.name === "limit_list_d"
                            ? `事件 ${dataset.rows}`
                            : `覆盖 ${dataset.coverage_ratio === null ? "-" : `${Math.round(dataset.coverage_ratio * 100)}%`}`;
                          return <span key={dataset.name}>{label} {detail} / {dataset.status}</span>;
                        })}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {mechanicalReview?.found ? (
                  <>
                    <div className="post-close-review-board">
                      <section className="post-close-review-column market">
                        <div className="post-close-review-column-head">
                          <span>大盘</span>
                          <strong className={reviewBreadthTone(reviewUpRatio)}>
                            {objectNumber(reviewDisplayMarketSummary, ["up_count"]) ?? "-"}涨{" "}
                            {objectNumber(reviewDisplayMarketSummary, ["down_count"]) ?? "-"}跌
                          </strong>
                        </div>
                        <div className="post-close-review-meter">
                          <span style={{ width: `${Math.max(3, (reviewUpRatio ?? 0) * 100)}%` }} />
                        </div>
                        <div className="post-close-review-facts">
                          <span>上涨占比 {ratioPct(reviewUpRatio)}</span>
                          <span>平均涨跌 {pct(objectNumber(reviewDisplayMarketSummary, ["avg_change_pct"]))}</span>
                          <span>成交变化 {pct(reviewAmountChange)}</span>
                          <span>成交额 {amountText(objectNumber(reviewDisplayMarketSummary, ["total_amount"]))}</span>
                        </div>
                        <div className="post-close-review-index">
                          <b>{objectText(reviewIndexes[0] ?? {}, ["name"])}</b>
                          <strong className={(objectNumber(reviewIndexes[0] ?? {}, ["change_pct"]) ?? 0) >= 0 ? "up" : "down"}>
                            {pct(objectNumber(reviewIndexes[0] ?? {}, ["change_pct"]))}
                          </strong>
                          <small>{objectText(reviewIndexes[0] ?? {}, ["trade_date"])}</small>
                        </div>
                      </section>

                      <section className="post-close-review-column sectors">
                        <div className="post-close-review-column-head">
                          <span>板块</span>
                          <strong>强弱分层</strong>
                        </div>
                        <div className="post-close-sector-bars">
                          {reviewStrongSectors.slice(0, 3).map((item) => (
                            <div className="post-close-sector-bar up" key={`strong-${objectText(item, ["sector"])}`}>
                              <div>
                                <b>{objectText(item, ["sector", "sector_name"])}</b>
                                <small>均涨 {pct(objectNumber(item, ["avg_change_pct"]))} / 上涨 {ratioPct(objectNumber(item, ["up_ratio"]))}</small>
                              </div>
                              <span><i style={{ width: `${reviewSectorBarWidth(item)}%` }} /></span>
                            </div>
                          ))}
                          {reviewWeakSectors.slice(0, 3).map((item) => (
                            <div className="post-close-sector-bar down" key={`weak-${objectText(item, ["sector"])}`}>
                              <div>
                                <b>{objectText(item, ["sector", "sector_name"])}</b>
                                <small>均涨 {pct(objectNumber(item, ["avg_change_pct"]))} / 上涨 {ratioPct(objectNumber(item, ["up_ratio"]))}</small>
                              </div>
                              <span><i style={{ width: `${reviewSectorBarWidth(item)}%` }} /></span>
                            </div>
                          ))}
                          {!reviewStrongSectors.length && !reviewWeakSectors.length ? (
                            <div className="post-close-review-empty">暂无板块强弱样本</div>
                          ) : null}
                        </div>
                      </section>

                      <section className="post-close-review-column candidates">
                        <div className="post-close-review-column-head">
                          <span>候选</span>
                          <strong>{candidateCount} 只</strong>
                        </div>
                        <div className="post-close-candidate-grid">
                          <div>
                            <span>今日可买</span>
                            <strong>{tradableCount}</strong>
                          </div>
                          <div>
                            <span>当前持仓</span>
                            <strong>{openTradeCount}</strong>
                          </div>
                          <div>
                            <span>6点候选</span>
                            <strong>{afterCloseStatus?.candidate_count ?? "-"}</strong>
                          </div>
                          <div>
                            <span>交易计划</span>
                            <strong>{afterCloseStatus?.plan_count ?? "-"}</strong>
                          </div>
                        </div>
                        <div className={`post-close-review-card ${reviewHealthTone(reviewHealthStatus)}`}>
                          <span>数据健康</span>
                          <strong>{reviewHealthLabel(reviewHealthStatus)}</strong>
                          <small>
                            日线 {objectNumber(reviewDataHealth ?? {}, ["daily_bar_count"]) ?? "-"} / 特征{" "}
                            {objectNumber(reviewDataHealth ?? {}, ["feature_count"]) ?? "-"}
                          </small>
                        </div>
                        <p>{uiText(afterCloseStatus?.market_summary ?? "盘后总结未记录市场结论")}</p>
                      </section>
                    </div>
                    {mechanicalReview.content_md ? (
                      <details className="post-close-review-details">
                        <summary>查看完整收盘复盘</summary>
                        <pre>{mechanicalReview.content_md}</pre>
                      </details>
                    ) : null}
                  </>
                ) : (
                  <div className="empty compact">暂无收盘复盘报告，收盘任务完成后会自动出现在这里。</div>
                )}
              </aside>
            </div>
          ) : null}

          <section className="workspace-layout">
        <div className="stock-list-panel">
          <div className="list-toolbar">
            <div className="toolbar-controls">
              <div className="search-box">
                <Search size={16} />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="搜索股票、名称、行业"
                />
              </div>
              <div className="source-tabs stock-view-tabs" data-testid="stock-view-tabs">
                {(Object.keys(stockViewLabels) as StockView[]).map((view) => (
                  <button
                    className={stockView === view ? "active" : ""}
                    data-testid={stockViewTestIds[view]}
                    key={view}
                    type="button"
                    onClick={() => setStockView(view)}
                  >
                    {stockViewLabels[view]}
                  </button>
                ))}
              </div>
              <div className="source-tabs sort-tabs" data-testid="stock-sort-tabs">
                <button
                  className={stockSortMode === "priority" ? "active" : ""}
                  data-testid="stock-sort-priority"
                  type="button"
                  onClick={() => setStockSortMode("priority")}
                >
                  <ArrowUpDown size={14} />
                  {stockSortLabels.priority}
                </button>
                <button
                  className={stockSortMode === "day_return" ? "active" : ""}
                  data-testid="stock-sort-day-return"
                  type="button"
                  onClick={() => setStockSortMode("day_return")}
                >
                  <TrendingUp size={14} />
                  {stockSortLabels.day_return}
                </button>
              </div>
              <label className="board-toggle">
                <input
                  type="checkbox"
                  checked={includeGrowthBoard}
                  onChange={(event) => setIncludeGrowthBoard(event.target.checked)}
                />
                <span>
                  <Filter size={14} />
                  创业板/扩展池
                </span>
              </label>
            </div>
          </div>

          <div className="manual-add-row">
            <input
              value={manualSymbol}
              onChange={(event) => setManualSymbol(event.target.value)}
              placeholder="股票代码"
            />
            <input
              value={manualNote}
              onChange={(event) => setManualNote(event.target.value)}
              placeholder="关注备注"
            />
            <button type="button" onClick={addManualFocus} disabled={manualAdding}>
              {manualAdding ? "加入中" : "加入关注"}
            </button>
          </div>
          {manualError ? <div className="manual-add-error">{manualError}</div> : null}
          {manualRefreshInfo ? (
            <div className={`manual-refresh-note ${manualRefreshInfo.warnings.length ? "warn" : "ok"}`}>
              <strong>
                {manualRefreshInfo.symbol} 已刷新 {manualRefreshInfo.feature_date ?? "-"}
              </strong>
              <small>
                证券 {manualRefreshInfo.security_rows} / 日线 {manualRefreshInfo.daily_rows} /
                特征 {manualRefreshInfo.feature_rows} / 正式 {manualRefreshInfo.formal_plan_rows} /
                观察 {manualRefreshInfo.watch_plan_rows}
              </small>
              {manualRefreshInfo.warnings.length ? <p>{manualRefreshInfo.warnings.join("；")}</p> : null}
            </div>
          ) : null}

          <div className="stock-table">
            <div className="stock-table-head">
              <span>股票</span>
              <span>状态</span>
              <span>近期表现</span>
              <span>计划 / 持仓</span>
            </div>
            {loading ? <div className="empty">加载中</div> : null}
            {!loading && !filteredStocks.length ? (
              <div className="empty">暂无{stockViewLabels[stockView]}股票</div>
            ) : null}
            {!loading && filteredStocks.length && stockView === "candidate"
              ? (
                  <>
                    {candidateGate ? (
                      <div className="candidate-gate-summary">
                        <div>
                          <span>今日策略门控</span>
                          <strong>{candidateGate.title}</strong>
                          <p>{uiText(candidateGate.reason)}</p>
                        </div>
                        <div className="candidate-gate-grid">
                          <small>{uiText(candidateGate.postureText)}</small>
                          <small>{uiText(candidateGate.coreLimitText)}</small>
                          <small>{uiText(candidateGate.dingPolicyText)}</small>
                          <small>{uiText(candidateGate.mainLineText)}</small>
                          <small>{uiText(candidateGate.supportLineText)}</small>
                          {candidateGate.styleGateText ? <small>{uiText(candidateGate.styleGateText)}</small> : null}
                        </div>
                      </div>
                    ) : null}
                    {startupTracking.length ? (
                      <div className="startup-tracking-strip">
                        <strong>启动追踪</strong>
                        {startupTracking.map((item) => (
                          <div className="startup-tracking-row" key={item.symbol}>
                            <b className={item.signal_type}>{item.signal_label === "启动观察" ? "启动观察" : "启动确认"}</b>
                            <span>{item.symbol} / {item.signal_date ?? "数据待补"}</span>
                            <span>历史验证 5/10/20日平均收益 {Object.values(item.historical).map((metric) => metric.raw_return === null ? "样本不足" : `${(metric.raw_return * 100).toFixed(1)}%`).join(" / ")}</span>
                            <span>当前跟踪 {item.current_tracking.realised_return === null ? "进行中" : `${(item.current_tracking.realised_return * 100).toFixed(1)}%`} / {Object.values(item.current_tracking.horizons).every((value) => value === "completed") ? "已完成" : "进行中"}</span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {candidateBlockReason && !candidateTierGroups.coreAction.length ? (
                      <div className="candidate-block-reason">{uiText(candidateBlockReason)}</div>
                    ) : null}
                    {candidateTierSections.map((section) => (
                      <div className="candidate-tier-section" key={section.key}>
                        <div className="candidate-tier-header">
                          <span>
                            <strong>{section.title}</strong>
                            <small>{section.hint}</small>
                          </span>
                          <b>{section.stocks.length}</b>
                        </div>
                        {section.stocks.length ? (
                          section.stocks.map(renderStockRow)
                        ) : (
                          <div className="candidate-tier-empty">暂无{section.title}股票</div>
                        )}
                      </div>
                    ))}
                  </>
                )
              : filteredStocks.map(renderStockRow)}
          </div>
        </div>

        <aside className="stock-detail-panel">
          {selected ? (
            <>
              <div className="stock-title">
                <div>
                  <span>{stockSourceLabel(selected)}</span>
                  <h2>{selected.symbol} {selected.name ?? ""}</h2>
                  <p>{selected.industry ?? "暂无行业"} / {styleLabelForValue(selected.sector_style)}</p>
                </div>
                <div className="latest-price">
                  <span>当前价</span>
                  <strong>{price(displayPrice(selected))}</strong>
                  <small>今日 {pct(selected.day_change_pct)}</small>
                </div>
              </div>

              <section className={`decision-card ${decisionClass(selected)}`}>
                <div>
                  <span>当前判断</span>
                  <strong>{decisionTitle(selected)}</strong>
                </div>
                <p>{selectedTrade?.status === "open" ? "已买入，重点看止损、止盈和浮盈回撤。" : selectedPlan?.execution_note ?? "暂无触发条件。"}</p>
                <div className="decision-reasons">
                  {selectedDecisionReasons.map((reason) => (
                    <span key={reason}>{reason}</span>
                  ))}
                </div>
              </section>

              {selected.manual_note || selected.manual_tags.length ? (
                <section className={`watch-note ${isNextSessionCandidate(selected) ? "candidate" : ""}`}>
                  <div>
                    <span>关注理由</span>
                    <strong>{stockSourceLabel(selected)}</strong>
                  </div>
                  {selected.manual_note ? <p>{uiText(selected.manual_note)}</p> : null}
                  {candidatePoolText(selected) ? <p>{candidatePoolText(selected)}</p> : null}
                  {candidateStrategyText(selected) ? <p>{candidateStrategyText(selected)}</p> : null}
                  {candidateHorizonText(selected) ? <p>{candidateHorizonText(selected)}</p> : null}
                  {startupSignalText(selected) ? <p>{startupSignalText(selected)}</p> : null}
                  {selected.startup_signal_reasons.map((reason) => (
                    <p key={reason}>{uiText(reason)}</p>
                  ))}
                  {selected.manual_tags.length ? (
                    <div className="tag-row">
                      {selected.manual_tags.map((tag) => (
                        <span key={tag}>{manualTagText(tag, selected)}</span>
                      ))}
                    </div>
                  ) : null}
                </section>
              ) : null}

              <div className="return-cards">
                <div>
                  <span>今日涨幅</span>
                  <strong className={(selected.day_change_pct ?? 0) >= 0 ? "up" : "down"}>
                    {pct(selected.day_change_pct)}
                  </strong>
                </div>
                <div>
                  <span>5日表现</span>
                  <strong className={(selected.return_5d ?? 0) >= 0 ? "up" : "down"}>{pct(selected.return_5d)}</strong>
                </div>
                <div>
                  <span>20日表现</span>
                  <strong className={(selected.return_20d ?? 0) >= 0 ? "up" : "down"}>{pct(selected.return_20d)}</strong>
                </div>
              </div>

              <section className="detail-section">
                <div className="section-title with-action">
                  <div>
                    <ClipboardList size={16} />
                    <h3>实盘模拟交易</h3>
                  </div>
                  {selected.recent_paper_trades.length ? (
                    <button type="button" onClick={() => setTradeDialogOpen(true)}>
                      历史记录
                    </button>
                  ) : null}
                </div>
                {selectedTrade ? (
                  <div className="active-trade-card">
                    <div className="active-trade-head">
                      <div>
                        <span>{selectedTrade.status === "open" ? "当前持仓" : "最近一笔"}</span>
                        <strong>
                          {selectedTrade.rule_id} / {tradeStatusText(selectedTrade.status)}
                        </strong>
                      </div>
                      <strong className={(selectedTradeReturn ?? 0) >= 0 ? "up" : "down"}>
                        {pct(selectedTradeReturn)}
                      </strong>
                    </div>
                    <div className="trade-metric-grid">
                      <div>
                        <span>买入</span>
                        <strong>{price(selectedTrade.entry_price)}</strong>
                        <small>{selectedTrade.entry_date}</small>
                      </div>
                      <div>
                        <span>{selectedTrade.status === "open" ? "实时价" : "卖出"}</span>
                        <strong>{price(selectedTrade.status === "open" ? selectedTrade.current_price : selectedTrade.exit_price)}</strong>
                        <small>{selectedTrade.status === "open" ? selectedTrade.quote_time ?? "-" : selectedTrade.exit_date ?? "-"}</small>
                      </div>
                      <div>
                        <span>今日涨幅</span>
                        <strong className={(selected.day_change_pct ?? 0) >= 0 ? "up" : "down"}>
                          {pct(selected.day_change_pct)}
                        </strong>
                        <small>{selected.quote_time ?? selected.latest_trade_date ?? "-"}</small>
                      </div>
                      <div>
                        <span>止损</span>
                        <strong>{price(selectedTrade.current_stop)}</strong>
                        <small>止盈 {price(selectedTrade.take_profit_1)}</small>
                      </div>
                      <div>
                        <span>顶峰</span>
                        <strong>{pct(selectedTrade.mfe_pct)}</strong>
                        <small>最大浮亏 {pct(selectedTrade.mae_pct)}</small>
                      </div>
                      <div>
                        <span>最高 / 最低</span>
                        <strong>{price(selectedTrade.highest_price)}</strong>
                        <small>{price(selectedTrade.lowest_price)}</small>
                      </div>
                      <div>
                        <span>胜率 / 已平</span>
                        <strong>{pct(paperWinRate(selected))}</strong>
                        <small>{paperClosedCount(selected)} 笔</small>
                      </div>
                    </div>
                    <p className="trade-note-line">
                      数量 {selectedTrade.quantity} / 持有 {selectedTrade.holding_days}天 /
                      退出原因 {exitReasonText(selectedTrade.exit_reason)}
                    </p>
                  </div>
                ) : (
                  <div className="empty compact">暂无实盘模拟交易，等系统按策略生成并触发买入后会自动出现在这里。</div>
                )}
              </section>

              <section className="detail-section">
                <div className="section-title">
                  <ClipboardList size={16} />
                  <h3>当前交易计划</h3>
                </div>
                {selected.plans.length ? (
                  selected.plans.map((plan) => (
                    <div className="plan-card" key={plan.id}>
                      <div>
                        <strong>{plan.rule_id} / {strategyText(plan.strategy_type)}</strong>
                        <span>
                          计划交易日 {plan.trade_date} / {plan.execution_label} /
                          {planStatusText(plan.status)} / 置信分 {price(plan.confidence_score)}
                        </span>
                      </div>
                      <p>触发价 {price(plan.entry_trigger_price)} / {riskText(plan)}</p>
                      <p className={plan.can_buy_now ? "execution-note tradable" : "execution-note blocked"}>
                        {plan.execution_note}
                      </p>
                      {plan.evidence.length ? (
                        <div className="evidence-grid">
                          {plan.evidence.map((item) => (
                            <div className={`evidence-item ${item.verdict}`} key={`${item.category}-${item.label}`}>
                              <span>{item.category}</span>
                              <strong>{item.label}: {item.value}</strong>
                              <small>{item.note}</small>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className="empty compact">暂无当前交易计划。</div>
                )}
              </section>

              <section className="detail-section">
                <div className="section-title">
                  <ClipboardList size={16} />
                  <h3>策略适配</h3>
                </div>
                {strategyFitError ? (
                  <div className="empty compact">策略适配暂时不可用。</div>
                ) : selectedPlanFitRows.length ? (
                  <div className="strategy-fit-list">
                    {selectedPlanFitRows.map(({ plan, overall, sector, symbol }) => (
                      <div className="strategy-fit-card" key={`${plan.id}-${plan.rule_id}`}>
                        <div className="strategy-fit-head">
                          <div>
                            <span>回归日期 {strategyFit?.report_date ?? "-"}</span>
                            <strong>{plan.rule_id} / {strategyText(plan.strategy_type)}</strong>
                          </div>
                          <span className={`fit-pill ${sector?.fit_status ?? overall?.fit_status ?? "neutral"}`}>
                            {fitStatusText(sector?.fit_status ?? overall?.fit_status)}
                          </span>
                        </div>
                        <div className="fit-metric-grid">
                          {[overall, sector, symbol].map((metric, index) => (
                            <div
                              className={`fit-metric ${metric?.fit_status ?? "missing"}`}
                              key={`${plan.id}-${index}`}
                            >
                              <span>{index === 0 ? "整体" : index === 1 ? "板块" : "个股"}</span>
                              <strong>
                                {metric ? `${fitStatusText(metric.fit_status)} / ${metric.trade_count}笔` : "暂无"}
                              </strong>
                              <small>
                                胜率 {pct(metric?.win_rate)} / 平均 {pct(metric?.avg_return)}
                              </small>
                              <small>{validationLine(metric)}</small>
                            </div>
                          ))}
                        </div>
                        <p className="fit-reason">{metricReason(sector ?? symbol ?? overall)}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty compact">暂无可匹配的策略回归记录。</div>
                )}
              </section>

              <section className="chart-panel in-detail">
                <div className="panel-head">
                  <div>
                    <span>策略证据图</span>
                    <h3>{selected.symbol} 日K与均线</h3>
                  </div>
                  <span>{candles.length} 根K线</span>
                </div>
                <StrategyEvidenceChart candles={candles} recommendation={null} />
              </section>

              <section className="detail-section">
                <div className="section-title">
                  <ClipboardList size={16} />
                  <h3>复盘总结</h3>
                </div>
                {selected ? (
                  <>
                    <div className="review-summary-block">
                      {selectedStockReviewItems.map((item) => (
                        <div className={`review-summary-panel ${item.tone ?? "neutral"}`} key={item.title}>
                          <span>{item.title}</span>
                          <ul>
                            {item.lines.map((line) => (
                              <li key={line}>{line}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="empty compact">请选择一只股票查看复盘。</div>
                )}
              </section>
            </>
          ) : (
            <div className="empty">选择一只股票查看详情</div>
          )}
        </aside>
      </section>
        </>
      ) : null}

      {activePage === "tracking" ? (
        <section className="page-panel tracking-workspace-panel">
          <div className="panel-head">
            <div>
              <span>个股追踪</span>
              <h3>中长期生命周期档案</h3>
            </div>
            <span>
              {marketOverview?.trade_date ? `交易日 ${marketOverview.trade_date}` : "暂无交易日"}
              {lastRefreshedAt ? ` / 更新 ${timeText(lastRefreshedAt)}` : ""}
            </span>
          </div>

          <div className="tracking-summary-grid">
            <div>
              <span>趋势持有</span>
              <strong>{trackingHoldingCount}</strong>
              <small>继续看主线和承接</small>
            </div>
            <div>
              <span>启动确认</span>
              <strong>{trackingStartupCount}</strong>
              <small>等板块、趋势、量能同向</small>
            </div>
            <div>
              <span>风险复核</span>
              <strong>{trackingRiskCount}</strong>
              <small>只做复盘样本</small>
            </div>
            <div>
              <span>平均追踪分</span>
              <strong>{trackingAverageScore === null ? "-" : trackingAverageScore.toFixed(1)}</strong>
              <small>透明规则，不做黑箱预测</small>
            </div>
          </div>

          {trackingSignalSummary ? (
            <div className="tracking-signal-summary">
              <div className="tracking-signal-summary-head">
                <div>
                  <span>信号汇总</span>
                  <strong>
                    {trackingSignalSummary.aligned_count}/{trackingSignalSummary.symbol_count}
                  </strong>
                  <small>分价同向 / 已有快照股票</small>
                </div>
                <div>
                  <span>背离</span>
                  <strong>{trackingSignalSummary.divergent_count}</strong>
                  <small>优先复核分涨价弱</small>
                </div>
                <div>
                  <span>样本不足</span>
                  <strong>{trackingSignalSummary.insufficient_count}</strong>
                  <small>继续等收盘快照</small>
                </div>
                <div>
                  <span>数据成熟度</span>
                  <strong>{trackingSignalSummary.maturity_label}</strong>
                  <small>{trackingSignalSummary.maturity_note}</small>
                </div>
              </div>
              {trackingSignalSummary.sectors.length ? (
                <div className="tracking-sector-samples">
                  <div className="tracking-sector-title">
                    <span>板块验证</span>
                    <small>先看板块，再看个股</small>
                  </div>
                  {trackingSignalSummary.sectors.slice(0, 4).map((sector) => (
                    <span key={sector.industry}>
                      <b>{sector.industry}</b>
                      <em>{sector.signal_label}</em>
                      <small>
                        成熟 {sector.mature_count}/{sector.symbol_count}
                        {" / "}
                        背离 {sector.divergent_count}
                      </small>
                      <small>
                        分 {sector.avg_score_delta === null
                          ? "-"
                          : `${sector.avg_score_delta >= 0 ? "+" : ""}${sector.avg_score_delta.toFixed(1)}`}
                        {" / "}
                        价 {pctPoint(sector.avg_simple_return_pct)}
                      </small>
                    </span>
                  ))}
                </div>
              ) : null}
              {trackingSignalSummary.items.length ? (
                <div className="tracking-signal-samples">
                  {trackingSignalSummary.items.slice(0, 4).map((item) => (
                    <span className={item.signal_alignment_tone} key={item.symbol}>
                      <b>{item.symbol} {item.name ?? ""}</b>
                      <em>{item.signal_alignment_label}</em>
                      <small>
                        分{" "}
                        {item.score_delta === null
                          ? "-"
                          : `${item.score_delta >= 0 ? "+" : ""}${item.score_delta.toFixed(1)}`}
                        {" / "}
                        价 {pctPoint(item.simple_return_pct)}
                      </small>
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          <div className="tracking-workspace">
            <div className="tracking-list">
              <div className="tracking-list-head">
                <span>股票</span>
                <span>阶段</span>
                <span>验证</span>
              </div>
              {loading && !trackingProfiles.length ? <div className="empty">加载中</div> : null}
              {!loading && !trackingProfiles.length ? (
                <div className="empty">暂无可追踪股票</div>
              ) : null}
              {trackingProfiles.map(renderTrackingRow)}
            </div>

            <aside className="tracking-detail">
              {selectedTrackingProfile ? (
                <>
                  <div className={`tracking-hero ${selectedTrackingProfile.stage} ${selectedTrackingState.key}`}>
                    <div>
                      <span>{selectedTrackingState.label}</span>
                      <h3>{selectedTrackingProfile.symbol} {selectedTrackingProfile.name ?? ""}</h3>
                      <p>
                        {selectedTrackingProfile.industry ?? "暂无行业"} / {selectedStartupPhase.label}
                        {" "} / 追踪分 {selectedTrackingProfile.score.toFixed(1)}
                      </p>
                    </div>
                    <strong className={selectedTrackingProfile.scoreTone}>
                      {selectedTrackingProfile.score.toFixed(1)}
                    </strong>
                  </div>

                  <div className="tracking-state-grid">
                    <section className={`tracking-state-card ${selectedTrackingState.key}`}>
                      <span>追踪状态</span>
                      <strong>{selectedTrackingState.label}</strong>
                      <small>{selectedTrackingState.reason}</small>
                    </section>
                    <section className={`tracking-state-card ${selectedStartupPhase.key}`}>
                      <span>启动阶段</span>
                      <strong>{selectedStartupPhase.label}</strong>
                      <small>{selectedStartupPhase.reason}</small>
                    </section>
                  </div>

                  <section className={`tracking-decision-card ${selectedTrackingDecision?.tone ?? selectedTrackingProfile.decision.tone}`}>
                    <div className="tracking-decision-head">
                      <span>追踪结论</span>
                      <strong>{selectedTrackingDecision?.verdictLabel ?? selectedTrackingProfile.decision.verdictLabel}</strong>
                    </div>
                    <div className="tracking-decision-columns">
                      <div>
                        <span>主要理由</span>
                        <ul>
                          {(selectedTrackingDecision?.primaryReasons ?? selectedTrackingProfile.decision.primaryReasons).map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                      <div>
                        <span>降级原因</span>
                        <ul>
                          {(selectedTrackingDecision?.downgradeReasons ?? selectedTrackingProfile.decision.downgradeReasons).map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                      <div>
                        <span>升级条件</span>
                        <ul>
                          {(selectedTrackingDecision?.upgradeConditions ?? selectedTrackingProfile.decision.upgradeConditions).map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  </section>

                  <div className="tracking-metric-grid">
                    {selectedTrackingProfile.metrics.map((metric) => (
                      <div className={`tracking-metric ${metric.tone}`} key={metric.label}>
                        <span>{metric.label}</span>
                        <strong>{metric.value}</strong>
                      </div>
                    ))}
                  </div>

                  <section className="tracking-history-panel">
                    <div className="tracking-history-head">
                      <div>
                        <span>追踪分变化</span>
                        <strong>
                          {trackingHistoryLatest?.tracking_score?.toFixed(1)
                            ?? selectedTrackingProfile.score.toFixed(1)}
                        </strong>
                        <small>
                          {trackingHistoryLatest
                            ? `${trackingHistoryLatest.snapshot_date} / 较前次 ${trackingScoreDeltaText(
                              trackingHistoryLatest,
                              trackingHistoryPrevious,
                            )} / ${trackingHistoryLatest.tracking_state_label}`
                            : "暂无历史快照，先生成今日快照"}
                        </small>
                      </div>
                      <button
                        type="button"
                        onClick={generateTrackingSnapshot}
                        disabled={trackingSnapshotCreating}
                      >
                        <RefreshCw size={14} />
                        {trackingSnapshotCreating ? "生成中" : "生成今日快照"}
                      </button>
                    </div>
                    {trackingHistoryError ? (
                      <small className="tracking-history-error">{uiText(trackingHistoryError)}</small>
                    ) : null}
                    {trackingHistoryLoading ? <div className="empty compact">追踪历史加载中</div> : null}
                    {!trackingHistoryLoading && trackingHistoryOldestFirst.length ? (
                      <>
                        <div className="tracking-history-summary-grid">
                          {trackingHistorySummary.map((item) => (
                            <div className={`tracking-history-summary ${item.tone}`} key={item.horizon}>
                              <span>{item.label}</span>
                              <strong>
                                {item.delta === null ? "-" : `${item.delta >= 0 ? "+" : ""}${item.delta.toFixed(1)}`}
                              </strong>
                              <small>{item.summary}</small>
                            </div>
                          ))}
                        </div>
                        <div className={`tracking-path-chart ${trackingPathSummary.tone}`}>
                          <div className="tracking-path-chart-head">
                            <div>
                              <span>追踪路径</span>
                              <strong>{trackingPathSummary.verdictLabel}</strong>
                            </div>
                            <small>{trackingPathSummary.insight}</small>
                          </div>
                          {trackingPathSummary.points.length >= 2 ? (
                            <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="追踪分路径">
                              <polyline points={trackingPathSummary.pointString} />
                              {trackingPathSummary.points.map((point) => (
                                <circle
                                  className={point.tone}
                                  cx={point.x}
                                  cy={point.y}
                                  key={`${point.date}-${point.score}`}
                                  r="2.8"
                                />
                              ))}
                            </svg>
                          ) : (
                            <div className="empty compact">快照不足，生成两次后显示路径</div>
                          )}
                          <div className="tracking-path-stats">
                            <span>
                              <small>窗口高点</small>
                              <strong>
                                {trackingPathSummary.highScore === null ? "-" : trackingPathSummary.highScore.toFixed(1)}
                              </strong>
                            </span>
                            <span>
                              <small>最大回落</small>
                              <strong>
                                {trackingPathSummary.maxDrawdown === null
                                  ? "-"
                                  : trackingPathSummary.maxDrawdown.toFixed(1)}
                              </strong>
                            </span>
                            <span>
                              <small>阶段切换</small>
                              <strong>{trackingPathSummary.stageChangeCount}</strong>
                            </span>
                            <span className={trackingPathSummary.outcomeTone}>
                              <small>跟踪收益</small>
                              <strong>{pctPoint(trackingPathSummary.simpleReturnPct)}</strong>
                            </span>
                            <span>
                              <small>价格回撤</small>
                              <strong>
                                {trackingPathSummary.maxPriceDrawdownPct === null
                                  ? "-"
                                  : `${trackingPathSummary.maxPriceDrawdownPct.toFixed(1)}%`}
                              </strong>
                            </span>
                            <span>
                              <small>价格样本</small>
                              <strong>{trackingPathSummary.priceSampleCount}</strong>
                            </span>
                          </div>
                          <div className={`tracking-signal-check ${trackingPathSummary.signalAlignmentTone}`}>
                            <span>信号验证</span>
                            <strong>{trackingPathSummary.signalAlignmentLabel}</strong>
                            <small>{trackingPathSummary.signalAlignmentText}</small>
                          </div>
                        </div>
                        <div className="tracking-history-bars">
                          {trackingHistoryOldestFirst.slice(-18).map((item) => (
                            <div
                              className={`tracking-history-row ${trackingSnapshotTone(item)}`}
                              key={`${item.symbol}-${item.snapshot_date}`}
                            >
                              <span>{item.snapshot_date.slice(5)}</span>
                              <b>
                                <i style={{ width: `${trackingHistoryBarWidth(item.tracking_score)}%` }} />
                              </b>
                              <strong>
                                {item.tracking_score === null ? "-" : item.tracking_score.toFixed(1)}
                              </strong>
                              <small>{item.tracking_state_label}</small>
                            </div>
                          ))}
                        </div>
                      </>
                    ) : null}
                    {!trackingHistoryLoading && !trackingHistoryOldestFirst.length ? (
                      <div className="empty compact">还没有真实追踪快照</div>
                    ) : null}
                  </section>

                  <section className={`tracking-candle-path ${selectedCandleTrendPath.tone}`}>
                    <div className="section-title">
                      <ClipboardList size={16} />
                      <h3>K线趋势路径</h3>
                    </div>
                    <div className="tracking-candle-path-head">
                      <strong>{selectedCandleTrendPath.verdictLabel}</strong>
                      <span>{candles.length ? `${candles.length} 根K线` : "暂无K线"}</span>
                    </div>
                    <div className="tracking-candle-metrics">
                      {selectedCandleTrendPath.metrics.map((metric) => (
                        <span className={metric.tone} key={metric.label}>
                          <b>{metric.label}</b>
                          {metric.value}
                        </span>
                      ))}
                    </div>
                    <div className="tracking-candle-path-body">
                      <ul>
                        {selectedCandleTrendPath.points.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                      <ul>
                        {selectedCandleTrendPath.risks.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  </section>

                  <div className="tracking-two-column">
                    <section>
                      <div className="section-title">
                        <ClipboardList size={16} />
                        <h3>继续跟踪的证据</h3>
                      </div>
                      <ul>
                        {selectedTrackingProfile.evidence.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </section>
                    <section>
                      <div className="section-title">
                        <ClipboardList size={16} />
                        <h3>风险和降级条件</h3>
                      </div>
                      <ul>
                        {selectedTrackingProfile.risks.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </section>
                  </div>

                  <section className="tracking-action">
                    <span>下一步</span>
                    <strong>{selectedTrackingProfile.nextAction}</strong>
                  </section>

                  <div className="tracking-timeline">
                    {selectedTrackingProfile.timeline.map((item) => (
                      <section className={`tracking-timeline-item ${item.tone}`} key={`${item.title}-${item.date ?? "none"}`}>
                        <div>
                          <span>{item.date ?? "-"}</span>
                          <strong>{item.title}</strong>
                        </div>
                        <ul>
                          {item.lines.map((line) => (
                            <li key={line}>{line}</li>
                          ))}
                        </ul>
                      </section>
                    ))}
                  </div>
                </>
              ) : (
                <div className="empty">选择一只股票查看追踪档案</div>
              )}
            </aside>
          </div>
        </section>
      ) : null}

      {activePage === "paper" ? (
        <section className="page-panel paper-workspace-panel">
          <div className="panel-head">
            <div>
              <span>实盘模拟</span>
              <h3>当前持仓和最近交易</h3>
            </div>
            <span>
              {marketOverview?.trade_date ? `交易日 ${marketOverview.trade_date}` : "暂无交易日"}
              {lastRefreshedAt ? ` / 更新 ${timeText(lastRefreshedAt)}` : ""}
            </span>
          </div>

          <div className="paper-summary-grid">
            <div>
              <span>模拟持仓</span>
              <strong>{paperOpenStocks.length}</strong>
              <small>当前仍在跟踪</small>
            </div>
            <div>
              <span>浮动合计</span>
              <strong className={paperFloatingReturn >= 0 ? "up" : "down"}>
                {pct(paperFloatingReturn)}
              </strong>
              <small>不算复利</small>
            </div>
            <div>
              <span>今日结束</span>
              <strong>{paperClosedTodayCount}</strong>
              <small>{marketOverview?.trade_date ?? "-"}</small>
            </div>
            <div>
              <span>最近记录</span>
              <strong>{paperTradeStocks.length}</strong>
              <small>含已结束交易</small>
            </div>
          </div>

          <div className="paper-trade-list">
            <div className="paper-trade-head">
              <span>股票</span>
              <span>模拟状态</span>
              <span>收益</span>
              <span>风控</span>
              <span>动作</span>
            </div>
            {loading ? <div className="empty">加载中</div> : null}
            {!loading && !paperTradeStocks.length ? (
              <div className="empty">暂无实盘模拟记录</div>
            ) : null}
            {!loading ? paperTradeStocks.map(renderPaperTradeRow) : null}
          </div>
        </section>
      ) : null}

      {tradeDialogOpen && selected ? (
        <div className="modal-backdrop" role="presentation">
          <section className="trade-dialog" role="dialog" aria-modal="true" aria-label="实盘模拟交易明细">
            <div className="dialog-head">
              <div>
                <span>{selected.symbol} {selected.name ?? ""}</span>
                <h3>实盘模拟交易明细</h3>
              </div>
              <button type="button" onClick={() => setTradeDialogOpen(false)}>
                关闭
              </button>
            </div>
            <div className="trade-record-list">
              {selected.recent_paper_trades.map((trade) => (
                <div className="trade-record" key={trade.id}>
                  <div>
                    <strong>{trade.rule_id} / {tradeStatusText(trade.status)} / {pct(trade.pnl_pct)}</strong>
                    <span>
                      买入 {trade.entry_date} @ {price(trade.entry_price)}，
                      卖出 {trade.exit_date ?? "未卖出"} @ {price(trade.exit_price)}
                    </span>
                  </div>
                  <p>
                    数量 {trade.quantity} / 持有 {trade.holding_days}天 /
                    最高 {price(trade.highest_price)} / 最低 {price(trade.lowest_price)} /
                    顶峰浮盈 {pct(trade.mfe_pct)} / 最大浮亏 {pct(trade.mae_pct)} /
                    退出原因 {exitReasonText(trade.exit_reason)}
                  </p>
                </div>
              ))}
            </div>
          </section>
        </div>
      ) : null}

      {activePage === "sectors" ? (
        <section className="page-panel">
          <div className="panel-head">
            <div>
              <span>板块主线</span>
              <h3>资金流动和月度排名</h3>
            </div>
            <span>
              {sectorOverview?.feature_trade_date ? `特征 ${sectorOverview.feature_trade_date}` : "暂无特征日"}
              {sectorOverview?.feature_coverage_ratio != null ? ` / 覆盖 ${pct(sectorOverview.feature_coverage_ratio)}` : ""}
              {sectorOverview?.moneyflow_trade_date ? ` / 资金 ${sectorOverview.moneyflow_trade_date}` : ""}
              {sectorOverview?.moneyflow_coverage_ratio != null ? ` / 资金覆盖 ${pct(sectorOverview.moneyflow_coverage_ratio)}` : ""}
              {sectorOverview?.moneyflow_reliability_label ? ` / ${sectorOverview.moneyflow_reliability_label}` : ""}
              {sectorOverview?.sector_gate_summary ? ` / 主线 ${sectorOverview.sector_gate_summary.main_allowed_count}` : ""}
              {sectorOverview?.sector_gate_summary ? ` / 观察 ${sectorOverview.sector_gate_summary.observe_count}` : ""}
              {sectorOverview?.sector_gate_summary ? ` / 降温 ${sectorOverview.sector_gate_summary.cooldown_count}` : ""}
            </span>
          </div>
          <section className="sector-catalyst-panel">
            <div className="snapshot-review-head">
              <strong>确认主线回看</strong>
              <small>只统计 10:30 最终确认；收益按信号日收盘计算。</small>
            </div>
            {confirmedMainlineOutcomes.length ? (
              <div className="sector-catalyst-list">
                {confirmedMainlineOutcomes.slice(0, 6).map((item) => (
                  <div className="sector-catalyst-item" key={`${item.signal_date}-${item.sector}`}>
                    <span>
                      <strong>{item.sector}</strong>
                      <em>{item.leader_symbol}</em>
                    </span>
                    <small>确认 {item.signal_date}</small>
                    <small>
                      {item.horizons
                        .map((horizon) =>
                          horizon.status === "completed"
                            ? `${horizon.horizon}日 ${pct(horizon.return_pct)}`
                            : `${horizon.horizon}日 等待`,
                        )
                        .join(" / ")}
                    </small>
                    {item.candidate_bindings.length ? (
                      <small>
                        候选 {item.candidate_bindings
                          .map((candidate) => {
                            const horizon = candidate.horizons.find((value) => value.horizon === 3);
                            return horizon?.status === "completed"
                              ? `${candidate.symbol} ${pct(horizon.return_pct)}`
                              : `${candidate.symbol} 等待`;
                          })
                          .join(" / ")}
                      </small>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty compact">暂无已成熟的主线效果样本</div>
            )}
          </section>
          {monthlySummary ? (
            <section className="monthly-summary-panel">
              <div className="monthly-summary-head">
                <div>
                  <span>月度交易总结</span>
                  <strong>{monthlySummary.month}</strong>
                </div>
                <div className="review-strip-meta">
                  <span>纸面复盘 {monthlySummary.paper_review_count}</span>
                  <span>回测样本 {monthlySummary.backtest_trade_count}</span>
                  <span>排除噪音 {monthlySummary.excluded_symbols.join("、") || "-"}</span>
                </div>
              </div>
              <div className="monthly-summary-grid">
                <div className="fit-metric">
                  <span>纸面总收益</span>
                  <strong className={monthlySummary.total_pnl >= 0 ? "up" : "down"}>
                    {pct(monthlySummary.total_pnl)}
                  </strong>
                  <small>胜 {monthlySummary.winning_reviews} / 负 {monthlySummary.losing_reviews}</small>
                </div>
                <div className="fit-metric">
                  <span>平均复盘收益</span>
                  <strong className={(monthlySummary.avg_review_return ?? 0) >= 0 ? "up" : "down"}>
                    {pct(monthlySummary.avg_review_return)}
                  </strong>
                  <small>不算复利</small>
                </div>
                <div className="fit-metric">
                  <span>平均回测收益</span>
                  <strong className={(monthlySummary.avg_backtest_return ?? 0) >= 0 ? "up" : "down"}>
                    {pct(monthlySummary.avg_backtest_return)}
                  </strong>
                  <small>用于因子对照</small>
                </div>
              </div>
              <div className="monthly-summary-lists">
                <div>
                  <span>因子观察</span>
                  {(monthlySummary.factor_insights.slice(0, 3)).map((item, index) => (
                    <small key={`factor-${index}`}>{factorInsightLabel(item)}</small>
                  ))}
                </div>
                <div>
                  <span>板块机会</span>
                  {(monthlySummary.sector_opportunities.slice(0, 3)).map((item, index) => (
                    <small key={`sector-${index}`}>{sectorOpportunityLabel(item)}</small>
                  ))}
                </div>
              </div>
              {monthlySummary.content_md ? (
                <details className="monthly-summary-details">
                  <summary>查看完整月度总结</summary>
                  <pre>{monthlySummary.content_md}</pre>
                </details>
              ) : null}
            </section>
          ) : null}
          <section className="monthly-summary-panel">
            <div className="monthly-summary-head">
              <div>
                <span>策略效果 / 长期低维回归</span>
                <strong>
                  {candidateReplayEffect
                    ? `${candidateReplayEffect.start_date} ~ ${candidateReplayEffect.end_date}`
                    : lowDimensionalReplay
                    ? `${lowDimensionalReplay.start_date} ~ ${lowDimensionalReplay.end_date}`
                    : "板块优先 / 每天最多3只"}
                </strong>
              </div>
              <div className="review-strip-meta">
                {lowDimensionalReplay ? (
                  <>
                    <span>交易日 {lowDimensionalReplay.processed_days}</span>
                    <span>样本 {lowDimensionalReplay.candidate_count}</span>
                    <span>异常日 {lowDimensionalReplay.warning_days}</span>
                  </>
                ) : null}
                {candidateReplayCacheText ? (
                  <span>{candidateReplayCacheText}</span>
                ) : null}
                {candidateReplayWindowLabel ? (
                  <span>{candidateReplayWindowLabel}</span>
                ) : null}
                <button
                  className="refresh-button"
                  type="button"
                  onClick={() => loadCandidateReplayEffect()}
                  disabled={candidateReplayEffectLoading}
                >
                  <RefreshCw size={14} />
                  {candidateReplayEffectLoading ? "策略运行中" : "策略效果"}
                </button>
                <button
                  className="refresh-button"
                  type="button"
                  onClick={() => loadCandidateReplayEffect(longCandidateReplayQuery)}
                  disabled={candidateReplayEffectLoading}
                >
                  <RefreshCw size={14} />
                  长周期回放
                </button>
                <button
                  className="refresh-button"
                  type="button"
                  onClick={() => loadLowDimensionalReplay()}
                  disabled={lowDimensionalReplayLoading}
                >
                  <RefreshCw size={14} />
                  {lowDimensionalReplayLoading ? "运行中" : "运行回归"}
                </button>
                <button
                  className="refresh-button"
                  type="button"
                  onClick={() => loadRuleRegressionStatus()}
                  disabled={ruleRegressionStatusLoading}
                >
                  <RefreshCw size={14} />
                  {ruleRegressionStatusLoading ? "刷新中" : "回归状态"}
                </button>
              </div>
            </div>
            {candidateReplayEffectError ? (
              <div className="empty compact">策略效果暂时不可用：{candidateReplayEffectError}</div>
            ) : null}
            {lowDimensionalReplayError ? (
              <div className="empty compact">长期回归暂时不可用：{lowDimensionalReplayError}</div>
            ) : null}
            {ruleRegressionStatus || ruleRegressionStatusError ? (
              <div className={`rule-regression-status ${ruleRegressionStatus?.status ?? "error"}`}>
                <div>
                  <span>规则回归状态</span>
                  <strong>{ruleRegressionStatusLabel(ruleRegressionStatus?.status)}</strong>
                  <small>{uiText(ruleRegressionStatus?.message ?? ruleRegressionStatusError)}</small>
                </div>
                {ruleRegressionStatus ? (
                  <div className="rule-regression-status-metrics">
                    <span>最近日期 {ruleRegressionStatus.latest_run_date ?? "-"}</span>
                    <span>交易样本 {ruleRegressionStatus.latest_trade_count}</span>
                    <span>表现行 {ruleRegressionStatus.latest_performance_rows}</span>
                    <span>
                      队列{" "}
                      {ruleRegressionStatus.active_tasks
                        + ruleRegressionStatus.reserved_tasks
                        + ruleRegressionStatus.scheduled_tasks}
                    </span>
                  </div>
                ) : null}
              </div>
            ) : null}
            {replayDataCoverage ? (
              <div className={`replay-data-coverage ${replayDataCoverage.overall.grade}`}>
                <div>
                  <span>数据覆盖</span>
                  <strong>{replayCoverageGradeLabel(replayDataCoverage.overall.grade)}</strong>
                  <small>{replayCoverageSummary(replayDataCoverage)}</small>
                </div>
                {replayCoverageWarnings.length ? (
                  <div>
                    {replayCoverageWarnings.map((warning) => (
                      <small key={warning}>{warning}</small>
                    ))}
                  </div>
                ) : (
                  <small>当前窗口没有明显覆盖风险，可参与月收益和总收益对比。</small>
                )}
              </div>
            ) : null}
            {candidateReplayEffect ? (
              <>
                <div className="replay-visual-board">
                  <div className="replay-visual-hero">
                    <span>当前姿态</span>
                    <strong>{candidateGate.title}</strong>
                    <small>{uiText(candidateGate.reason)}</small>
                  </div>
                  {visualStrategyLines.length ? (
                    <div className="replay-visual-lines">
                      {visualStrategyLines.map((line) => (
                        <div className={`replay-visual-line ${line.tone}`} key={line.scope}>
                          <div>
                            <span>{line.label}</span>
                            <strong>{pct(line.displayMetric?.total_return)}</strong>
                            <small>
                              均值 {pct(line.displayMetric?.avg_return)} / 样本{" "}
                              {line.displayMetric?.sample_count ?? 0}
                            </small>
                          </div>
                          <div className="replay-visual-bar">
                            <span style={{ width: `${replayBarWidth(line.displayMetric?.total_return)}%` }} />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {mainLineMonthlyPerformance.length ? (
                    <div className="replay-monthly-performance">
                      <div className="replay-monthly-performance-head">
                        <span>固定主线月度表现</span>
                        <strong>{mainLineMonthlyPerformance[0].label}</strong>
                        <small>20日 / 简单相加 / 不复利</small>
                      </div>
                      <div className={`replay-monthly-health ${mainLineMonthlyHealth.status}`}>
                        <div>
                          <span>策略健康</span>
                          <strong>{mainLineMonthlyHealth.statusLabel}</strong>
                          <small>
                            正收益月份 {mainLineMonthlyHealth.positiveMonths}/{mainLineMonthlyHealth.monthCount}
                          </small>
                        </div>
                        <div>
                          <span>总收益</span>
                          <strong>{pct(mainLineMonthlyHealth.totalReturn)}</strong>
                        </div>
                        <div>
                          <span>最深回撤</span>
                          <strong>{pct(mainLineMonthlyHealth.maxDrawdown)}</strong>
                          <small>红线 -{(mainLineMonthlyHealth.drawdownLimit * 100).toFixed(0)}%</small>
                        </div>
                      </div>
                      <div className="replay-monthly-defense">
                        <div className="replay-monthly-defense-head">
                          <span>回撤防守信号</span>
                          <strong>预警 -10% / 风险 -15%</strong>
                        </div>
                        <div className="replay-monthly-defense-list">
                          {mainLineDefenseSignals.map((signal) => (
                            <div className={`replay-monthly-defense-row ${signal.status}`} key={signal.month}>
                              <span>{signal.month}</span>
                              <strong>{signal.statusLabel}</strong>
                              <small>{signal.actionLabel}</small>
                              <small>{signal.reason}</small>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div className={`replay-monthly-simulation ${mainLineDefenseSimulation.status}`}>
                        <div>
                          <span>防守模拟</span>
                          <strong>{mainLineDefenseSimulation.statusLabel}</strong>
                          <small>上月信号决定下月仓位</small>
                        </div>
                        <div>
                          <span>防守后总收益</span>
                          <strong>{pct(mainLineDefenseSimulation.totalReturn)}</strong>
                          <small>原始 {pct(mainLineDefenseSimulation.originalTotalReturn)}</small>
                        </div>
                        <div>
                          <span>回撤改善</span>
                          <strong>{pct(mainLineDefenseSimulation.drawdownImprovement)}</strong>
                          <small>防守后 {pct(mainLineDefenseSimulation.maxDrawdown)}</small>
                        </div>
                        <div>
                          <span>收益让渡</span>
                          <strong>{pct(mainLineDefenseSimulation.returnGiveback)}</strong>
                          <small>换取更小回撤</small>
                        </div>
                      </div>
                      <div className="replay-monthly-performance-list">
                        {mainLineMonthlyPerformance.map((row) => (
                          <div className={`replay-monthly-performance-row ${row.tone}`} key={row.month}>
                            <span>{row.month}</span>
                            <strong>{pct(row.monthlyReturn)}</strong>
                            <small>总 {pct(row.cumulativeReturn)}</small>
                            <small className={row.drawdown <= -0.15 ? "risk" : ""}>
                              回撤 {pct(row.drawdown)}
                            </small>
                            <small>样本 {row.sampleCount}</small>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {visualMonthlyRows.length ? (
                    <div className="replay-visual-months">
                      <span>近月策略线</span>
                      {visualMonthlyRows.map((row) => (
                        <div className={`replay-visual-month ${row.tone}`} key={row.month}>
                          <div className="replay-visual-month-head">
                            <strong>{row.month}</strong>
                            <small>{row.postureLabel}</small>
                            <em>领先：{row.leaderLabel}</em>
                          </div>
                          <div className="replay-visual-month-lines">
                            {row.lines.map((line) => (
                              <div className={`replay-visual-month-line ${line.tone}`} key={`${row.month}-${line.scope}`}>
                                <span>{line.label}</span>
                                <strong>{pct(line.metric?.total_return)}</strong>
                                <div className="replay-visual-bar">
                                  <span style={{ width: `${replayBarWidth(line.metric?.total_return)}%` }} />
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
                <details className="replay-detail-drawer">
                  <summary>查看详细策略诊断</summary>
              <div className="replay-insight-block">
                <span>策略诊断</span>
                <div className="replay-diagnosis">
                  <strong>{candidateReplayEffect.diagnosis.policy_label}</strong>
                  <p>{uiText(candidateReplayEffect.diagnosis.summary)}</p>
                  <p>
                    {candidateReplayEffect.diagnosis.monthly_posture.month ?? "最近月份"}：
                    {candidateReplayEffect.diagnosis.monthly_posture.posture_label}。
                    {uiText(candidateReplayEffect.diagnosis.monthly_posture.summary)}
                  </p>
                  <div>
                    {candidateReplayEffect.diagnosis.reasons.slice(0, 3).map((reason) => (
                      <small key={reason}>{uiText(reason)}</small>
                    ))}
                  </div>
                  {candidateReplayEffect.diagnosis.overfit_guardrails.length ? (
                    <div className="replay-guardrails">
                      {candidateReplayEffect.diagnosis.overfit_guardrails.map((guardrail) => (
                        <small key={guardrail}>{uiText(guardrail)}</small>
                      ))}
                    </div>
                  ) : null}
                  <div className="replay-phase-policy">
                    <strong>{uiText(candidateReplayEffect.diagnosis.core_promotion_gate.label)}</strong>
                    <small>
                      核心上限 {candidateReplayEffect.diagnosis.core_promotion_gate.max_core_positions} 只 / 样本{" "}
                      {candidateReplayEffect.diagnosis.core_promotion_gate.sample_count} / 独立月份{" "}
                      {candidateReplayEffect.diagnosis.core_promotion_gate.month_count}
                    </small>
                    <small>{uiText(candidateReplayEffect.diagnosis.core_promotion_gate.summary)}</small>
                  </div>
                  {candidateReplayEffect.diagnosis.tactical_opportunities.length ? (
                    <div className="replay-tactical">
                      {candidateReplayEffect.diagnosis.tactical_opportunities.map((item) => (
                        <small key={item}>{uiText(item)}</small>
                      ))}
                    </div>
                  ) : null}
                  <div className="replay-phase-policy">
                    <strong>{candidateReplayEffect.diagnosis.market_phase_policy.label}</strong>
                    <small>
                      核心上限 {candidateReplayEffect.diagnosis.market_phase_policy.max_core_positions} 只 /{" "}
                      {candidateReplayEffect.diagnosis.market_phase_policy.expansion_allowed
                        ? "允许网页端扩散观察"
                        : "不扩大行动池"}
                    </small>
                    <small>{uiText(candidateReplayEffect.diagnosis.market_phase_policy.summary)}</small>
                    {candidateReplayEffect.diagnosis.market_phase_policy.reasons.slice(0, 2).map((reason) => (
                      <small key={reason}>{uiText(reason)}</small>
                    ))}
                  </div>
                  <div className="replay-phase-policy">
                    <strong>{candidateReplayEffect.diagnosis.market_stress_gate_policy.label}</strong>
                    <small>
                      核心上限 {candidateReplayEffect.diagnosis.market_stress_gate_policy.max_core_positions} 只 /{" "}
                      少亏改善 {pct(candidateReplayEffect.diagnosis.market_stress_gate_policy.avoided_total_loss)}
                    </small>
                    <small>{uiText(candidateReplayEffect.diagnosis.market_stress_gate_policy.summary)}</small>
                    {candidateReplayEffect.diagnosis.market_stress_gate_policy.reasons.slice(0, 2).map((reason) => (
                      <small key={reason}>{uiText(reason)}</small>
                    ))}
                  </div>
                  <div className="replay-dual-line-policy">
                    <strong>{uiText(candidateReplayEffect.diagnosis.dual_line_policy.summary)}</strong>
                    <small>
                      钉钉策略 {dingPolicyText(candidateReplayEffect.diagnosis.dual_line_policy.ding_policy)} / 核心上限{" "}
                      {candidateReplayEffect.diagnosis.dual_line_policy.max_core_positions} 只
                    </small>
                    <small>
                      主线：{lineStatusText(candidateReplayEffect.diagnosis.dual_line_policy.main_line.status)} /{" "}
                      {uiText(candidateReplayEffect.diagnosis.dual_line_policy.main_line.summary)}
                    </small>
                    <small>
                      辅线：{lineStatusText(candidateReplayEffect.diagnosis.dual_line_policy.support_line.status)} /{" "}
                      {uiText(candidateReplayEffect.diagnosis.dual_line_policy.support_line.summary ?? "暂无预热信号")}
                    </small>
                  </div>
                  {candidateDualLineLongSummary ? (
                    <div className="replay-dual-line-evidence">
                      <strong>{candidateDualLineLongSummary.horizon}日双线长期证据</strong>
                      <div className="dual-line-evidence-grid">
                        {[candidateDualLineLongSummary.mainLine, candidateDualLineLongSummary.supportLine].map((line) => (
                          <div className={`dual-line-evidence-item ${line.tone}`} key={line.scope}>
                            <span>{line.label} / {line.role}</span>
                            <strong>{pct(line.displayMetric?.avg_return)}</strong>
                            <small>
                              总收益 {pct(line.displayMetric?.total_return)} / 样本{" "}
                              {line.displayMetric?.sample_count ?? 0}
                            </small>
                          </div>
                        ))}
                      </div>
                      <small>{candidateDualLineLongSummary.guidance}</small>
                      <small>
                        均值领先：{dualLineLeaderText(candidateDualLineLongSummary.qualityLeader)} / 覆盖领先：
                        {dualLineLeaderText(candidateDualLineLongSummary.coverageLeader)}
                      </small>
                    </div>
                  ) : null}
                  {candidateMonthlyStrategyPkRows.length ? (
                    <div className="monthly-strategy-pk">
                      <strong>月度策略 PK</strong>
                      <div className="monthly-strategy-pk-list">
                        {candidateMonthlyStrategyPkRows.map((row) => (
                          <div className={`monthly-strategy-pk-row ${row.tone}`} key={row.month}>
                            <div className="monthly-strategy-pk-head">
                              <span>{row.month}</span>
                              <strong>{row.postureLabel}</strong>
                              <small>
                                领先：{row.leaderLabel} {pct(row.leaderTotalReturn)} / 最弱：{row.worstLineLabel}{" "}
                                {pct(row.worstTotalReturn)}
                              </small>
                            </div>
                            <div className="monthly-strategy-pk-lines">
                              {row.lines.map((line) => (
                                <span className={line.tone} key={`${row.month}-${line.scope}`}>
                                  {line.label} 均 {pct(line.metric?.avg_return)} / 总{" "}
                                  {pct(line.metric?.total_return)} / 样本 {line.metric?.sample_count ?? 0}
                                </span>
                              ))}
                            </div>
                            <small>{row.guidance}</small>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  <div className="replay-sector-policy">
                    <strong>
                      {candidateReplayEffect.diagnosis.sector_leadership_policy.label} /{" "}
                      {candidateReplayEffect.diagnosis.sector_leadership_policy.rhythm_label}
                    </strong>
                    <small>{uiText(candidateReplayEffect.diagnosis.sector_leadership_policy.summary)}</small>
                    <small>{uiText(candidateReplayEffect.diagnosis.sector_leadership_policy.rhythm_summary)}</small>
                    {candidateReplayEffect.diagnosis.sector_leadership_policy.warnings.slice(0, 1).map((warning) => (
                      <small className="replay-warning" key={warning}>
                        {uiText(warning)}
                      </small>
                    ))}
                    {candidateReplayEffect.diagnosis.sector_leadership_policy.rows.slice(0, 2).map((row) => (
                      <small key={row.scope}>
                        {row.label}：有效 {row.positive_months}/{row.month_count} 月 / 弱月{" "}
                        {row.negative_months} / 最近 {row.latest_month ?? "-"}
                      </small>
                    ))}
                    {candidateReplayEffect.diagnosis.sector_leadership_policy.rows.slice(0, 1).map((row) => (
                      <small key={`${row.scope}-metric`}>
                        强板块均值 {pct(row.strong_avg_return)} / 总收益{" "}
                        {pct(row.strong_total_return)} / 相对均值 {pct(row.avg_return_lift)}
                      </small>
                    ))}
                    {candidateReplayEffect.diagnosis.sector_leadership_policy.rules.slice(0, 1).map((rule) => (
                      <small key={rule}>{uiText(rule)}</small>
                    ))}
                  </div>
                  <div className="replay-potential-policy">
                    <strong>{candidateReplayEffect.diagnosis.potential_watch_policy.label}</strong>
                    <small>{uiText(candidateReplayEffect.diagnosis.potential_watch_policy.summary)}</small>
                  </div>
                </div>
                {candidateStrategyPkRows.length ? (
                  <>
                    <span>多策略对比</span>
                    <div className="strategy-pk-summary">
                      <strong>{uiText(candidateStrategyPk?.summary)}</strong>
                      <small>
                        口径：简单相加不复利 / 主周期 {candidateStrategyPk?.primary_horizon ?? 20}日 /{" "}
                        候选线 {candidateStrategyPkRows.length}
                      </small>
                      {candidateStrategyPk?.rules.slice(0, 2).map((rule) => (
                        <small key={rule}>{uiText(rule)}</small>
                      ))}
                    </div>
                    <div className="strategy-pk-list">
                      {candidateStrategyPkRows.map((row) => (
                        <div className="strategy-pk-row" key={row.scope}>
                          <div className="strategy-pk-main">
                            <strong>{row.label}</strong>
                            <span className={`strategy-pk-policy ${row.tone}`}>{row.policyLabel}</span>
                          </div>
                          <div className="strategy-pk-score">
                            <em className={row.tone}>{pct(row.primaryMetric?.avg_return)}</em>
                            <small>
                              {row.primaryHorizon}日均值 / 总收益 {pct(row.primaryMetric?.total_return)} / 胜率{" "}
                              {pct(row.primaryMetric?.win_rate)} / 样本 {row.primaryMetric?.sample_count ?? 0}
                            </small>
                          </div>
                          <div className="strategy-pk-meta">
                            <small>
                              候选 {row.candidateCount} / 月份 {row.monthCount} / 正负{" "}
                              {row.positiveMonths}:{row.negativeMonths}
                            </small>
                            <small>
                              最近 {row.latestMonth ?? "暂无"} {pct(row.latestMonthMetric?.total_return)} / 最差{" "}
                              {pct(row.worstMonthTotalReturn)} / 最好 {pct(row.bestMonthTotalReturn)}
                            </small>
                            <small>
                              月回撤 {pct(row.monthlyMaxDrawdown)} / 月均样本 {row.avgMonthlySampleCount ?? "-"}
                            </small>
                            <small>
                              月正比 {pct(row.monthlyPositiveRatio)} / 收益回撤比{" "}
                              {row.returnDrawdownRatio?.toFixed(2) ?? "-"}
                            </small>
                          </div>
                          <div className="strategy-pk-metrics">
                            {row.horizonMetrics.map((metric) => (
                              <span className={metric.tone} key={`${row.scope}-${metric.horizon}`}>
                                {metric.label} {pct(metric.metric?.total_return)}
                              </span>
                            ))}
                          </div>
                          <small className="strategy-pk-reason">{uiText(row.rankReason)}</small>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}
                <span>启动前夜短周期</span>
                <div className="replay-row-list">
                  {startupPreheatEffectRows.map((row) => (
                    <div className="replay-insight-row" key={row.horizon}>
                      <strong>{row.label}</strong>
                      <em className={row.tone}>{pct(row.metric?.total_return)}</em>
                      <small>
                        均值 {pct(row.metric?.avg_return)} / 胜率 {pct(row.metric?.win_rate)} / 样本{" "}
                        {row.metric?.sample_count ?? 0}
                      </small>
                      {row.highSignalMetric ? (
                        <small>
                          高分启动组 {pct(row.highSignalMetric.total_return)} / 均值{" "}
                          {pct(row.highSignalMetric.avg_return)} / 样本{" "}
                          {row.highSignalMetric.sample_count}
                        </small>
                      ) : null}
                    </div>
                  ))}
                </div>
                {startupSignalEffectRows.length ? (
                  <div className="startup-signal-replay">
                    <strong>启动信号回归</strong>
                    <div className="startup-signal-replay-list">
                      {startupSignalEffectRows.map((row) => (
                        <div className={`startup-signal-replay-row ${row.tone}`} key={row.horizon}>
                          <div className="startup-signal-replay-head">
                            <span>{row.label}</span>
                            <strong>{row.postureLabel}</strong>
                            <small>{row.guidance}</small>
                          </div>
                          <div className="startup-signal-replay-metrics">
                            <span className={row.tone}>
                              高分均值 {pct(row.highSignalMetric?.avg_return)} / 总收益{" "}
                              {pct(row.highSignalMetric?.total_return)} / 样本{" "}
                              {row.highSignalMetric?.sample_count ?? 0}
                            </span>
                            <span>
                              整体均值 {pct(row.baselineMetric?.avg_return)} / 总收益{" "}
                              {pct(row.baselineMetric?.total_return)} / 样本{" "}
                              {row.baselineMetric?.sample_count ?? 0}
                            </span>
                            <span
                              className={
                                row.liftAvgReturn === null
                                  ? "neutral"
                                  : row.liftAvgReturn > 0
                                    ? "up"
                                    : "down"
                              }
                            >
                              均值差 {pct(row.liftAvgReturn)}
                            </span>
                            {row.lowSignalMetric ? (
                              <span className="neutral">
                                低分均值 {pct(row.lowSignalMetric.avg_return)} / 样本{" "}
                                {row.lowSignalMetric.sample_count}
                              </span>
                            ) : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
                {startupSignalStyleEffectRows.length ? (
                  <div className="startup-signal-style-replay">
                    <strong>启动信号风格拆分</strong>
                    <div className="startup-signal-style-list">
                      {startupSignalStyleEffectRows.map((row) => (
                        <div className={`startup-signal-style-row ${row.tone}`} key={row.style}>
                          <div className="startup-signal-style-head">
                            <span>{row.label}</span>
                            <strong>{row.postureLabel}</strong>
                            <small>{row.guidance}</small>
                          </div>
                          <div className="startup-signal-style-metrics">
                            <span className={row.tone}>
                              高分20日 {pct(row.highSignalMetric?.avg_return)} / 总收益{" "}
                              {pct(row.highSignalMetric?.total_return)} / 样本{" "}
                              {row.highSignalMetric?.sample_count ?? 0}
                            </span>
                            <span>
                              风格整体 {pct(row.baselineMetric?.avg_return)} / 样本{" "}
                              {row.baselineMetric?.sample_count ?? 0}
                            </span>
                            <span
                              className={
                                row.liftAvgReturn === null
                                  ? "neutral"
                                  : row.liftAvgReturn > 0
                                    ? "up"
                                    : "down"
                              }
                            >
                              均值差 {pct(row.liftAvgReturn)}
                            </span>
                            {row.lowSignalMetric ? (
                              <span className="neutral">
                                低分20日 {pct(row.lowSignalMetric.avg_return)} / 样本{" "}
                                {row.lowSignalMetric.sample_count}
                              </span>
                            ) : null}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
                {startupPreheatGateRows.length ? (
                  <>
                    <span>启动前夜门控</span>
                    <div className="replay-row-list">
                      {startupPreheatGateRows.map((row) => (
                        <div className="replay-insight-row" key={row.style}>
                          <strong>{row.label}</strong>
                          <em
                            className={
                              row.status === "upgrade_allowed"
                                ? "up"
                                : row.status === "stand_down"
                                  ? "down"
                                  : "neutral"
                            }
                          >
                            {row.status_label}
                          </em>
                          <small>
                            {row.latest_month} / 均值 {pct(row.latest_avg_return)} / 胜率{" "}
                            {pct(row.latest_win_rate)} / 样本 {row.latest_sample_count}
                          </small>
                          <small>{uiText(row.summary)}</small>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}
                {potentialWatchStyleRows.length ? (
                  <>
                    <span>潜力观察风格拆分（10日）</span>
                    <div className="replay-row-list">
                      {potentialWatchStyleRows.map((row) => (
                        <div className="replay-insight-row" key={`${row.month}-${row.style}`}>
                          <strong>{row.label}</strong>
                          <em className={row.tone}>{pct(row.metric.total_return)}</em>
                          <small>
                            {row.month} / 均值 {pct(row.metric.avg_return)} / 胜率{" "}
                            {pct(row.metric.win_rate)} / 样本 {row.metric.sample_count}
                          </small>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}
                {styleGateRows.length ? (
                  <>
                    <span>板块风格门控</span>
                    <div className="replay-row-list">
                      {styleGateRows.map((row) => (
                        <div className="replay-insight-row" key={row.style}>
                          <strong>{row.label}</strong>
                          <em
                            className={
                              row.status === "upgrade_allowed"
                                ? "up"
                                : row.status === "stand_down"
                                  ? "down"
                                  : "neutral"
                            }
                          >
                            {row.status_label}
                          </em>
                          <small>
                            {row.latest_month} / 均值 {pct(row.latest_avg_return)} / 胜率{" "}
                            {pct(row.latest_win_rate)} / 样本 {row.latest_sample_count}
                          </small>
                          <small>{uiText(row.summary)}</small>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}
                <span>20日策略池收益</span>
                <div className="replay-row-list">
                  {candidateReplayScopeRows.map((row) => (
                    <div className="replay-insight-row" key={row.scope}>
                      <strong>{row.label}</strong>
                      <em className={row.tone}>{pct(row.metric?.total_return)}</em>
                      <small>
                        均值 {pct(row.metric?.avg_return)} / 胜率 {pct(row.metric?.win_rate)} / 样本{" "}
                        {row.metric?.sample_count ?? 0} / 候选 {row.candidateCount}
                      </small>
                      <small>
                        3只等权 {pct(row.portfolioMetric?.total_return)} / 均值{" "}
                        {pct(row.portfolioMetric?.avg_return)} / 交易日 {row.portfolioMetric?.sample_count ?? 0}
                      </small>
                    </div>
                  ))}
                </div>
              </div>
                </details>
              </>
            ) : null}
            {lowDimensionalReplay ? (
              <>
                <div className="monthly-summary-grid">
                  {replayMetricCards.map(([label, metric]) => (
                    <div className="fit-metric" key={label}>
                      <span>{label}风控收益</span>
                      <strong className={((metric?.total_return ?? 0) >= 0 ? "up" : "down")}>
                        {pct(metric?.total_return)}
                      </strong>
                      <small>
                        均值 {pct(metric?.avg_return)} / 胜率 {pct(metric?.win_rate)} / 样本{" "}
                        {metric?.sample_count ?? 0}
                      </small>
                    </div>
                  ))}
                </div>
                {replayCapitalCurve20d ? (
                  <div className={`replay-capital-curve ${replayCapitalCurve20d.status}`}>
                    <div className="replay-capital-curve-head">
                      <div className={replayCapitalCurve20d.status}>
                        <span>20日非复利资金曲线</span>
                        <strong>{pct(replayCapitalCurve20d.metric.total_return)}</strong>
                      </div>
                      <div className={replayCapitalCurve20d.status}>
                        <span>最大回撤</span>
                        <strong>{pct(replayCapitalCurve20d.metric.max_drawdown)}</strong>
                      </div>
                      <div className={replayCapitalCurve20d.defensiveStatus}>
                        <span>多板块确认</span>
                        <strong>{pct(replayCapitalCurve20d.defensiveMetric.total_return)}</strong>
                      </div>
                      <div className={replayCapitalCurve20d.defensiveStatus}>
                        <span>防守回撤</span>
                        <strong>{pct(replayCapitalCurve20d.defensiveMetric.max_drawdown)}</strong>
                      </div>
                      <small>
                        当前{replayCapitalCurve20d.metric.max_drawdown_passed ? "通过" : "超过"}15% / 多板块
                        {replayCapitalCurve20d.defensiveMetric.max_drawdown_passed ? "通过" : "超过"} / 防守样本{" "}
                        {replayCapitalCurve20d.defensiveMetric.sample_count}批
                      </small>
                    </div>
                    <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="20日非复利资金曲线">
                      <line
                        className="replay-capital-zero"
                        x1="0"
                        x2="100"
                        y1={replayCapitalCurve20d.points[0]?.y ?? 50}
                        y2={replayCapitalCurve20d.points[0]?.y ?? 50}
                      />
                      <polyline className="baseline" points={replayCapitalCurve20d.pointString} />
                      <polyline
                        className={`defensive ${replayCapitalCurve20d.defensiveStatus}`}
                        points={replayCapitalCurve20d.defensivePointString}
                      />
                      {replayCapitalCurve20d.points.length ? (
                        <circle
                          className="baseline"
                          cx={replayCapitalCurve20d.points[replayCapitalCurve20d.points.length - 1].x}
                          cy={replayCapitalCurve20d.points[replayCapitalCurve20d.points.length - 1].y}
                          r="2.8"
                        />
                      ) : null}
                      {replayCapitalCurve20d.defensivePoints.length ? (
                        <circle
                          className={`defensive ${replayCapitalCurve20d.defensiveStatus}`}
                          cx={replayCapitalCurve20d.defensivePoints[replayCapitalCurve20d.defensivePoints.length - 1].x}
                          cy={replayCapitalCurve20d.defensivePoints[replayCapitalCurve20d.defensivePoints.length - 1].y}
                          r="2.8"
                        />
                      ) : null}
                    </svg>
                  </div>
                ) : null}
                {replayDefensiveValidationRows.length ? (
                  <div className="replay-validation-strip">
                    {replayDefensiveValidationRows.map((row) => (
                      <div className={row.tone} key={row.horizon}>
                        <span>{row.label}年度验证</span>
                        <strong>{row.statusLabel}</strong>
                        <small>{row.detail}</small>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="monthly-summary-lists">
                  <div>
                    <span>主线板块</span>
                    {lowDimensionalReplay.top_sectors.slice(0, 6).map((item) => (
                      <small key={item.sector}>{item.sector} / {item.count}次</small>
                    ))}
                  </div>
                  <div>
                    <span>20日月度收益</span>
                    {replayMonthlyItems(lowDimensionalReplay, 20).slice(0, 6).map(([month, item]) => (
                      <small key={month}>
                        {month} / {pct(item.guarded.total_return)} / 样本 {item.guarded.sample_count}
                      </small>
                    ))}
                  </div>
                </div>
                <div className="replay-insight-grid">
                  <div className="replay-insight-block">
                    <span>20日模式贡献</span>
                    <div className="replay-row-list">
                      {replayModeRows.map((row) => (
                        <div className="replay-insight-row" key={row.key}>
                          <strong>{row.label}</strong>
                          <em className={row.tone}>{pct(row.metric.total_return)}</em>
                          <small>
                            均值 {pct(row.metric.avg_return)} / 胜率 {pct(row.metric.win_rate)} / 样本{" "}
                            {row.metric.sample_count}
                          </small>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="replay-insight-block">
                    <span>20日风格贡献</span>
                    <div className="replay-row-list">
                      {replayStyleRows.map((row) => (
                        <div className="replay-insight-row" key={row.key}>
                          <strong>{row.label}</strong>
                          <em className={row.tone}>{pct(row.metric.total_return)}</em>
                          <small>
                            均值 {pct(row.metric.avg_return)} / 胜率 {pct(row.metric.win_rate)} / 样本{" "}
                            {row.metric.sample_count}
                          </small>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="replay-insight-block">
                    <span>风格窗口</span>
                    <div className="replay-row-list">
                      {replayStylePreferences.map((row) => (
                        <div className="replay-insight-row" key={row.style}>
                          <strong>{row.label}</strong>
                          <em className={row.tone}>{row.preferredHorizon}日</em>
                          <small>
                            均值 {pct(row.avgReturn)} / 总收益 {pct(row.totalReturn)} / 样本{" "}
                            {row.sampleCount}
                          </small>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="replay-insight-block">
                    <span>20日亏损月份</span>
                    <div className="replay-row-list">
                      {replayWeakMonths.length ? (
                        replayWeakMonths.map((row) => (
                          <div className="replay-insight-row" key={row.month}>
                            <strong>{row.month}</strong>
                            <em className={row.tone}>{pct(row.metric.total_return)}</em>
                            <small>
                              均值 {pct(row.metric.avg_return)} / 胜率 {pct(row.metric.win_rate)} / 样本{" "}
                              {row.metric.sample_count}
                            </small>
                          </div>
                        ))
                      ) : (
                        <small>暂无负收益月份</small>
                      )}
                    </div>
                  </div>
                </div>
                <small>
                  风控退出：5日 {replayExitText(replay5d)}；10日 {replayExitText(replay10d)}；20日{" "}
                  {replayExitText(replay20d)}
                </small>
              </>
            ) : (
              <div className="empty compact">运行后展示月收益、总收益和板块来源。</div>
            )}
          </section>
          <section className={`data-health-panel ${dataHealthTone(dataHealth)}`}>
            <div className="data-health-main">
              <span>数据健康</span>
              <strong>{dataHealthStatusText(dataHealth)}</strong>
              <small>
                {dataHealth?.trade_date ?? "暂无日期"} / 日线 {dataHealth?.daily_bar_count ?? 0}
                {" "} / 特征 {dataHealth?.feature_count ?? 0}
              </small>
            </div>
            <div className="data-health-metrics">
              <div>
                <span>成交额缺失</span>
                <strong>{pct(dataHealth?.amount_missing_ratio)}</strong>
                <small>前日 {pct(dataHealth?.previous_amount_missing_ratio)}</small>
              </div>
              <div>
                <span>量额比中位</span>
                <strong>{dataHealth?.amount_ratio_5d_median?.toFixed(2) ?? "-"}</strong>
                <small>P10 {dataHealth?.amount_ratio_5d_p10?.toFixed(2) ?? "-"}</small>
              </div>
              <div>
                <span>量能确认</span>
                <strong>{scoreText(dataHealth?.volume_confirmation_median ?? null)}</strong>
                <small>样本稳定性</small>
              </div>
            </div>
            <div className="data-health-schedule">
              <div>
                <span>数据链路</span>
                <strong>{dataPipelineStatusText(dataHealth, marketOverview)}</strong>
                <small>{dataPipelineDetailText(dataHealth, marketOverview)}</small>
              </div>
              <div>
                <span>收盘任务</span>
                <strong>18:00</strong>
                <small>回归 21:00 / 日报 22:30</small>
              </div>
            </div>
            <div className="data-health-issues">
              {dataHealth?.issues.length ? (
                dataHealth.issues.slice(0, 3).map((issue) => (
                  <span key={issue.code}>{issue.message}</span>
                ))
              ) : (
                <span>日线、特征和量额比例暂未发现成片异常。</span>
              )}
            </div>
          </section>
          <section className="sector-catalyst-panel">
            <div className="snapshot-review-head">
              <div>
                <span>消息催化</span>
                <strong>{sectorCatalysts?.catalysts[0]?.sector_name ?? "等待热词"}</strong>
              </div>
              <small>
                {dateTimeText(sectorCatalysts?.as_of)} / {catalystMetaText(sectorCatalysts)}
              </small>
            </div>
            <div className="sector-catalyst-list">
              {sectorCatalysts?.catalysts.length ? (
                sectorCatalysts.catalysts.slice(0, 6).map((item) => (
                  <button
                    className={`sector-catalyst-item ${catalystTone(item.catalyst_score)}`}
                    key={item.sector_name}
                    type="button"
                    onClick={() => {
                      const matched = sectorOverview?.sectors.find(
                        (sector) =>
                          sector.sector_name === item.sector_name ||
                          sector.canonical_sector_name === item.sector_name ||
                          item.related_sectors.includes(sector.sector_name) ||
                          (sector.canonical_sector_name
                            ? item.related_sectors.includes(sector.canonical_sector_name)
                            : false),
                      );
                      if (matched) setSelectedSectorCode(matched.sector_code);
                    }}
                  >
                    <span>
                      <strong>{item.sector_name}</strong>
                      <small>{item.catalyst_label} / {item.catalyst_score.toFixed(1)}分</small>
                    </span>
                    <em>{item.keywords.slice(0, 5).join("、") || "-"}</em>
                    <small>{item.source_titles[0] ?? item.related_sectors.join("、")}</small>
                    <i>{item.risk_notes[0] ?? sectorCatalysts.message}</i>
                  </button>
                ))
              ) : (
                <div className="intraday-empty">{sectorCatalysts?.message ?? "暂无消息催化"}</div>
              )}
            </div>
          </section>
          <section className="sector-radar-grid">
            {[
              ["月度主线", "monthly", sectorOverview?.monthly_rank ?? []],
              ["资金活跃", "activity", sectorOverview?.activity_rank ?? []],
              ["趋势持续", "continuity", sectorOverview?.continuity_rank ?? []],
            ].map(([title, kind, items]) => (
              <div className="sector-radar-card" key={title as string}>
                <span>{title as string}</span>
                {(items as SectorOverviewItem[]).slice(0, 5).map((item) => (
                  <button
                    className={`sector-radar-item ${sectorRadarTone(item, kind as SectorRadarKind)}`}
                    key={`${title}-${item.sector_code}`}
                    type="button"
                    onClick={() => setSelectedSectorCode(item.sector_code)}
                  >
                    <span className="sector-radar-item-head">
                      <strong>{item.sector_name}</strong>
                      <em>{sectorRadarValueText(item, kind as SectorRadarKind)}</em>
                    </span>
                    <span className="sector-radar-bar">
                      <i style={{ width: `${sectorRadarWidth(item, kind as SectorRadarKind)}%` }} />
                    </span>
                    <small>
                      月 {pct(item.monthly_return_pct)} / 强度 {scoreText(item.sector_strength_score)}
                    </small>
                    <small>门控 {sectorGateText(item)}</small>
                  </button>
                ))}
                {!(items as SectorOverviewItem[]).length ? <small>暂无数据</small> : null}
              </div>
            ))}
          </section>
          <section className="snapshot-review-panel">
            <div className="snapshot-review-head">
              <div>
                <span>盘中快照复盘</span>
                <strong>{intradaySnapshots?.trade_date ?? "等待快照"}</strong>
              </div>
              <button
                type="button"
                onClick={() => loadIntradayCandidates(true)}
                aria-label="刷新盘中快照"
              >
                <RefreshCw size={14} />
              </button>
            </div>
            {intradaySnapshots?.learning_summary ? (
              <div className="snapshot-summary-grid">
                <div>
                  <span>阶段样本</span>
                  <strong>{intradaySnapshots.learning_summary.transition_count}</strong>
                  <small>最近 {intradaySnapshots.learning_summary.sample_days} 个交易日</small>
                </div>
                <div>
                  <span>转弱</span>
                  <strong className="down">
                    {intradaySnapshots.learning_summary.verdict_counts.weakened ?? 0}
                  </strong>
                  <small>午间强但尾盘承接差</small>
                </div>
                <div>
                  <span>修复</span>
                  <strong className="up">
                    {intradaySnapshots.learning_summary.verdict_counts.repaired ?? 0}
                  </strong>
                  <small>盘中由弱转强</small>
                </div>
                <div>
                  <span>保持强势</span>
                  <strong className="up">
                    {intradaySnapshots.learning_summary.verdict_counts.held_strength ?? 0}
                  </strong>
                  <small>顺势观察</small>
                </div>
              </div>
            ) : null}
            {intradaySnapshots?.learning_summary?.pattern_notes.length ? (
              <div className="snapshot-pattern-notes">
                {intradaySnapshots.learning_summary.pattern_notes.slice(0, 3).map((note) => (
                  <span key={note}>{note}</span>
                ))}
              </div>
            ) : null}
            {intradaySnapshots?.learning.length ? (
              <div className="snapshot-learning-list">
                {intradaySnapshots.learning.slice(0, 6).map((item) => (
                  <button
                    className={`snapshot-learning-item ${learningTone(item.verdict)}`}
                    key={`${item.symbol}-${item.from_stage}-${item.to_stage}`}
                    type="button"
                    onClick={() => {
                      setSelectedSymbol(item.symbol);
                      setActivePage("stocks");
                    }}
                  >
                    <span>
                      <strong>{item.symbol}</strong>
                      <small>{item.name ?? "-"} / {item.from_stage_label} {"->"} {item.to_stage_label}</small>
                    </span>
                    <span>
                      <b>{item.verdict_label}</b>
                      <small>{item.from_label} {"->"} {item.to_label} / {signedScore(item.score_delta)}分</small>
                    </span>
                    <em>{item.reason}</em>
                  </button>
                ))}
              </div>
            ) : null}
            <div className="snapshot-stage-grid">
              {intradaySnapshots?.snapshots.length ? (
                intradaySnapshots.snapshots.map((snapshot) => (
                  <div className="snapshot-stage-card" key={snapshot.stage}>
                    <div className="snapshot-stage-title">
                      <span>{snapshot.stage_label}</span>
                      <small>{timeOnly(snapshot.as_of)} / {snapshot.candidate_count} 只</small>
                    </div>
                    <div className="snapshot-candidate-list">
                      {snapshot.candidates.slice(0, 5).map((item) => (
                        <button
                          className={`snapshot-candidate ${intradayItemTone(
                            item.intraday_state,
                            item.sector_signal,
                          )}`}
                          key={`${snapshot.stage}-${item.symbol}`}
                          type="button"
                          onClick={() => {
                            setSelectedSymbol(item.symbol);
                            setActivePage("stocks");
                          }}
                        >
                          <span>
                            <strong>
                              {item.symbol}
                              <i className={`tier-pill ${selectionTierTone(item.selection_tier)}`}>
                                {item.selection_tier_label}
                              </i>
                            </strong>
                            <small>{item.name ?? "-"} / {item.sector ?? "-"}</small>
                          </span>
                          <span>
                            <b>{item.intraday_label}</b>
                            <small>{pct(item.day_change_pct)} / {item.intraday_score.toFixed(1)}分</small>
                            <small>
                              {item.sector_quality_label}{item.sector_quality_score.toFixed(1)}
                            </small>
                          </span>
                          <em>{candidateExplanationText(item)}</em>
                        </button>
                      ))}
                      {!snapshot.candidates.length ? (
                        <div className="intraday-empty">暂无候选</div>
                      ) : null}
                    </div>
                  </div>
                ))
              ) : (
                <div className="intraday-empty">暂无可复盘快照</div>
              )}
            </div>
          </section>
          <div className="sector-grid">
            <div className="sector-list">
              <div className="stock-table-head sector-head">
                <span>板块</span>
                <span>月度排名</span>
                <span>资金 / 技术</span>
              </div>
              {!sectorOverview?.sectors.length ? <div className="empty compact">暂无板块数据</div> : null}
              {sectorOverview?.sectors.map((item) => (
                <button
                  key={item.sector_code}
                  type="button"
                  className={`stock-row sector-row ${selectedSector?.sector_code === item.sector_code ? "selected" : ""}`}
                  onClick={() => setSelectedSectorCode(item.sector_code)}
                >
                  <span>
                    <strong>{item.sector_name}</strong>
                    {item.canonical_sector_name ? (
                      <small>映射 {item.canonical_sector_name}</small>
                    ) : null}
                    <small>当日 {pct(item.day_change_pct)} / 月内 {pct(item.monthly_return_pct)}</small>
                    <small>{sectorBreadthText(item)}</small>
                    <small>{item.sector_gate_reasons.slice(0, 2).join(" / ") || "门控待确认"}</small>
                  </span>
                  <span className="source-stack">
                    <span className={`source-pill ${sectorTone(item)}`}>
                      {item.sector_gate_label ?? "门控待确认"}
                    </span>
                    <span className={`source-pill ${sectorTone(item)}`}>
                      {item.month_rank ? `第 ${item.month_rank} 名` : "未排名"}
                    </span>
                    <small>{item.month_start_date ? `${item.month_start_date} 起` : "月初未知"}</small>
                  </span>
                  <span>
                    <em className={sectorTone(item)}>{sectorFlowText(item)}</em>
                    <small>{sectorSignalText(item)}</small>
                    <small>成交 {amountText(item.amount)}</small>
                  </span>
                </button>
              ))}
            </div>
            <div className="sector-detail">
              <section className="detail-section">
                <div className="section-title">
                  <ClipboardList size={16} />
                  <h3>月度位置</h3>
                </div>
                {selectedSector ? (
                  <div className="review-summary-block single-column">
                    <div className={`review-summary-panel ${sectorTone(selectedSector)}`}>
                      <span>{selectedSector.sector_name}</span>
                      <ul>
                        {selectedSector.canonical_sector_name ? (
                          <li>特征归一 {selectedSector.canonical_sector_name}</li>
                        ) : null}
                        <li>月度排名 {selectedSector.month_rank ?? "-"} / 月内收益 {pct(selectedSector.monthly_return_pct)}</li>
                        <li>板块门控 {sectorGateText(selectedSector)}</li>
                        <li>{selectedSector.sector_gate_reasons.join(" / ") || "门控待确认"}</li>
                        <li>当日表现 {pct(selectedSector.day_change_pct)} / 成交 {amountText(selectedSector.amount)}</li>
                        <li>资金流 {sectorFlowText(selectedSector)}</li>
                        <li>
                          特征覆盖 {pct(sectorOverview?.feature_coverage_ratio ?? null)} / 样本 {sectorOverview?.feature_sector_count ?? 0}
                          /{sectorOverview?.overview_sector_count ?? 0}
                        </li>
                        <li>
                          资金覆盖 {pct(sectorOverview?.moneyflow_coverage_ratio ?? null)} / 已匹配 {sectorOverview?.moneyflow_sector_count ?? 0}
                          /{sectorOverview?.overview_sector_count ?? 0} / 缺失 {sectorOverview?.moneyflow_missing_count ?? 0}
                        </li>
                      </ul>
                    </div>
                  </div>
                ) : (
                  <div className="empty compact">请选择板块</div>
                )}
              </section>
              <section className="detail-section">
                <div className="section-title">
                  <TrendingUp size={16} />
                  <h3>技术与广度</h3>
                </div>
                {selectedSector ? (
                  <div className="fit-metric-grid sector-metric-grid">
                    <div className={`fit-metric ${sectorTone(selectedSector)}`}>
                      <span>板块强度</span>
                      <strong>{scoreText(selectedSector.sector_strength_score)}</strong>
                      <small>偏趋势还是偏防守</small>
                    </div>
                    <div className={`fit-metric ${sectorTone(selectedSector)}`}>
                      <span>板块广度</span>
                      <strong>{scoreText(selectedSector.sector_breadth_score)}</strong>
                      <small>{sectorBreadthText(selectedSector)}</small>
                    </div>
                    <div className={`fit-metric ${sectorTone(selectedSector)}`}>
                      <span>板块动量</span>
                      <strong>{scoreText(selectedSector.sector_momentum_score)}</strong>
                      <small>看趋势延续性</small>
                    </div>
                  </div>
                ) : (
                  <div className="empty compact">暂无技术侧数据</div>
                )}
              </section>
            </div>
          </div>
        </section>
      ) : null}

    </main>
  );
}
