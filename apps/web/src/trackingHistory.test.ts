// @ts-ignore Node's experimental TypeScript runner needs the explicit extension.
import { buildTrackingHistorySummary } from "./trackingHistory.ts";
import type { TrackingSnapshot } from "./api.ts";

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(message);
}

function snapshot(index: number, stage = "watching"): TrackingSnapshot {
  const day = String(index + 1).padStart(2, "0");
  return {
    symbol: "603893",
    snapshot_date: `2026-05-${day}`,
    stage,
    stage_label: stage === "risk_review" ? "风险复核" : "持续观察",
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
