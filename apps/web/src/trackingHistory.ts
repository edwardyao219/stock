import type { TrackingSnapshot } from "./api";
import type { TrackingDecision } from "./stockTracking";

export interface TrackingHistorySummaryItem {
  horizon: number;
  label: string;
  latestScore: number | null;
  baseScore: number | null;
  delta: number | null;
  tone: "good" | "warn" | "bad" | "neutral";
  sampleCount: number;
  stageChangeCount: number;
  summary: string;
}

type TrackingTone = "good" | "warn" | "bad" | "neutral";

export interface TrackingPathPoint {
  date: string;
  dateLabel: string;
  score: number;
  stage: string;
  stageLabel: string;
  tone: TrackingTone;
  x: number;
  y: number;
}

export interface TrackingPathSummary {
  sampleCount: number;
  points: TrackingPathPoint[];
  pointString: string;
  latestScore: number | null;
  highScore: number | null;
  lowScore: number | null;
  maxDrawdown: number | null;
  currentDrawdown: number | null;
  stageChangeCount: number;
  stageTrail: string[];
  tone: TrackingTone;
  verdictLabel: string;
  insight: string;
  priceSampleCount: number;
  simpleReturnPct: number | null;
  maxPriceDrawdownPct: number | null;
  outcomeTone: TrackingTone;
  scoreDelta: number | null;
  signalAlignmentLabel: string;
  signalAlignmentTone: TrackingTone;
  signalAlignmentText: string;
}

function scoreTone(delta: number | null): TrackingHistorySummaryItem["tone"] {
  if (delta === null) return "neutral";
  if (delta >= 5) return "good";
  if (delta <= -5) return "bad";
  return "warn";
}

function stageTone(item: Pick<TrackingSnapshot, "stage" | "tracking_score">): TrackingTone {
  if (item.stage === "risk_review") return "bad";
  if (item.stage === "startup_confirming") return "warn";
  if (item.stage === "trend_holding") return "good";
  if ((item.tracking_score ?? 0) >= 70) return "good";
  if ((item.tracking_score ?? 0) < 45) return "bad";
  return "neutral";
}

function stageChangeCount(items: TrackingSnapshot[]) {
  let count = 0;
  for (let index = 1; index < items.length; index += 1) {
    if (items[index]?.stage !== items[index - 1]?.stage) count += 1;
  }
  return count;
}

function summaryText(delta: number | null, sampleCount: number, stageChanges: number) {
  if (delta === null) return `样本 ${sampleCount} 条，继续沉淀`;
  const direction = delta > 0 ? "走强" : delta < 0 ? "走弱" : "持平";
  return `${direction} ${delta >= 0 ? "+" : ""}${delta.toFixed(1)}，阶段切换 ${stageChanges} 次`;
}

export function buildTrackingHistorySummary(
  history: TrackingSnapshot[],
  horizons = [7, 20, 60],
): TrackingHistorySummaryItem[] {
  const oldestFirst = [...history].sort((left, right) =>
    left.snapshot_date.localeCompare(right.snapshot_date),
  );

  return horizons.map((horizon) => {
    const items = oldestFirst.slice(-horizon);
    const latest = items[items.length - 1] ?? null;
    const base = items[0] ?? null;
    const latestScore = latest?.tracking_score ?? null;
    const baseScore = items.length >= 2 ? (base?.tracking_score ?? null) : null;
    const delta =
      latestScore === null || baseScore === null ? null : Number((latestScore - baseScore).toFixed(1));
    const changes = stageChangeCount(items);
    return {
      horizon,
      label: `近${horizon}日`,
      latestScore,
      baseScore,
      delta,
      tone: scoreTone(delta),
      sampleCount: items.length,
      stageChangeCount: changes,
      summary: summaryText(delta, items.length, changes),
    };
  });
}

function sortedOldestFirst(history: TrackingSnapshot[]) {
  return [...history].sort((left, right) => left.snapshot_date.localeCompare(right.snapshot_date));
}

function roundOne(value: number) {
  return Number(value.toFixed(1));
}

function buildStageTrail(items: TrackingSnapshot[]) {
  const trail: string[] = [];
  for (const item of items) {
    const label = item.stage_label || item.stage;
    if (label && trail[trail.length - 1] !== label) trail.push(label);
  }
  return trail;
}

function pathTone(latest: TrackingSnapshot | null, currentDrawdown: number | null): TrackingTone {
  if (!latest) return "neutral";
  if (latest.stage === "risk_review" || (currentDrawdown ?? 0) >= 8) return "bad";
  if (latest.stage === "startup_confirming" || (currentDrawdown ?? 0) >= 4) return "warn";
  if (latest.stage === "trend_holding" || (latest.tracking_score ?? 0) >= 70) return "good";
  return "neutral";
}

