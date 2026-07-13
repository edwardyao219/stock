import type {
  CandidateReplayEffectQuery,
  CandidateReplayEffectReport,
  LowDimensionalReplayReport,
  ReplayReturnSummary,
  ReplayScopeSummary,
  StrategyPkHorizonMetric,
} from "./api";

function formatReplayDate(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function yesterdayReplayEndDate(today = new Date()) {
  return formatReplayDate(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1));
}

export const longCandidateReplayQuery = {
  start_date: "2024-01-01",
  end_date: yesterdayReplayEndDate(),
  limit: 15,
  min_coverage_ratio: 0.7,
  include_fundamentals: false,
  use_monthly_shards: true,
} as const satisfies CandidateReplayEffectQuery;

export const initialCandidateReplayQuery = longCandidateReplayQuery;

export type ReplayBreakdownGroup = "selection_mode" | "style";
export type ReplayTone = "up" | "down" | "neutral";

export interface CapitalCurveView {
  status: "passed" | "failed";
  defensiveStatus: "passed" | "failed";
  metric: NonNullable<LowDimensionalReplayReport["capital_curve_horizons"]>[number]["guarded"];
  defensiveMetric: NonNullable<LowDimensionalReplayReport["capital_curve_horizons"]>[number]["defensive_breadth"];
  points: Array<{ x: number; y: number; value: number }>;
  pointString: string;
  defensivePoints: Array<{ x: number; y: number; value: number }>;
  defensivePointString: string;
}

export function capitalCurveView(
  report: Pick<LowDimensionalReplayReport, "capital_curve_horizons"> | null,
  horizon: number,
): CapitalCurveView | null {
  const horizonSummary = report?.capital_curve_horizons?.[horizon];
  const metric = horizonSummary?.guarded;
  const defensiveMetric = horizonSummary?.defensive_breadth;
  if (!metric || !defensiveMetric) return null;
  const values = [0, ...metric.curve.map((point) => point.cumulative_return)];
  const defensiveValues = [
    0,
    ...defensiveMetric.curve.map((point) => point.cumulative_return),
  ];
  const low = Math.min(...values, ...defensiveValues);
  const high = Math.max(...values, ...defensiveValues);
  const spread = high - low || 1;
  const chartPoints = (items: number[]) => {
    const lastIndex = Math.max(1, items.length - 1);
    return items.map((value, index) => ({
      x: Math.round((2 + (index / lastIndex) * 96) * 100) / 100,
      y: Math.round((92 - ((value - low) / spread) * 84) * 100) / 100,
      value,
    }));
  };
  const points = chartPoints(values);
  const defensivePoints = chartPoints(defensiveValues);
  return {
    status: metric.max_drawdown_passed ? "passed" : "failed",
    defensiveStatus: defensiveMetric.max_drawdown_passed ? "passed" : "failed",
    metric,
    defensiveMetric,
    points,
    pointString: points.map((point) => `${point.x},${point.y}`).join(" "),
    defensivePoints,
    defensivePointString: defensivePoints
      .map((point) => `${point.x},${point.y}`)
      .join(" "),
  };
}

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

export type StartupSignalReplayPosture = "observe" | "verify" | "stand_down";

export interface StartupSignalReplayRow {
  horizon: number;
  label: string;
  baselineMetric: ReplayReturnSummary | null;
  highSignalMetric: ReplayReturnSummary | null;
  lowSignalMetric: ReplayReturnSummary | null;
  liftAvgReturn: number | null;
  liftTotalReturn: number | null;
  posture: StartupSignalReplayPosture;
  postureLabel: string;
  guidance: string;
  tone: ReplayTone;
}

export interface StartupSignalStyleReplayRow {
  style: string;
  label: string;
  horizon: number;
  baselineMetric: ReplayReturnSummary | null;
  highSignalMetric: ReplayReturnSummary | null;
  lowSignalMetric: ReplayReturnSummary | null;
  liftAvgReturn: number | null;
  posture: StartupSignalReplayPosture;
  postureLabel: string;
  guidance: string;
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
  monthlyPositiveRatio: number | null;
  monthlyMaxDrawdown: number | null;
  returnDrawdownRatio: number | null;
  avgMonthlySampleCount: number | null;
  worstMonthTotalReturn: number | null;
  bestMonthTotalReturn: number | null;
  rankReason: string;
  tone: ReplayTone;
}

