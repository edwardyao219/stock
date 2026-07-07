import type {
  CandidateReplayEffectQuery,
  CandidateReplayEffectReport,
  LowDimensionalReplayReport,
  ReplayReturnSummary,
  ReplayScopeSummary,
  StrategyPkHorizonMetric,
} from "./api";

export const longCandidateReplayQuery = {
  start_date: "2025-01-02",
  end_date: "2026-06-05",
  limit: 15,
  min_coverage_ratio: 0.7,
  include_fundamentals: false,
  use_monthly_shards: true,
} as const satisfies CandidateReplayEffectQuery;

export type ReplayBreakdownGroup = "selection_mode" | "style";
export type ReplayTone = "up" | "down" | "neutral";

export interface ReplayScopeRow {
  scope: string;
  label: string;
  candidateCount: number;
  metric: ReplayReturnSummary | null;
  portfolioMetric: ReplayReturnSummary | null;
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

export interface ReplayMonthlyStyleRow {
  month: string;
  style: string;
  label: string;
  metric: ReplayReturnSummary;
  tone: ReplayTone;
}

export interface StartupPreheatRow {
  horizon: number;
  label: string;
  metric: ReplayReturnSummary | null;
  highSignalMetric: ReplayReturnSummary | null;
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

export interface StrategyPkMetricRow {
  horizon: number;
  label: string;
  metric: StrategyPkHorizonMetric | null;
  tone: ReplayTone;
}

export interface StrategyPkDisplayRow {
  scope: string;
  label: string;
  policy: string;
  policyLabel: string;
  candidateCount: number;
  primaryHorizon: number;
  primaryMetric: StrategyPkHorizonMetric | null;
  horizonMetrics: StrategyPkMetricRow[];
  latestMonth: string | null;
  latestMonthMetric: StrategyPkHorizonMetric | null;
  monthCount: number;
  positiveMonths: number;
  negativeMonths: number;
  worstMonthTotalReturn: number | null;
  bestMonthTotalReturn: number | null;
  rankReason: string;
  tone: ReplayTone;
}

const scopeOrder = [
  "action_long",
  "action",
  "startup_confirmed",
  "startup_preheat",
  "potential_watch",
  "all",
];

const scopeLabels: Record<string, string> = {
  action_long: "长期行动池",
  action: "钉钉行动池",
  startup_confirmed: "启动确认池",
  startup_preheat: "启动前夜池",
  potential_watch: "潜力观察池",
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
  market_beta: "市场弹性",
  theme: "题材",
  unknown: "未分类",
};

const strategyPkPolicyLabels: Record<string, string> = {
  core_candidate: "核心候选",
  tactical_observe: "战术观察",
  observe_only: "只观察",
  low_sample: "样本不足",
  stand_down: "休息",
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

function strategyMetricFallback(
  label: string,
  sampleCount: number,
  avgReturn: number | null,
  winRate: number | null,
  totalReturn: number | null,
): StrategyPkHorizonMetric {
  return {
    metric_label: label,
    sample_count: sampleCount,
    avg_return: avgReturn,
    win_rate: winRate,
    total_return: totalReturn,
  };
}

export function replayScopeRows(
  report: CandidateReplayEffectReport | null,
  horizon: number,
): ReplayScopeRow[] {
  if (!report) return [];
  return sortedScopeEntries(report).map(([scope, summary]) => {
    const metric = summary.horizons[horizon]?.guarded ?? null;
    const portfolioMetric = summary.portfolio_horizons[horizon]?.guarded ?? null;
    return {
      scope,
      label: scopeLabels[scope] ?? "其他候选池",
      candidateCount: summary.candidate_count,
      metric,
      portfolioMetric,
      tone: toneFor(metric?.total_return),
    };
  });
}

export function strategyPkRows(report: CandidateReplayEffectReport | null): StrategyPkDisplayRow[] {
  const strategyPk = report?.diagnosis.strategy_pk;
  if (!strategyPk) return [];
  const horizons = strategyPk.horizons.length ? strategyPk.horizons : [strategyPk.primary_horizon];
  return strategyPk.rows.map((row) => {
    const primaryHorizon = row.primary_horizon || strategyPk.primary_horizon;
    const primaryMetric =
      row.metrics_by_horizon[primaryHorizon] ??
      strategyMetricFallback(
        `${primaryHorizon}日`,
        row.sample_count,
        row.avg_return,
        row.win_rate,
        row.total_return,
      );
    const latestMonthMetric =
      row.latest_month || row.latest_month_sample_count > 0
        ? strategyMetricFallback(
            row.latest_month ?? "最近月",
            row.latest_month_sample_count,
            row.latest_month_avg_return,
            null,
            row.latest_month_total_return,
          )
        : null;
    return {
      scope: row.scope,
      label: row.label || scopeLabels[row.scope] || "其他策略线",
      policy: row.policy,
      policyLabel: row.policy_label || strategyPkPolicyLabels[row.policy] || "未定",
      candidateCount: row.candidate_count,
      primaryHorizon,
      primaryMetric,
      horizonMetrics: horizons.map((horizon) => {
        const metric = row.metrics_by_horizon[horizon] ?? null;
        return {
          horizon,
          label: metric?.metric_label || `${horizon}日`,
          metric,
          tone: toneFor(metric?.total_return),
        };
      }),
      latestMonth: row.latest_month,
      latestMonthMetric,
      monthCount: row.month_count,
      positiveMonths: row.positive_months,
      negativeMonths: row.negative_months,
      worstMonthTotalReturn: row.worst_month_total_return,
      bestMonthTotalReturn: row.best_month_total_return,
      rankReason: row.rank_reason,
      tone: toneFor(primaryMetric.total_return ?? row.total_return ?? row.avg_return),
    };
  });
}

export function startupPreheatRows(report: CandidateReplayEffectReport | null): StartupPreheatRow[] {
  const scope = report?.scopes.startup_preheat;
  return [1, 5, 10].map((horizon) => {
    const metric = scope?.horizons[horizon]?.guarded ?? null;
    const highSignalMetric = scope?.startup_signal_horizons?.[horizon]?.high?.guarded ?? null;
    return {
      horizon,
      label: `${horizon}日`,
      metric,
      highSignalMetric,
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
      label: labels[key] ?? (group === "selection_mode" ? "其他模式" : "其他风格"),
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

export function replayMonthlyStyleRows(
  report: Pick<ReplayScopeSummary, "monthly_style_horizons"> | null | undefined,
  horizon: number,
  month?: string,
): ReplayMonthlyStyleRow[] {
  if (!report) return [];
  const monthlyStyles = report.monthly_style_horizons[horizon] ?? {};
  const selectedMonth =
    month ??
    Object.keys(monthlyStyles)
      .sort()
      .reverse()
      .find((key) =>
        Object.values(monthlyStyles[key] ?? {}).some((item) => item.guarded.sample_count > 0),
      );
  if (!selectedMonth) return [];
  return Object.entries(monthlyStyles[selectedMonth] ?? {})
    .map(([style, item]) => ({
      month: selectedMonth,
      style,
      label: styleLabels[style] ?? "其他风格",
      metric: item.guarded,
      tone: toneFor(item.guarded.total_return),
    }))
    .filter((row) => row.metric.sample_count > 0)
    .sort((left, right) => metricTotal(right.metric) - metricTotal(left.metric));
}

export function replayStylePreferenceRows(
  report: Pick<LowDimensionalReplayReport, "style_horizon_preferences"> | null,
): ReplayStylePreferenceRow[] {
  if (!report) return [];
  return Object.entries(report.style_horizon_preferences)
    .map(([style, item]) => ({
      style,
      label: styleLabels[style] ?? "其他风格",
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
