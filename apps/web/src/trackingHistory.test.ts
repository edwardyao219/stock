// @ts-ignore Node's experimental TypeScript runner needs the explicit extension.
import { buildTrackingHistorySummary, buildTrackingPathSummary, decisionWithValidation } from "./trackingHistory.ts";
import type { TrackingSnapshot } from "./api.ts";
import type { TrackingDecision } from "./stockTracking";

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(message);
}

function snapshot(index: number, stage = "watching"): TrackingSnapshot {
  const day = String(index + 1).padStart(2, "0");
  const stageLabels: Record<string, string> = {
    risk_review: "风险复核",
    startup_confirming: "启动确认",
    trend_holding: "趋势持有",
    watching: "持续观察",
  };
  return {
    symbol: "603893",
    snapshot_date: `2026-05-${day}`,
    stage,
    stage_label: stageLabels[stage] ?? stage,
    tracking_state_key: stage,
    tracking_state_label: stageLabels[stage] ?? stage,
    tracking_state_reason: "测试状态",
    startup_phase_key: stage === "startup_confirming" ? "confirming" : "no_signal",
    startup_phase_label: stage === "startup_confirming" ? "启动确认" : "暂无启动",
    startup_phase_reason: "测试阶段",
    tracking_score: index,
    name: "瑞芯微",
    industry: "半导体",
    sector_style: "growth_cycle",
    latest_trade_date: `2026-05-${day}`,
    latest_close: null,
    current_price: null,
    day_change_pct: null,
    return_5d: null,
    return_20d: null,
    metrics: {},
    evidence: [],
    risks: [],
    source: {},
  };
}

const history = Array.from({ length: 61 }, (_, index) =>
  snapshot(index, index < 30 ? "risk_review" : "watching"),
).reverse();

const summary = buildTrackingHistorySummary(history);

assert(summary.length === 3, "追踪历史摘要需要固定展示 7/20/60 日");
assert(summary[0].label === "近7日", "第一项应该是近7日");
assert(summary[0].delta === 6, "近7日需要比较最新分和窗口起点分");
assert(summary[1].label === "近20日", "第二项应该是近20日");
assert(summary[1].delta === 19, "近20日需要比较最新分和窗口起点分");
assert(summary[2].label === "近60日", "第三项应该是近60日");
assert(summary[2].delta === 59, "近60日需要比较最新分和窗口起点分");
assert(summary[2].stageChangeCount === 1, "摘要需要统计阶段切换次数");

const sparse = buildTrackingHistorySummary([snapshot(1)]);
assert(sparse.every((item) => item.delta === null), "只有一个快照时不能假装有趋势");

const pathHistory = [50, 60, 70, 64, 68, 62].map((score, index) =>
  snapshot(index, index < 2 ? "startup_confirming" : index < 4 ? "trend_holding" : "risk_review"),
).reverse();
pathHistory.forEach((item, index) => {
  item.tracking_score = [62, 68, 64, 70, 60, 50][index];
});

const path = buildTrackingPathSummary(pathHistory, 18);
assert(path.sampleCount === 6, "追踪路径需要使用最近真实快照");
assert(path.points.length === 6, "每个有分数的快照都要生成折线点");
assert(path.points[0].dateLabel === "05-01", "折线点需要按日期从旧到新排序");
assert(path.points[0].score === 50, "最早日期分数需要保留");
assert(path.points[path.points.length - 1]?.score === 62, "最新日期分数需要保留");
assert(path.highScore === 70, "追踪路径需要识别窗口高点");
assert(path.maxDrawdown === 8, "追踪路径需要计算从窗口高点后的最大回落");
assert(path.currentDrawdown === 8, "当前回落需要对比窗口高点");
assert(path.stageTrail.join(" > ") === "启动确认 > 趋势持有 > 风险复核", "阶段轨迹需要去重保序");
assert(path.tone === "bad", "明显回落且最新处于风险复核时应提示风险");

const equalScorePath = buildTrackingPathSummary(
  [snapshot(1), snapshot(0)].map((item) => ({ ...item, tracking_score: 70 })),
  18,
);
assert(
  equalScorePath.points.every((point) => point.y === 50),
  "分数持平时折线应该居中，不能贴底误导成低位",
);

const pricedHistory = [10, 12, 11, 13, 10.4].map((price, index) => ({
  ...snapshot(index),
  current_price: price,
  tracking_score: 60 + index,
})).reverse();
const pricedPath = buildTrackingPathSummary(pricedHistory, 18);
assert(pricedPath.priceSampleCount === 5, "追踪路径需要统计可用价格样本");
assert(pricedPath.simpleReturnPct === 4, "跟踪收益只按首尾快照价格计算，不算复利");
assert(pricedPath.maxPriceDrawdownPct === 20, "价格回撤需要按窗口高点之后的最大跌幅计算");
assert(pricedPath.outcomeTone === "warn", "有收益但回撤较大时需要提示谨慎");
assert(pricedPath.scoreDelta === 4, "信号验证需要统计窗口首尾追踪分变化");
assert(pricedPath.signalAlignmentLabel === "分价同向", "追踪分走强且价格上涨时应该识别为同向");
assert(pricedPath.signalAlignmentTone === "good", "分价同向应该作为有效信号");

const scoreOnlyHistory = [10, 9.6, 9.4].map((price, index) => ({
  ...snapshot(index),
  current_price: price,
  tracking_score: 60 + index * 5,
})).reverse();
const scoreOnlyPath = buildTrackingPathSummary(scoreOnlyHistory, 18);
assert(scoreOnlyPath.signalAlignmentLabel === "验证背离", "连续分涨价弱时需要标记验证背离");
assert(scoreOnlyPath.signalAlignmentTone === "bad", "验证背离不能当成有效信号");
assert(scoreOnlyPath.signalAlignmentText.includes("连续2次"), "验证背离需要说明连续次数");

const alignedStreakHistory = [10, 10.4, 10.9].map((price, index) => ({
  ...snapshot(index),
  current_price: price,
  tracking_score: 60 + index * 5,
})).reverse();
const alignedStreakPath = buildTrackingPathSummary(alignedStreakHistory, 18);
assert(alignedStreakPath.signalAlignmentLabel === "验证延续", "连续分价同向时需要标记验证延续");
assert(alignedStreakPath.signalAlignmentTone === "good", "验证延续应该作为更强的有效信号");

const baseDecision: TrackingDecision = {
  verdictLabel: "继续跟踪",
  tone: "good",
  primaryReasons: ["板块和趋势仍在"],
  downgradeReasons: ["板块转弱时降级"],
  upgradeConditions: ["分价继续同向"],
};
const divergentDecision = decisionWithValidation(baseDecision, scoreOnlyPath);
assert(divergentDecision.verdictLabel === "验证背离", "验证背离要直接覆盖追踪结论");
assert(divergentDecision.tone === "bad", "验证背离后的结论要转为风险色");
assert(divergentDecision.primaryReasons[0].includes("连续2次"), "验证背离原因要放在第一位");

const continuedDecision = decisionWithValidation(
  { ...baseDecision, verdictLabel: "等待确认", tone: "warn" },
  alignedStreakPath,
);
assert(continuedDecision.verdictLabel === "验证延续", "验证延续要强化追踪结论");
assert(continuedDecision.tone === "good", "验证延续后的结论要转为正向色");