export interface DualLineLongReplayLine<
  TScope extends "action_long" | "startup_preheat" = "action_long" | "startup_preheat",
  TLabel extends "长期行动池" | "启动前夜池" = "长期行动池" | "启动前夜池",
> {
  scope: TScope;
  label: TLabel;
  role: string;
  metric: ReplayReturnSummary | null;
  portfolioMetric: ReplayReturnSummary | null;
  displayMetric: ReplayReturnSummary | null;
  tone: ReplayTone;
}

export interface DualLineLongReplaySummary {
  horizon: number;
  mainLine: DualLineLongReplayLine<"action_long", "长期行动池">;
  supportLine: DualLineLongReplayLine<"startup_preheat", "启动前夜池">;
  qualityLeader: "main" | "support" | "none";
  coverageLeader: "main" | "support" | "none";
  guidance: string;
}

export interface CandidateGateSummary {
  title: string;
  reason: string;
  postureText: string;
  coreLimitText: string;
  dingPolicyText: string;
  mainLineText: string;
  supportLineText: string;
  styleGateText: string | null;
}

export type MonthlyStrategyPkScope = "action_long" | "startup_preheat" | "potential_watch";
export type MonthlyStrategyPkPosture = "core_available" | "observe_only" | "risk_off";

export interface MonthlyStrategyPkLine {
  scope: MonthlyStrategyPkScope;
  label: string;
  role: string;
  metric: ReplayReturnSummary | null;
  tone: ReplayTone;
}

export interface MonthlyStrategyPkRow {
  month: string;
  lines: MonthlyStrategyPkLine[];
  leaderScope: MonthlyStrategyPkScope | "none";
  leaderLabel: string;
  leaderTotalReturn: number | null;
  worstLineLabel: string;
  worstTotalReturn: number | null;
  posture: MonthlyStrategyPkPosture;
  postureLabel: string;
  guidance: string;
  tone: ReplayTone;
}

export interface MonthlyPerformanceRow {
  month: string;
  label: string;
  monthlyReturn: number | null;
  cumulativeReturn: number;
  drawdown: number;
  sampleCount: number;
  tone: ReplayTone;
}

export interface MonthlyPerformanceHealth {
  totalReturn: number | null;
  maxDrawdown: number | null;
  positiveMonths: number;
  monthCount: number;
  drawdownLimit: number;
  status: "empty" | "healthy" | "weak" | "risk";
  statusLabel: string;
}

export interface MonthlyDefenseSignal {
  month: string;
  monthlyReturn: number | null;
  drawdown: number;
  status: "normal" | "caution" | "risk";
  statusLabel: string;
  actionLabel: string;
  reason: string;
  tone: ReplayTone;
}

export interface MonthlyDefenseSimulationMonth {
  month: string;
  exposure: number;
  monthlyReturn: number | null;
  adjustedReturn: number | null;
  cumulativeReturn: number;
  drawdown: number;
  tone: ReplayTone;
}