function pathVerdict(tone: TrackingTone) {
  if (tone === "good") return "趋势保持";
  if (tone === "warn") return "启动观察";
  if (tone === "bad") return "风险复核";
  return "继续沉淀";
}

function pathInsight(
  sampleCount: number,
  latestScore: number | null,
  currentDrawdown: number | null,
  stageTrail: string[],
) {
  if (sampleCount < 2 || latestScore === null || currentDrawdown === null) return "样本不足，先积累真实快照";
  const stageText = stageTrail.length ? stageTrail.join(" > ") : "阶段暂无变化";
  return `最新 ${latestScore.toFixed(1)}，高点回落 ${currentDrawdown.toFixed(1)}，${stageText}`;
}

function snapshotPrice(item: TrackingSnapshot) {
  const price = item.current_price ?? item.latest_close;
  return price !== null && price > 0 ? price : null;
}

function priceOutcomeTone(simpleReturnPct: number | null, maxDrawdownPct: number | null): TrackingTone {
  if (simpleReturnPct === null) return "neutral";
  if (simpleReturnPct > 0 && (maxDrawdownPct ?? 0) <= 12) return "good";
  if (simpleReturnPct < 0 || (maxDrawdownPct ?? 0) >= 25) return "bad";
  return "warn";
}

function signalAlignment(
  scoreDelta: number | null,
  simpleReturnPct: number | null,
): Pick<TrackingPathSummary, "signalAlignmentLabel" | "signalAlignmentTone" | "signalAlignmentText"> {
  if (scoreDelta === null || simpleReturnPct === null) {
    return {
      signalAlignmentLabel: "样本不足",
      signalAlignmentTone: "neutral",
      signalAlignmentText: "至少需要两条分数和价格快照",
    };
  }
  if (scoreDelta > 0 && simpleReturnPct > 0) {
    return {
      signalAlignmentLabel: "分价同向",
      signalAlignmentTone: "good",
      signalAlignmentText: `追踪分 +${scoreDelta.toFixed(1)}，价格 ${simpleReturnPct.toFixed(1)}%`,
    };
  }
  if (scoreDelta < 0 && simpleReturnPct < 0) {
    return {
      signalAlignmentLabel: "分价同向",
      signalAlignmentTone: "good",
      signalAlignmentText: `追踪分 ${scoreDelta.toFixed(1)}，价格 ${simpleReturnPct.toFixed(1)}%`,
    };
  }
  if (scoreDelta > 0 && simpleReturnPct <= 0) {
    return {
      signalAlignmentLabel: "分涨价弱",
      signalAlignmentTone: "bad",
      signalAlignmentText: `追踪分 +${scoreDelta.toFixed(1)}，价格 ${simpleReturnPct.toFixed(1)}%`,
    };
  }
  if (scoreDelta < 0 && simpleReturnPct >= 0) {
    return {
      signalAlignmentLabel: "分弱价强",
      signalAlignmentTone: "warn",
      signalAlignmentText: `追踪分 ${scoreDelta.toFixed(1)}，价格 ${simpleReturnPct.toFixed(1)}%`,
    };
  }
  return {
    signalAlignmentLabel: "继续观察",
    signalAlignmentTone: "neutral",
    signalAlignmentText: `追踪分 ${scoreDelta.toFixed(1)}，价格 ${simpleReturnPct.toFixed(1)}%`,
  };
}

function streakAlignment(
  items: TrackingSnapshot[],
): Pick<TrackingPathSummary, "signalAlignmentLabel" | "signalAlignmentTone" | "signalAlignmentText"> | null {
  const usable = items.filter(
    (item) => item.tracking_score !== null && snapshotPrice(item) !== null,
  );
  const latestThree = usable.slice(-3);
  if (latestThree.length < 3) return null;

  const moves = [1, 2].map((index) => {
    const previous = latestThree[index - 1];
    const current = latestThree[index];
    return {
      scoreDelta: (current.tracking_score as number) - (previous.tracking_score as number),
      priceDelta: (snapshotPrice(current) as number) - (snapshotPrice(previous) as number),
    };
  });
  const bullishAligned = moves.every((item) => item.scoreDelta > 0 && item.priceDelta > 0);
  if (bullishAligned) {
    return {
      signalAlignmentLabel: "验证延续",
      signalAlignmentTone: "good",
      signalAlignmentText: "最近连续2次追踪分和价格同向走强",
    };
  }
  const scoreUpPriceWeak = moves.every((item) => item.scoreDelta > 0 && item.priceDelta <= 0);
  if (scoreUpPriceWeak) {
    return {
      signalAlignmentLabel: "验证背离",
      signalAlignmentTone: "bad",
      signalAlignmentText: "最近连续2次追踪分上升但价格不跟，先降级复核",
    };
  }
  return null;
}

