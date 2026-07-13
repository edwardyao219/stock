// @ts-ignore Node's experimental TypeScript runner needs the explicit extension.
import { buildCandleTrendPath, buildStockTrackingProfile, sortStockTrackingProfiles } from "./stockTracking.ts";
import type { Candle, TrackingSignalItem, WorkspaceStock } from "./api.ts";

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(message);
}

function stock(overrides: Partial<WorkspaceStock>): WorkspaceStock {
  return {
    symbol: "002558",
    name: "测试股份",
    industry: "电子",
    sector_style: "growth_cycle",
    source: "auto",
    manual_note: "候选理由：板块强势，个股放量突破。",
    manual_tags: ["after_close_candidate", "tier:core_action"],
    candidate_rank: 1,
    candidate_score: 84,
    candidate_tier: "core_action",
    candidate_tier_label: "核心行动",
    candidate_tier_reason: "板块和个股趋势同时在线。",
    startup_signal_score: 78,
    startup_signal_label: "启动观察",
    startup_signal_reasons: ["量价开始共振"],
    feature_date: "2026-07-09",
    latest_trade_date: "2026-07-10",
    latest_close: 12,
    current_price: 12.3,
    day_change_pct: 0.021,
    quote_time: "2026-07-10T10:30:00",
    return_5d: 0.06,
    return_20d: 0.16,
    trend_score: 82,
    relative_strength_score: 79,
    sector_strength_score: 76,
    volume_confirmation_score: 74,
    risk_score: 24,
    overheat_score: 28,
    volume_trap_risk_score: 18,
    distance_to_ma20: 0.06,
    amount_percentile_60d: 0.72,
    amount_ratio_5d: 1.35,
    pullback_volume_ratio: 0.82,
    ma20_slope_20d: 0.03,
    ma60_slope_20d: 0.01,
    ma_alignment_score: 78,
    trend_quality_score: 81,
    route_score: 82,
    route_label: "主升趋势",
    route_reason: "趋势和量能较好",
    plans: [],
    paper_trade_summaries: [],
    recent_paper_trades: [],
    ...overrides,
  } as WorkspaceStock;
}

const holding = stock({
  recent_paper_trades: [
    {
      id: 1,
      trade_plan_id: 11,
      rule_id: "R005",
      entry_date: "2026-07-09",
      entry_price: 11.8,
      exit_date: null,
      exit_price: null,
      holding_days: 1,
      pnl_pct: null,
      mfe_pct: 0.05,
      mae_pct: -0.01,
      highest_price: 12.5,
      lowest_price: 11.7,
      quantity: 100,
      status: "open",
      exit_reason: null,
      current_price: 12.3,
      current_pnl_pct: 0.042,
      current_stop: 11.3,
      take_profit_1: 13.2,
      quote_time: "2026-07-10T10:30:00",
    },
  ],
});
const holdingProfile = buildStockTrackingProfile(holding);

assert(holdingProfile.stageLabel === "趋势持有", "强趋势模拟持仓要进入趋势持有");
assert(holdingProfile.score >= 75, "强趋势模拟持仓的追踪分不能太低");
assert(holdingProfile.nextAction.includes("继续跟踪"), "强趋势持仓应该提示继续跟踪而不是每天重新筛掉");
assert(holdingProfile.timeline.length >= 5, "追踪档案需要有连续证据线");
assert(holdingProfile.timeline.some((item) => item.title === "模拟持仓"), "持仓票需要显示模拟持仓节点");
assert(holdingProfile.decision.verdictLabel === "继续跟踪", "持仓强趋势票需要给出继续跟踪结论");
assert(holdingProfile.decision.primaryReasons.some((item) => item.includes("板块")), "继续跟踪理由要包含板块证据");
assert(holdingProfile.decision.downgradeReasons.length > 0, "继续跟踪也必须给出降级条件");

const risky = stock({
  symbol: "300999",
  candidate_tier: "risk_reject",
  candidate_tier_label: "淘汰/风险",
  candidate_tier_reason: "冲高回落，放量诱多。",
  trend_score: 42,
  relative_strength_score: 38,
  sector_strength_score: 31,
  volume_confirmation_score: 28,
  risk_score: 82,
  overheat_score: 77,
  volume_trap_risk_score: 86,
  distance_to_ma20: 0.18,
  return_20d: 0.34,
  manual_note: "候选理由：冲高回落，放量诱多风险偏高。",
});
const riskyProfile = buildStockTrackingProfile(risky);

assert(riskyProfile.stageLabel === "风险复核", "高风险或淘汰票要进入风险复核");
assert(riskyProfile.score < holdingProfile.score, "风险票追踪分要低于强趋势持仓");
assert(riskyProfile.risks.some((item) => item.includes("诱多")), "风险理由需要指出诱多/放量问题");
assert(riskyProfile.nextAction.includes("降级"), "风险复核的下一步应提示降级");
assert(riskyProfile.decision.verdictLabel === "暂不看好", "风险复核票需要明确暂不看好");
assert(riskyProfile.decision.downgradeReasons.some((item) => item.includes("诱多")), "暂不看好的理由要点出诱多风险");
assert(riskyProfile.decision.upgradeConditions.some((item) => item.includes("板块")), "暂不看好也要给出重新升级条件");

const watch = stock({
  symbol: "601888",
  recent_paper_trades: [],
  candidate_tier: "watch_wait",
  candidate_tier_label: "观察等待",
  candidate_score: 65,
  trend_score: 55,
  relative_strength_score: 52,
  sector_strength_score: 58,
  volume_confirmation_score: 45,
});
const sorted = sortStockTrackingProfiles([
  buildStockTrackingProfile(watch),
  riskyProfile,
  holdingProfile,
]);

