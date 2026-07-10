// @ts-ignore Node's experimental TypeScript runner needs the explicit extension.
import { monthlyPerformanceHealth, monthlyPerformanceRows } from "./replayInsights.ts";
import type { CandidateReplayEffectReport } from "./api";

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