export function decisionWithValidation(
  decision: TrackingDecision,
  summary: Pick<TrackingPathSummary, "signalAlignmentLabel" | "signalAlignmentTone" | "signalAlignmentText">,
): TrackingDecision {
  if (summary.signalAlignmentLabel === "验证背离") {
    return {
      verdictLabel: "验证背离",
      tone: "bad",
      primaryReasons: [summary.signalAlignmentText, ...decision.primaryReasons].slice(0, 3),
      downgradeReasons: [summary.signalAlignmentText, ...decision.downgradeReasons].slice(0, 3),
      upgradeConditions: ["价格重新跟随追踪分走强", ...decision.upgradeConditions].slice(0, 3),
    };
  }
  if (summary.signalAlignmentLabel === "验证延续" && decision.tone !== "bad") {
    return {
      ...decision,
      verdictLabel: "验证延续",
      tone: "good",
      primaryReasons: [summary.signalAlignmentText, ...decision.primaryReasons].slice(0, 3),
    };
  }
  return decision;
}

export function buildTrackingPathSummary(
  history: TrackingSnapshot[],
  limit = 18,
): TrackingPathSummary {
  const items = sortedOldestFirst(history).slice(-limit);
  const scoredItems = items.filter((item) => item.tracking_score !== null);
  const scores = scoredItems.map((item) => item.tracking_score as number);
  const latest = scoredItems[scoredItems.length - 1] ?? null;
  const latestScore = latest?.tracking_score ?? null;
  const firstScore = scoredItems.length >= 2 ? (scoredItems[0]?.tracking_score ?? null) : null;
  const scoreDelta =
    latestScore === null || firstScore === null ? null : roundOne(latestScore - firstScore);
  const highScore = scores.length ? Math.max(...scores) : null;
  const lowScore = scores.length ? Math.min(...scores) : null;
  const isFlat = highScore !== null && lowScore !== null && highScore === lowScore;
  const span = highScore !== null && lowScore !== null ? Math.max(1, highScore - lowScore) : 1;
  const points = scoredItems.map((item, index) => {
    const score = item.tracking_score as number;
    const x = scoredItems.length <= 1 ? 50 : roundOne((index / (scoredItems.length - 1)) * 100);
    const y = isFlat ? 50 : roundOne(100 - ((score - (lowScore ?? score)) / span) * 100);
    return {
      date: item.snapshot_date,
      dateLabel: item.snapshot_date.slice(5),
      score,
      stage: item.stage,
      stageLabel: item.stage_label,
      tone: stageTone(item),
      x,
      y,
    };
  });

  let runningHigh = scores[0] ?? null;
  let maxDrawdown = 0;
  for (const score of scores) {
    runningHigh = runningHigh === null ? score : Math.max(runningHigh, score);
    maxDrawdown = Math.max(maxDrawdown, runningHigh - score);
  }
  const currentDrawdown =
    highScore === null || latestScore === null ? null : roundOne(highScore - latestScore);
  const stageTrail = buildStageTrail(items);
  const tone = pathTone(latest, currentDrawdown);
  const priceItems = items
    .map((item) => snapshotPrice(item))
    .filter((price): price is number => price !== null);
  const firstPrice = priceItems[0] ?? null;
  const latestPrice = priceItems[priceItems.length - 1] ?? null;
  const simpleReturnPct =
    firstPrice === null || latestPrice === null || priceItems.length < 2
      ? null
      : roundOne(((latestPrice - firstPrice) / firstPrice) * 100);
  let runningHighPrice = priceItems[0] ?? null;
  let maxPriceDrawdownPct = 0;
  for (const price of priceItems) {
    runningHighPrice = runningHighPrice === null ? price : Math.max(runningHighPrice, price);
    if (runningHighPrice > 0) {
      maxPriceDrawdownPct = Math.max(maxPriceDrawdownPct, ((runningHighPrice - price) / runningHighPrice) * 100);
    }
  }
  const roundedMaxPriceDrawdownPct = priceItems.length >= 2 ? roundOne(maxPriceDrawdownPct) : null;
  const alignment = streakAlignment(items) ?? signalAlignment(scoreDelta, simpleReturnPct);

  return {
    sampleCount: items.length,
    points,
    pointString: points.map((point) => `${point.x},${point.y}`).join(" "),
    latestScore,
    highScore: highScore === null ? null : roundOne(highScore),
    lowScore: lowScore === null ? null : roundOne(lowScore),
    maxDrawdown: scores.length ? roundOne(maxDrawdown) : null,
    currentDrawdown,
    stageChangeCount: stageChangeCount(items),
    stageTrail,
    tone,
    verdictLabel: pathVerdict(tone),
    insight: pathInsight(items.length, latestScore, currentDrawdown, stageTrail),
    priceSampleCount: priceItems.length,
    simpleReturnPct,
    maxPriceDrawdownPct: roundedMaxPriceDrawdownPct,
    outcomeTone: priceOutcomeTone(simpleReturnPct, roundedMaxPriceDrawdownPct),
    scoreDelta,
    ...alignment,
  };
}
