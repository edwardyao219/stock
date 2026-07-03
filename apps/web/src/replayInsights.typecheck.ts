import type { CandidateReplayEffectReport, LowDimensionalReplayReport } from "./api";
import {
  replayScopeRows,
  replayBreakdownRows,
  replayWeakMonthRows,
  replayStylePreferenceRows,
} from "./replayInsights";

const candidateReplay = {
  start_date: "2025-01-01",
  end_date: "2026-07-01",
  discovery_cache_dir: ".tmp/candidate-replay-discovery-cache",
  diagnosis: {
    horizon: 20,
    primary_scope: "action_long",
    primary_scope_label: "长期行动池",
    policy_label: "核心少量行动",
    ding_policy: "ding_core_only",
    summary: "长期行动池收益质量最好，钉钉继续只推少数核心票。",
    reasons: ["长期行动池：20日均值+5.71%，总收益+102.79%，样本18"],
    monthly_posture: {
      month: "2026-05",
      posture: "tighten_core",
      posture_label: "核心收敛",
      summary: "扩池和普通行动池在最近完整月份拖累收益，长期行动池仍为正。",
      reasons: ["2026-05 全候选池：20日总收益-418.48%，均值-1.67%，样本251"],
      scope_rows: [
        {
          scope: "action_long",
          label: "长期行动池",
          sample_count: 5,
          avg_return: 0.165327,
          win_rate: 0.6,
          total_return: 0.826633,
        },
      ],
    },
    scope_rows: [
      {
        scope: "action_long",
        label: "长期行动池",
        candidate_count: 19,
        sample_count: 18,
        avg_return: 0.057108,
        win_rate: 0.61,
        total_return: 1.027945,
      },
    ],
  },
  scopes: {
    all: {
      start_date: "2025-01-01",
      end_date: "2026-07-01",
      candidate_count: 3398,
      warning_days: 0,
      top_sectors: [],
      style_counts: [],
      selection_mode_counts: [],
      horizons: {
        20: {
          raw: { sample_count: 3000, avg_return: 0.01, win_rate: 0.52, total_return: 30 },
          guarded: { sample_count: 3000, avg_return: 0.008, win_rate: 0.5, total_return: 24 },
        },
      },
      monthly_horizons: {},
      style_horizons: {},
      selection_mode_horizons: {},
      monthly_style_horizons: {},
      monthly_selection_mode_horizons: {},
      style_horizon_preferences: {},
      processed_days: 300,
      excluded_symbols: [],
    },
  },
} satisfies CandidateReplayEffectReport;

const lowDimensional = {
  start_date: "2025-01-01",
  end_date: "2026-07-01",
  processed_days: 300,
  candidate_count: 20,
  warning_days: 0,
  excluded_symbols: [],
  top_sectors: [],
  style_counts: [{ style: "growth_cycle", count: 12 }],
  selection_mode_counts: [{ selection_mode: "potential_watch", count: 8 }],
  horizons: {},
  monthly_horizons: {
    20: {
      "2026-05": {
        raw: { sample_count: 2, avg_return: -0.01, win_rate: 0.5, total_return: -0.02 },
        guarded: { sample_count: 2, avg_return: -0.02, win_rate: 0, total_return: -0.04 },
      },
    },
  },
  style_horizons: {
    20: {
      growth_cycle: {
        raw: { sample_count: 2, avg_return: 0.03, win_rate: 1, total_return: 0.06 },
        guarded: { sample_count: 2, avg_return: 0.025, win_rate: 1, total_return: 0.05 },
      },
    },
  },
  selection_mode_horizons: {
    20: {
      potential_watch: {
        raw: { sample_count: 2, avg_return: 0.04, win_rate: 1, total_return: 0.08 },
        guarded: { sample_count: 2, avg_return: 0.03, win_rate: 1, total_return: 0.06 },
      },
    },
  },
  monthly_style_horizons: {},
  monthly_selection_mode_horizons: {},
  style_horizon_preferences: {
    growth_cycle: {
      preferred_horizon: 20,
      preferred_metric: "guarded_avg_return",
      sample_count: 12,
      avg_return: 0.02,
      total_return: 0.24,
      actionable: true,
      reason: "样本足够且风控后平均收益为正",
    },
  },
} satisfies LowDimensionalReplayReport;

const scopeRows = replayScopeRows(candidateReplay, 20);
const breakdownRows = replayBreakdownRows(lowDimensional, 20, "selection_mode");
const weakRows = replayWeakMonthRows(lowDimensional, 20);
const preferenceRows = replayStylePreferenceRows(lowDimensional);

scopeRows[0].scope satisfies "all" | "action" | "action_long" | string;
breakdownRows[0].label satisfies string;
weakRows[0].month satisfies string;
preferenceRows[0].preferredHorizon satisfies number;
candidateReplay.diagnosis.primary_scope satisfies string;