assert(sorted[0].symbol === "002558", "排序应优先展示值得中长期持续追踪的票");
assert(sorted[2].symbol === "300999", "风险复核票应排到后面");

const highScoreThinSample = buildStockTrackingProfile(stock({
  symbol: "002001",
  recent_paper_trades: [],
  candidate_tier: "core_action",
  trend_score: 88,
  relative_strength_score: 86,
  sector_strength_score: 84,
  volume_confirmation_score: 82,
  candidate_score: 90,
  startup_signal_score: 86,
}));
const validatedTrend = buildStockTrackingProfile(stock({
  symbol: "002002",
  recent_paper_trades: [],
  candidate_tier: "core_action",
  trend_score: 76,
  relative_strength_score: 74,
  sector_strength_score: 76,
  volume_confirmation_score: 72,
  candidate_score: 76,
  startup_signal_score: 76,
}));
const validationSignals = new Map<string, TrackingSignalItem>([
  [
    "002001",
    {
      symbol: "002001",
      name: "高分薄样本",
      industry: "电子",
      latest_snapshot_date: "2026-07-10",
      sample_count: 1,
      score_delta: null,
      simple_return_pct: null,
      signal_alignment_key: "insufficient",
      signal_alignment_label: "样本不足",
      signal_alignment_tone: "neutral",
    },
  ],
  [
    "002002",
    {
      symbol: "002002",
      name: "验证趋势",
      industry: "电子",
      latest_snapshot_date: "2026-07-10",
      sample_count: 4,
      score_delta: 5,
      simple_return_pct: 8,
      signal_alignment_key: "aligned",
      signal_alignment_label: "分价同向",
      signal_alignment_tone: "good",
    },
  ],
]);
const validatedSorted = sortStockTrackingProfiles(
  [highScoreThinSample, validatedTrend],
  validationSignals,
);

assert(validatedSorted[0].symbol === "002002", "同阶段排序应优先真实快照验证有效的票");

const divergentHighScore = buildStockTrackingProfile(stock({
  symbol: "002003",
  recent_paper_trades: [],
  candidate_tier: "core_action",
  trend_score: 91,
  relative_strength_score: 89,
  sector_strength_score: 87,
  volume_confirmation_score: 84,
  candidate_score: 94,
  startup_signal_score: 90,
}));
const neutralThinSample = buildStockTrackingProfile(stock({
  symbol: "002004",
  recent_paper_trades: [],
  candidate_tier: "core_action",
  trend_score: 70,
  relative_strength_score: 68,
  sector_strength_score: 66,
  volume_confirmation_score: 64,
  candidate_score: 70,
  startup_signal_score: 68,
}));
const divergenceSignals = new Map<string, TrackingSignalItem>([
  [
    "002002",
    validationSignals.get("002002") as TrackingSignalItem,
  ],
  [
    "002003",
    {
      symbol: "002003",
      name: "高分背离",
      industry: "电子",
      latest_snapshot_date: "2026-07-10",
      sample_count: 4,
      score_delta: 8,
      simple_return_pct: -3,
      signal_alignment_key: "score_up_price_weak",
      signal_alignment_label: "分涨价弱",
      signal_alignment_tone: "neutral",
    },
  ],
  [
    "002004",
    {
      symbol: "002004",
      name: "中性薄样本",
      industry: "电子",
      latest_snapshot_date: "2026-07-10",
      sample_count: 1,
      score_delta: null,
      simple_return_pct: null,
      signal_alignment_key: "insufficient",
      signal_alignment_label: "样本不足",
      signal_alignment_tone: "neutral",
    },
  ],
]);
const divergenceSorted = sortStockTrackingProfiles(
  [divergentHighScore, neutralThinSample, validatedTrend],
  divergenceSignals,
);

assert(divergenceSorted.map((item) => item.symbol).join(",") === "002002,002004,002003", "同阶段排序要按分涨价弱语义降权，不能依赖展示色");

function candle(index: number, close: number, amount = 1000): Candle {
  return {
    time: `2026-06-${String(index + 1).padStart(2, "0")}`,
    open: close * 0.99,
    high: close * 1.02,
    low: close * 0.98,
    close,
    volume: amount / close,
    amount,
    ma5: close * 0.99,
    ma10: close * 0.97,
    ma20: close * 0.94,
    ma60: null,
  };
}

const trendCandles = Array.from({ length: 24 }, (_, index) => candle(index, 10 + index * 0.12, 1000 + index * 20));
const trendPath = buildCandleTrendPath(trendCandles);

assert(trendPath.verdictLabel === "趋势延续", "中长期强趋势要识别为趋势延续");
assert(trendPath.metrics.some((item) => item.label === "20日收益"), "趋势路径需要展示20日收益");
assert(trendPath.points.some((item) => item.includes("20日线上方")), "趋势路径要说明是否守住20日线");
assert(trendPath.points.some((item) => item.includes("量能")), "趋势路径要包含量能承接");

const weakCandles = trendCandles.map((item, index) => ({
  ...item,
  close: index < 18 ? item.close : 12.5 - (index - 17) * 0.45,
  high: index < 18 ? item.high : 12.7 - (index - 17) * 0.35,
  low: index < 18 ? item.low : 12.1 - (index - 17) * 0.5,
  ma20: 11.9,
  amount: index >= 18 ? 1800 : item.amount,
}));
const weakPath = buildCandleTrendPath(weakCandles);

assert(weakPath.verdictLabel === "趋势转弱", "跌破20日线且回撤扩大时要识别为趋势转弱");
assert(weakPath.risks.some((item) => item.includes("20日线")), "趋势转弱要提示20日线风险");
assert(weakPath.risks.some((item) => item.includes("回撤")), "趋势转弱要提示回撤风险");
