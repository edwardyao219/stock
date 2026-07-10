import type { TrackingSnapshot } from "./api";

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

function scoreTone(delta: number | null): TrackingHistorySummaryItem["tone"] {
  if (delta === null) return "neutral";
  if (delta >= 5) return "good";
  if (delta <= -5) return "bad";
  return "warn";
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