export interface MonthlyDefenseSimulation {
  totalReturn: number | null;
  maxDrawdown: number | null;
  originalTotalReturn: number | null;
  originalMaxDrawdown: number | null;
  returnGiveback: number | null;
  drawdownImprovement: number | null;
  status: "empty" | "improved" | "unchanged" | "worse";
  statusLabel: string;
  months: MonthlyDefenseSimulationMonth[];
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

const dingPolicyLabels: Record<string, string> = {
  ding_core_only: "只推核心",
  ding_action_selective: "行动精选",
  ding_core_main_line: "主线核心推送",
  ding_core_selective: "精选核心推送",
  web_observe_only: "网页端观察",
  web_support_only: "辅线只在网页端观察",
  hold: "暂停推送",
};

const lineStatusLabels: Record<string, string> = {
  core_enabled: "核心生效",
  monitor_only: "仅观察",
  web_preheat: "网页端预热",
  selective_core: "精选核心",
  paused: "暂停",
  stand_down: "暂停观察",
};

export function dingPolicyText(value: string | null | undefined) {
  if (!value) return "未定";
  return dingPolicyLabels[value] ?? "未定策略";
}

export function lineStatusText(value: string | null | undefined) {
  if (!value) return "未定";
  return lineStatusLabels[value] ?? "未定状态";
}

function toneFor(value: number | null | undefined): ReplayTone {
  if (value === null || value === undefined || value === 0) return "neutral";
  return value > 0 ? "up" : "down";
}

function percentText(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
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

function scopeMetric(
  report: CandidateReplayEffectReport,
  scope: "action_long" | "startup_preheat",
  horizon: number,
) {
  const summary = report.scopes[scope];
  const metric = summary?.horizons[horizon]?.guarded ?? null;
  const portfolioMetric = summary?.portfolio_horizons[horizon]?.guarded ?? null;
  return {
    metric,
    portfolioMetric,
    displayMetric: portfolioMetric ?? metric,
  };
}

function leaderByMetric(
  mainValue: number | null | undefined,
  supportValue: number | null | undefined,
) {
  if (mainValue === null || mainValue === undefined || supportValue === null || supportValue === undefined) {
    return "none";
  }
  if (mainValue === supportValue) return "none";
  return mainValue > supportValue ? "main" : "support";
}

const monthlyStrategyPkScopes: Array<{
  scope: MonthlyStrategyPkScope;
  label: string;
  role: string;
}> = [
  { scope: "action_long", label: "长期行动池", role: "核心少量" },
  { scope: "startup_preheat", label: "启动前夜池", role: "观察预热" },
  { scope: "potential_watch", label: "潜力观察池", role: "扩散观察" },
];

function monthlyScopeMetric(
  report: CandidateReplayEffectReport,
  scope: MonthlyStrategyPkScope,
  month: string,
  horizon: number,
) {
  const summary = report.scopes[scope];
  return (
    summary?.monthly_portfolio_horizons[horizon]?.[month]?.guarded
    ?? summary?.monthly_horizons[horizon]?.[month]?.guarded
    ?? null
  );
}

export function monthlyPerformanceRows(
  report: CandidateReplayEffectReport | null,
  scope: MonthlyStrategyPkScope = "action_long",
  horizon = 20,
  limit = 8,
): MonthlyPerformanceRow[] {
  const summary = report?.scopes[scope];
  if (!summary) return [];
  const portfolioMonths = summary.monthly_portfolio_horizons[horizon] ?? {};
  const singleMonths = summary.monthly_horizons[horizon] ?? {};
  const months = [...new Set([...Object.keys(singleMonths), ...Object.keys(portfolioMonths)])].sort();
  const rows: MonthlyPerformanceRow[] = [];
  let cumulativeReturn = 0;
  let peakReturn = 0;

  for (const month of months) {
    const metric = portfolioMonths[month]?.guarded ?? singleMonths[month]?.guarded ?? null;
    const sampleCount = metric?.sample_count ?? 0;
    if (sampleCount <= 0) continue;
    const monthlyReturn = metric?.total_return ?? null;
    cumulativeReturn += monthlyReturn ?? 0;
    peakReturn = Math.max(peakReturn, cumulativeReturn);
    rows.push({
      month,
      label: scopeLabels[scope] ?? "策略线",
      monthlyReturn,
      cumulativeReturn,
      drawdown: cumulativeReturn - peakReturn,
      sampleCount,
      tone: toneFor(monthlyReturn),
    });
  }

  return rows.reverse().slice(0, limit);
}

export function monthlyPerformanceHealth(
  rows: MonthlyPerformanceRow[],
  drawdownLimit = 0.15,
): MonthlyPerformanceHealth {
  const limit = Math.abs(drawdownLimit);
  if (!rows.length) {
    return {
      totalReturn: null,
      maxDrawdown: null,
      positiveMonths: 0,
      monthCount: 0,
      drawdownLimit: limit,
      status: "empty",
      statusLabel: "样本不足",
    };
  }

  const totalReturn = rows[0].cumulativeReturn;
  const maxDrawdown = Math.min(...rows.map((row) => row.drawdown));
  const positiveMonths = rows.filter((row) => (row.monthlyReturn ?? 0) > 0).length;
  const status = maxDrawdown < -limit ? "risk" : totalReturn > 0 ? "healthy" : "weak";
  return {
    totalReturn,
    maxDrawdown,
    positiveMonths,
    monthCount: rows.length,
    drawdownLimit: limit,
    status,
    statusLabel: status === "risk" ? "回撤超线" : status === "healthy" ? "趋势健康" : "收益偏弱",
  };
}

export function monthlyDefenseSignals(
  rows: MonthlyPerformanceRow[],
  warningLimit = 0.1,
  riskLimit = 0.15,
  limit = 6,
): MonthlyDefenseSignal[] {
  const warning = Math.abs(warningLimit);
  const risk = Math.abs(riskLimit);
  return rows.slice(0, limit).map((row) => {
    const status = row.drawdown <= -risk ? "risk" : row.drawdown <= -warning ? "caution" : "normal";
    return {
      month: row.month,
      monthlyReturn: row.monthlyReturn,
      drawdown: row.drawdown,
      status,
      statusLabel: status === "risk" ? "防守" : status === "caution" ? "收敛" : "正常",
      actionLabel: status === "risk" ? "次月暂停升级" : status === "caution" ? "次月核心收敛" : "次月正常跟随",
      reason: `月收益 ${percentText(row.monthlyReturn)} / 回撤 ${percentText(row.drawdown)}`,
      tone: status === "risk" ? "down" : status === "caution" ? "neutral" : row.tone,
    };
  });
}

function exposureAfterSignal(status: MonthlyDefenseSignal["status"]) {
  if (status === "risk") return 0;
  if (status === "caution") return 0.5;
  return 1;
}

export function monthlyDefenseSimulation(
  rows: MonthlyPerformanceRow[],
  warningLimit = 0.1,
  riskLimit = 0.15,
): MonthlyDefenseSimulation {
  if (!rows.length) {
    return {
      totalReturn: null,
      maxDrawdown: null,
      originalTotalReturn: null,
      originalMaxDrawdown: null,
      returnGiveback: null,
      drawdownImprovement: null,
      status: "empty",
      statusLabel: "样本不足",
      months: [],
    };
  }

  const chronological = [...rows].reverse();
  let cumulativeReturn = 0;
  let peakReturn = 0;
  let previousSignal: MonthlyDefenseSignal["status"] = "normal";
  const months: MonthlyDefenseSimulationMonth[] = [];

  for (const row of chronological) {
    const exposure = exposureAfterSignal(previousSignal);
    const adjustedReturn = row.monthlyReturn === null ? null : row.monthlyReturn * exposure;
    cumulativeReturn += adjustedReturn ?? 0;
    peakReturn = Math.max(peakReturn, cumulativeReturn);
    months.push({
      month: row.month,
      exposure,
      monthlyReturn: row.monthlyReturn,
      adjustedReturn,
      cumulativeReturn,
      drawdown: cumulativeReturn - peakReturn,
      tone: toneFor(adjustedReturn),
    });
    const [signal] = monthlyDefenseSignals([row], warningLimit, riskLimit, 1);
    previousSignal = signal?.status ?? "normal";
  }

  const original = monthlyPerformanceHealth(rows, riskLimit);
  const maxDrawdown = Math.min(...months.map((month) => month.drawdown));
  const totalReturn = months[months.length - 1]?.cumulativeReturn ?? null;
  const originalTotalReturn = original.totalReturn;
  const originalMaxDrawdown = original.maxDrawdown;
  const returnGiveback = originalTotalReturn === null || totalReturn === null
    ? null
    : originalTotalReturn - totalReturn;
  const drawdownImprovement = originalMaxDrawdown === null ? null : maxDrawdown - originalMaxDrawdown;
  const status = drawdownImprovement === null
    ? "empty"
    : drawdownImprovement > 0.000001
      ? "improved"
      : drawdownImprovement < -0.000001
        ? "worse"
        : "unchanged";
  return {
    totalReturn,
    maxDrawdown,
    originalTotalReturn,
    originalMaxDrawdown,
    returnGiveback,
    drawdownImprovement,
    status,
    statusLabel: status === "improved" ? "回撤改善" : status === "worse" ? "回撤变差" : "效果持平",
    months: months.reverse(),
  };
}

function hasPositiveMetric(metric: ReplayReturnSummary | null | undefined) {
  if (!metric) return false;
  return (metric.sample_count ?? 0) > 0
    && (metric.avg_return ?? 0) > 0
    && (metric.total_return ?? 0) > 0;
}

function gateTitle(coreLimit: number, dingPolicy: string) {
  if (coreLimit <= 0 || dingPolicy.startsWith("web_") || dingPolicy === "hold") {
    return "今天先观察，不推核心";
  }
  if (coreLimit === 1) return "今天核心收敛，少量跟踪";
  return "今天主线可用，核心少量行动";
}

function styleGateText(report: CandidateReplayEffectReport) {
  const rows = report.diagnosis.style_gate_policy.rows;
  const upgradeLabels = rows
    .filter((row) => row.status === "upgrade_allowed")
    .map((row) => row.label || styleLabels[row.style] || "其他风格");
  if (!upgradeLabels.length) return "暂无风格允许升级，潜力票只做观察。";
  return `可升级风格：${upgradeLabels.slice(0, 3).join("、")}；其余风格先观察。`;
}

export function candidateGateSummary(
  report: CandidateReplayEffectReport,
  blockReason?: string | null,
): CandidateGateSummary {
  const market = report.diagnosis.market_phase_policy;
  const dualLine = report.diagnosis.dual_line_policy;
  const coreLimit = Math.max(0, Math.min(market.max_core_positions, dualLine.max_core_positions));
  return {
    title: gateTitle(coreLimit, dualLine.ding_policy),
    reason: blockReason || dualLine.summary || market.summary,
    postureText: `${market.label}：${market.summary}`,
    coreLimitText: `钉钉核心上限 ${coreLimit} 只，网页端保留观察和盘中验证。`,
    dingPolicyText: `钉钉策略：${dingPolicyText(dualLine.ding_policy)}`,
    mainLineText: `主线：${lineStatusText(dualLine.main_line.status)} / ${dualLine.main_line.summary}`,
    supportLineText: `辅线：${lineStatusText(dualLine.support_line.status)} / ${
      dualLine.support_line.summary ?? "暂无预热信号"
    }`,
    styleGateText: styleGateText(report),
  };
}

function metricDiff(
  left: ReplayReturnSummary | null | undefined,
  right: ReplayReturnSummary | null | undefined,
  key: "avg_return" | "total_return",
) {
  const leftValue = left?.[key];
  const rightValue = right?.[key];
  if (leftValue === null || leftValue === undefined || rightValue === null || rightValue === undefined) {
    return null;
  }
  return leftValue - rightValue;
}

function monthlyStrategyPosture(lines: MonthlyStrategyPkLine[]) {
  const coreMetric = lines.find((line) => line.scope === "action_long")?.metric ?? null;
  const hasSupportPositive = lines.some(
    (line) => line.scope !== "action_long" && hasPositiveMetric(line.metric),
  );
  if (hasPositiveMetric(coreMetric)) {
    return {
      posture: "core_available" as const,
      postureLabel: "核心可用",
      guidance: "核心线为主，启动线和潜力线只做辅助观察。",
      tone: "up" as const,
    };
  }
  if (hasSupportPositive) {
    return {
      posture: "observe_only" as const,
      postureLabel: "只观察",
      guidance: "核心线不占优，启动和潜力线只做观察与盘中确认。",
      tone: "neutral" as const,
    };
  }
  return {
    posture: "risk_off" as const,
    postureLabel: "降低频率",
    guidance: "三条线都没有正向证据，优先降低交易频率。",
    tone: "down" as const,
  };
}

export function monthlyStrategyPkRows(
  report: CandidateReplayEffectReport | null,
  horizon = 20,
  limit = 6,
): MonthlyStrategyPkRow[] {
  if (!report) return [];
  const months = new Set<string>();
  for (const { scope } of monthlyStrategyPkScopes) {
    const summary = report.scopes[scope];
    for (const month of Object.keys(summary?.monthly_portfolio_horizons[horizon] ?? {})) {
      months.add(month);
    }
    for (const month of Object.keys(summary?.monthly_horizons[horizon] ?? {})) {
      months.add(month);
    }
  }
  return [...months]
    .sort()
    .reverse()
    .map((month) => {
      const lines: MonthlyStrategyPkLine[] = monthlyStrategyPkScopes.map((item) => {
        const metric = monthlyScopeMetric(report, item.scope, month, horizon);
        return {
          ...item,
          metric,
          tone: toneFor(metric?.avg_return),
        };
      });
      const validLines = lines.filter((line) => (line.metric?.sample_count ?? 0) > 0);
      const returnLines = validLines.filter(
        (line) => line.metric?.total_return !== null && line.metric?.total_return !== undefined,
      );
      const leader = validLines.reduce<MonthlyStrategyPkLine | null>((best, line) => {
        if (!hasPositiveMetric(line.metric)) return best;
        if (!best) return line;
        return (line.metric?.total_return ?? Number.NEGATIVE_INFINITY)
          > (best.metric?.total_return ?? Number.NEGATIVE_INFINITY)
          ? line
          : best;
      }, null);
      const worstLine = returnLines.reduce<MonthlyStrategyPkLine | null>((worst, line) => {
        if (!worst) return line;
        return (line.metric?.total_return ?? Number.POSITIVE_INFINITY)
          < (worst.metric?.total_return ?? Number.POSITIVE_INFINITY)
          ? line
          : worst;
      }, null);
      const leaderScope: MonthlyStrategyPkScope | "none" = leader?.scope ?? "none";
      const posture = monthlyStrategyPosture(lines);
      return {
        month,
        lines,
        leaderScope,
        leaderLabel: leader?.label ?? "无明显领先",
        leaderTotalReturn: leader?.metric?.total_return ?? null,
        worstLineLabel: worstLine?.label ?? "无样本",
        worstTotalReturn: worstLine?.metric?.total_return ?? null,
        ...posture,
      };
    })
    .filter((row) => row.lines.some((line) => (line.metric?.sample_count ?? 0) > 0))
    .slice(0, limit);
}

export function dualLineLongReplaySummary(
  report: CandidateReplayEffectReport | null,
  horizon = 20,
): DualLineLongReplaySummary | null {
  if (!report?.scopes.action_long || !report.scopes.startup_preheat) return null;
  const mainMetrics = scopeMetric(report, "action_long", horizon);
  const supportMetrics = scopeMetric(report, "startup_preheat", horizon);
  const mainLine: DualLineLongReplayLine<"action_long", "长期行动池"> = {
    scope: "action_long",
    label: "长期行动池",
    role: "核心少量",
    ...mainMetrics,
    tone: toneFor(mainMetrics.displayMetric?.avg_return),
  };
  const supportLine: DualLineLongReplayLine<"startup_preheat", "启动前夜池"> = {
    scope: "startup_preheat",
    label: "启动前夜池",
    role: "观察预热",
    ...supportMetrics,
    tone: toneFor(supportMetrics.displayMetric?.avg_return),
  };
  const qualityLeader = leaderByMetric(
    mainLine.displayMetric?.avg_return,
    supportLine.displayMetric?.avg_return,
  );
  const coverageLeader = leaderByMetric(
    mainLine.displayMetric?.sample_count,
    supportLine.displayMetric?.sample_count,
  );
  return {
    horizon,
    mainLine,
    supportLine,
    qualityLeader,
    coverageLeader,
    guidance:
      qualityLeader === "main"
        ? "核心线看均值质量，启动线看机会覆盖；启动线只做观察和盘中确认。"
        : "启动线更活跃时也先观察，只有个股趋势、量能和风控同时确认才考虑升级。",
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
      monthlyPositiveRatio: row.monthly_positive_ratio,
      monthlyMaxDrawdown: row.monthly_max_drawdown,
      returnDrawdownRatio: row.return_drawdown_ratio,
      avgMonthlySampleCount: row.avg_monthly_sample_count,
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

function startupSignalPosture(
  highSignalMetric: ReplayReturnSummary | null,
  liftAvgReturn: number | null,
) {
  if (!highSignalMetric || (highSignalMetric.sample_count ?? 0) <= 0) {
    return {
      posture: "stand_down" as const,
      postureLabel: "样本不足",
      guidance: "高分启动组样本不足，先不作为筛选依据。",
      tone: "neutral" as const,
    };
  }
  if (hasPositiveMetric(highSignalMetric) && (liftAvgReturn === null || liftAvgReturn > 0)) {
    return {
      posture: "observe" as const,
      postureLabel: "值得观察",
      guidance: "高分启动组有正向证据，适合提前一天放入观察和盘中确认。",
      tone: "up" as const,
    };
  }
  if (hasPositiveMetric(highSignalMetric)) {
    return {
      posture: "verify" as const,
      postureLabel: "谨慎观察",
      guidance: "高分启动组为正但相对优势不明显，只做辅助确认。",
      tone: "neutral" as const,
    };
  }
  return {
    posture: "stand_down" as const,
    postureLabel: "暂缓",
    guidance: "高分启动组没有正向证据，降低使用频率。",
    tone: "down" as const,
  };
}

export function startupSignalReplayRows(
  report: CandidateReplayEffectReport | null,
  horizons: number[] = [1, 5, 10, 20],
): StartupSignalReplayRow[] {
  const scope = report?.scopes.startup_preheat;
  if (!scope) return [];
  return horizons
    .map((horizon) => {
      const baselineMetric = scope.horizons[horizon]?.guarded ?? null;
      const highSignalMetric = scope.startup_signal_horizons?.[horizon]?.high?.guarded ?? null;
      const lowSignalMetric = scope.startup_signal_horizons?.[horizon]?.low?.guarded ?? null;
      const liftAvgReturn = metricDiff(highSignalMetric, baselineMetric, "avg_return");
      const liftTotalReturn = metricDiff(highSignalMetric, baselineMetric, "total_return");
      const posture = startupSignalPosture(highSignalMetric, liftAvgReturn);
      return {
        horizon,
        label: horizon === 1 ? "次日" : `${horizon}日`,
        baselineMetric,
        highSignalMetric,
        lowSignalMetric,
        liftAvgReturn,
        liftTotalReturn,
        ...posture,
      };
    })
    .filter(
      (row) =>
        (row.baselineMetric?.sample_count ?? 0) > 0
        || (row.highSignalMetric?.sample_count ?? 0) > 0
        || (row.lowSignalMetric?.sample_count ?? 0) > 0,
    );
}

export function startupSignalStyleReplayRows(
  report: CandidateReplayEffectReport | null,
  horizon = 20,
  limit = 5,
): StartupSignalStyleReplayRow[] {
  const scope = report?.scopes.startup_preheat;
  if (!scope) return [];
  const styleBuckets = scope.startup_signal_style_horizons?.[horizon] ?? {};
  return Object.entries(styleBuckets)
    .map(([style, buckets]) => {
      const baselineMetric = scope.style_horizons[horizon]?.[style]?.guarded ?? null;
      const highSignalMetric = buckets.high?.guarded ?? null;
      const lowSignalMetric = buckets.low?.guarded ?? null;
      const liftAvgReturn = metricDiff(highSignalMetric, baselineMetric, "avg_return");
      const posture = startupSignalPosture(highSignalMetric, liftAvgReturn);
      const label = styleLabels[style] ?? "其他风格";
      return {
        style,
        label,
        horizon,
        baselineMetric,
        highSignalMetric,
        lowSignalMetric,
        liftAvgReturn,
        ...posture,
        guidance:
          posture.posture === "observe"
            ? `${label}里的高分启动信号更值得提前观察，仍需盘中承接确认。`
            : posture.guidance,
      };
    })
    .filter((row) => (row.highSignalMetric?.sample_count ?? 0) > 0)
    .sort((left, right) => {
      const leftObserve = left.posture === "observe" ? 1 : 0;
      const rightObserve = right.posture === "observe" ? 1 : 0;
      if (leftObserve !== rightObserve) return rightObserve - leftObserve;
      return metricTotal(right.highSignalMetric) - metricTotal(left.highSignalMetric);
    })
    .slice(0, limit);
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
