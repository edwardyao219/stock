// @ts-ignore Node's experimental TypeScript runner needs the explicit extension.
import { capitalCurveView, monthlyDefenseSignals, monthlyDefenseSimulation, monthlyPerformanceHealth, monthlyPerformanceRows } from "./replayInsights.ts";
import type { CandidateReplayEffectReport, LowDimensionalReplayReport } from "./api";

function assertClose(actual: number | null, expected: number, message: string) {
  if (actual === null || Math.abs(actual - expected) > 0.000001) {
    throw new Error(`${message}: expected ${expected}, got ${String(actual)}`);
  }
}

function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

const report = {
  scopes: {
    action_long: {
      monthly_portfolio_horizons: {
        20: {
          "2026-01": {
            guarded: { sample_count: 2, avg_return: 0.05, win_rate: 1, total_return: 0.1 },
          },
          "2026-02": {
            guarded: { sample_count: 3, avg_return: -0.013333, win_rate: 0.33, total_return: -0.04 },
          },
          "2026-03": {
            guarded: { sample_count: 4, avg_return: 0.0075, win_rate: 0.5, total_return: 0.03 },
          },
        },
      },
      monthly_horizons: {},
    },
  },
} as unknown as CandidateReplayEffectReport;

const rows = monthlyPerformanceRows(report, "action_long", 20);

assertEqual(rows[0].month, "2026-03", "最新月份排在前面");
assertClose(rows[0].monthlyReturn, 0.03, "展示月收益");
assertClose(rows[0].cumulativeReturn, 0.09, "总收益使用简单相加");
assertClose(rows[0].drawdown, -0.01, "回撤基于历史峰值");
assertEqual(rows[0].sampleCount, 4, "保留样本数");
assertClose(rows[1].drawdown, -0.04, "弱月回撤需要看得见");

const healthy = monthlyPerformanceHealth(rows, 0.15);
assertClose(healthy.totalReturn, 0.09, "健康条总收益用最新累计简单收益");
assertClose(healthy.maxDrawdown, -0.04, "健康条展示最深回撤");
assertEqual(healthy.status, "healthy", "回撤未超过15且总收益为正");
assertEqual(healthy.positiveMonths, 2, "统计正收益月份");

const risky = monthlyPerformanceHealth([
  { ...rows[0], cumulativeReturn: -0.08, drawdown: -0.2, monthlyReturn: -0.12 },
  ...rows.slice(1),
], 0.15);
assertEqual(risky.status, "risk", "超过15回撤线要标风险");

const defenseSignals = monthlyDefenseSignals(rows, 0.03, 0.15);
assertEqual(defenseSignals[0].month, "2026-03", "防守信号保持最新月份在前");
assertEqual(defenseSignals[0].status, "normal", "未触发回撤线正常运行");
assertEqual(defenseSignals[1].status, "caution", "超过预警线进入收敛");
assertEqual(defenseSignals[1].actionLabel, "次月核心收敛", "预警后不扩张");

const riskSignals = monthlyDefenseSignals([
  { ...rows[0], drawdown: -0.2, monthlyReturn: -0.12 },
  ...rows.slice(1),
]);
assertEqual(riskSignals[0].status, "risk", "超过15回撤线进入防守");
assertEqual(riskSignals[0].actionLabel, "次月暂停升级", "风险后暂停潜力升级");

const simulated = monthlyDefenseSimulation(rows, 0.03, 0.15);
assertClose(simulated.totalReturn, 0.075, "防守模拟用上月信号调整下月收益");
assertClose(simulated.maxDrawdown, -0.04, "防守模拟回撤按调整后曲线重算");
assertClose(simulated.originalTotalReturn, 0.09, "保留原始简单收益便于对比");
assertClose(simulated.returnGiveback, 0.015, "显示防守牺牲收益");
assertEqual(simulated.months[0].exposure, 0.5, "最新月用上月预警信号半仓");
assertEqual(simulated.months[1].exposure, 1, "预警月本身不倒推降仓");

const riskAdjusted = monthlyDefenseSimulation([
  { ...rows[0], monthlyReturn: 0.06, cumulativeReturn: 0.12, drawdown: -0.01 },
  { ...rows[1], drawdown: -0.2, monthlyReturn: -0.08 },
  rows[2],
], 0.03, 0.15);
assertEqual(riskAdjusted.months[0].exposure, 0, "上月风险后次月暂停升级");

const capitalCurve = capitalCurveView({
  capital_curve_horizons: {
    20: {
      max_positions: 3,
      weighting: "equal_weight_fixed_notional",
      holding_period_days: 20,
      return_calculation: "simple_sum_no_compounding",
      raw: {
        sample_count: 2,
        avg_return: -0.05,
        win_rate: 0.5,
        total_return: -0.1,
        max_drawdown: -0.2,
        max_drawdown_limit_pct: 0.15,
        max_drawdown_passed: false,
        curve: [],
      },
      guarded: {
        sample_count: 2,
        avg_return: -0.01,
        win_rate: 0.5,
        total_return: -0.02,
        max_drawdown: -0.1,
        max_drawdown_limit_pct: 0.15,
        max_drawdown_passed: true,
        curve: [
          { entry_date: "2026-01-03", period_return: 0.08, cumulative_return: 0.08, drawdown: 0 },
          { entry_date: "2026-01-23", period_return: -0.1, cumulative_return: -0.02, drawdown: -0.1 },
        ],
      },
    },
  },
} as unknown as LowDimensionalReplayReport, 20);

assertEqual(capitalCurve?.status, "passed", "15%以内显示通过");
assertEqual(capitalCurve?.points.length, 3, "曲线包含零起点");
assertEqual(capitalCurve?.points[0].x, 0, "曲线从左侧开始");
assertEqual(capitalCurve?.points[2].x, 100, "曲线延伸到右侧");
