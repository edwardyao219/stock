import type {
  CandidateReplayEffectReport,
  LowDimensionalReplayReport,
  ReplayReturnSummary,
  ReplayScopeSummary,
} from "./api";

export type ReplayBreakdownGroup = "selection_mode" | "style";
export type ReplayTone = "up" | "down" | "neutral";

export interface ReplayScopeRow {
  scope: string;
  label: string;
  candidateCount: number;
  metric: ReplayReturnSummary | null;
  tone: ReplayTone;
}

export interface ReplayBreakdownRow {
  key: string;
  label: string;
  metric: ReplayReturnSummary;
  tone: ReplayTone;
}

export interface ReplayMonthRow {
  month: string;
  metric: ReplayReturnSummary;
  tone: ReplayTone;
}

export interface ReplayStylePreferenceRow {
  style: string;
  label: string;
  preferredHorizon: number;
  sampleCount: number;
  avgReturn: number | null;
  totalReturn: number | null;
  actionable: boolean;
  reason: string;
  tone: ReplayTone;
}

const scopeOrder = ["action_long", "action", "all"];

const scopeLabels: Record<string, string> = {
  action_long: "长期行动池",
  action: "钉钉行动池",
  all: "全候选池",
};

const selectionModeLabels: Record<string, string> = {
  formal_strategy: "正式策略",
  potential_watch: "潜力观察",
  exploration: "强板块探索",
  observation: "观察池",
  low_dimensional_mainline: "低维主线",
  unknown: "未分类",
};

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

function toneFor(value: number | null | undefined): ReplayTone {
  if (value === null || value === undefined || value === 0) return "neutral";
  return value > 0 ? "up" : "down";
}

function metricTotal(metric: ReplayReturnSummary | null | undefined) {
  return metric?.total_return ?? Number.NEGATIVE_INFINITY;
}

function sortedScopeEntries(report: CandidateReplayEffectReport) {
  const entries = Object.entries(report.scopes);
  return entries.sort(([left], [right]) => {
    const leftOrder = scopeOrder.indexOf(left);
    const rightOrder = scopeOrder.indexOf(right);
    if (leftOrder !== -1 || rightOrder !== -1) {
      return (leftOrder === -1 ? scopeOrder.length : leftOrder) - (
        rightOrder === -1 ? scopeOrder.length : rightOrder
      );
    }
    return left.localeCompare(right);
  });
}

export function replayScopeRows(
  report: CandidateReplayEffectReport | null,
  horizon: number,
): ReplayScopeRow[] {
  if (!report) return [];
  return sortedScopeEntries(report).map(([scope, summary]) => {
    const metric = summary.horizons[horizon]?.guarded ?? null;
    return {
      scope,
      label: scopeLabels[scope] ?? scope,
      candidateCount: summary.candidate_count,
      metric,
      tone: toneFor(metric?.total_return),
    };
  });
}

export function replayBreakdownRows(
  report: Pick<ReplayScopeSummary, "selection_mode_horizons" | "style_horizons"> | null,
  horizon: number,
  group: ReplayBreakdownGroup,
): ReplayBreakdownRow[] {
  if (!report) return [];
  const summaries =
    group === "selection_mode"
      ? report.selection_mode_horizons[horizon] ?? {}
      : report.style_horizons[horizon] ?? {};
  const labels = group === "selection_mode" ? selectionModeLabels : styleLabels;
  return Object.entries(summaries)
    .map(([key, item]) => ({
      key,
      label: labels[key] ?? key,
      metric: item.guarded,
      tone: toneFor(item.guarded.total_return),
    }))
    .filter((row) => row.metric.sample_count > 0)
    .sort((left, right) => metricTotal(right.metric) - metricTotal(left.metric));
}

export function replayWeakMonthRows(
  report: Pick<LowDimensionalReplayReport, "monthly_horizons"> | null,
  horizon: number,
  limit = 5,
): ReplayMonthRow[] {
  if (!report) return [];
  return Object.entries(report.monthly_horizons[horizon] ?? {})
    .map(([month, item]) => ({
      month,
      metric: item.guarded,
      tone: toneFor(item.guarded.total_return),
    }))
    .filter((row) => row.metric.sample_count > 0 && (row.metric.total_return ?? 0) < 0)
    .sort((left, right) => metricTotal(left.metric) - metricTotal(right.metric))
    .slice(0, limit);
}

export function replayStylePreferenceRows(
  report: Pick<LowDimensionalReplayReport, "style_horizon_preferences"> | null,
): ReplayStylePreferenceRow[] {
  if (!report) return [];
  return Object.entries(report.style_horizon_preferences)
    .map(([style, item]) => ({
      style,
      label: styleLabels[style] ?? style,
      preferredHorizon: item.preferred_horizon,
      sampleCount: item.sample_count,
      avgReturn: item.avg_return,
      totalReturn: item.total_return,
      actionable: item.actionable,
      reason: item.reason,
      tone: toneFor(item.avg_return),
    }))
    .sort((left, right) => {
      if (left.actionable !== right.actionable) return left.actionable ? -1 : 1;
      return metricTotal({
        sample_count: right.sampleCount,
        avg_return: right.avgReturn,
        win_rate: null,
        total_return: right.totalReturn,
      }) - metricTotal({
        sample_count: left.sampleCount,
        avg_return: left.avgReturn,
        win_rate: null,
        total_return: left.totalReturn,
      });
    });
}
