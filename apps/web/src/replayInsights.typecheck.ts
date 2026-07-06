import type { CandidateReplayEffectReport, LowDimensionalReplayReport } from "./api";
import {
  replayScopeRows,
  replayBreakdownRows,
  replayWeakMonthRows,
  replayStylePreferenceRows,
  startupPreheatRows,
  replayMonthlyStyleRows,
} from "./replayInsights";

const candidateReplay = {
  start_date: "2024-01-01",
  end_date: "2026-07-01",
  discovery_cache_dir: ".tmp/candidate-replay-discovery-cache",
  data_coverage: {
    start_date: "2024-01-01",
    end_date: "2026-07-01",
    overall: {
      grade: "partial",
      months: 30,
      usable_months: 18,
      warning_months: 12,
      active_symbols: 5200,
      min_trade_days: 10,
      min_active_feature_coverage: 0.7,
      min_sector_rows: 20,
    },
    months: [
      {
        month: "2024-01",
        grade: "partial",
        is_incomplete_tail_month: false,
        trade_days: 22,
        feature_days: 22,
        sector_days: 22,
        avg_daily_bar_symbols: 210,
        avg_feature_symbols: 210,
        avg_sector_rows: 5,
        feature_day_ratio: 1,
        sector_day_ratio: 1,
        avg_market_feature_coverage: 1,
        avg_feature_active_coverage: 0.04,
        warnings: ["2024-01 样本偏窄，只作压力测试。"],
      },
    ],
    warnings: ["2024-01 样本偏窄，只作压力测试。"],
  },
  diagnosis: {
    horizon: 20,
    primary_scope: "action_long",
    primary_scope_label: "长期行动池",
    policy_label: "核心少量行动",
    ding_policy: "ding_core_only",
    summary: "长期行动池收益质量最好，钉钉继续只推少数核心票。",
    reasons: ["长期行动池：20日均值+5.71%，总收益+102.79%，样本18"],
    overfit_guardrails: ["潜力观察池最近月份转强，但此前月份不稳，只作为Web观察。"],
    tactical_opportunities: ["2026-06 潜力观察池10日表现转强，只做Web重点观察。"],
    potential_watch_policy: {
      status: "tactical_watch",
      label: "盘中重点观察",
      month: "2026-06",
      horizon: 10,
      sample_count: 37,
      avg_return: 0.07,
      total_return: 2.65,
      summary: "潜力观察池10日收益转强，只做Web重点观察和盘中确认。",
    },
    market_phase_policy: {
      status: "trend_follow",
      label: "顺势阶段",
      lookback_months: 3,
      strong_months: 2,
      weak_months: 1,
      expansion_allowed: true,
      max_core_positions: 3,
      summary: "最近有效月份连续转强，允许顺势跟随。",
      reasons: [
        "2026-05 全候选池：20日总收益+8.00%，均值+2.00%，样本40",
        "2026-06 全候选池：20日总收益+12.00%，均值+3.00%，样本40",
      ],
    },
    dual_line_policy: {
      active_line: "main_trend",
      ding_policy: "ding_core_main_line",
      max_core_positions: 3,
      summary: "主线生效：强板块趋势和行动池收益同向。",
      main_line: {
        name: "强板块趋势线",
        status: "core_enabled",
        scope: "action_long",
        label: "长期行动池",
        sample_count: 18,
        avg_return: 0.057108,
        total_return: 1.027945,
        summary: "长期行动池20日均值+5.71%。",
      },
      support_line: {
        name: "弱市抗跌/轮动预热线",
        status: "monitor_only",
        month: "2026-06",
        horizon: 10,
        sample_count: 37,
        avg_return: 0.07,
        total_return: 2.65,
        summary: "潜力观察池10日收益转强，只做Web重点观察。",
      },
      rules: ["主线只在顺势阶段承接钉钉核心。"],
    },
    style_gate_policy: {
      scope: "potential_watch",
      horizon: 10,
      lookback_months: 3,
      summary: "按潜力观察池最近月度风格回放做动态门控。",
      upgrade_styles: ["growth_cycle"],
      observe_styles: ["unknown"],
      stand_down_styles: ["cyclical"],
      rows: [
        {
          style: "growth_cycle",
          label: "科技成长",
          status: "upgrade_allowed",
          status_label: "允许潜力升级",
          latest_month: "2026-06",
          latest_sample_count: 6,
          latest_avg_return: 0.12,
          latest_win_rate: 0.67,
          latest_total_return: 0.72,
          recent_months: 2,
          recent_sample_count: 11,
          recent_avg_return: 0.056364,
          recent_total_return: 0.62,
          positive_months: 1,
          negative_months: 1,
          summary: "允许从普通潜力观察升级为Web重点和盘中验证。",
        },
      ],
    },
    startup_preheat_policy: {
      scope: "startup_preheat",
      horizon: 5,
      lookback_months: 3,
      summary: "按启动前夜池最近月度风格回放做动态门控。",
      upgrade_styles: ["growth_cycle"],
      observe_styles: [],
      stand_down_styles: [],
      rows: [
        {
          style: "growth_cycle",
          label: "科技成长",
          status: "upgrade_allowed",
          status_label: "允许潜力升级",
          latest_month: "2026-06",
          latest_sample_count: 5,
          latest_avg_return: 0.05,
          latest_win_rate: 0.6,
          latest_total_return: 0.25,
          recent_months: 2,
          recent_sample_count: 8,
          recent_avg_return: 0.035,
          recent_total_return: 0.28,
          positive_months: 2,
          negative_months: 0,
          summary: "启动前夜池可盘中重点观察，不代表买点。",
        },
      ],
    },
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
      start_date: "2024-01-01",
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
      portfolio_horizons: {
        20: {
          max_positions: 3,
          weighting: "equal_weight_by_signal_day",
          raw: { sample_count: 120, avg_return: 0.01, win_rate: 0.52, total_return: 1.2 },
          guarded: { sample_count: 120, avg_return: 0.008, win_rate: 0.5, total_return: 0.96 },
        },
      },
      monthly_horizons: {},
      monthly_portfolio_horizons: {},
      style_horizons: {},
      selection_mode_horizons: {},
      monthly_style_horizons: {
        10: {
          "2026-06": {
            growth_cycle: {
              raw: { sample_count: 5, avg_return: 0.36, win_rate: 0.8, total_return: 1.8 },
              guarded: { sample_count: 5, avg_return: 0.35, win_rate: 0.8, total_return: 1.75 },
            },
          },
        },
      },
      monthly_selection_mode_horizons: {},
      style_horizon_preferences: {},
      processed_days: 300,
      excluded_symbols: [],
    },
  },
} satisfies CandidateReplayEffectReport;

const lowDimensional = {
  start_date: "2024-01-01",
  end_date: "2026-07-01",
  data_coverage: candidateReplay.data_coverage,
  processed_days: 300,
  candidate_count: 20,
  warning_days: 0,
  excluded_symbols: [],
  top_sectors: [],
  style_counts: [{ style: "growth_cycle", count: 12 }],
  selection_mode_counts: [{ selection_mode: "potential_watch", count: 8 }],
  horizons: {},
  portfolio_horizons: {},
  monthly_horizons: {
    20: {
      "2026-05": {
        raw: { sample_count: 2, avg_return: -0.01, win_rate: 0.5, total_return: -0.02 },
        guarded: { sample_count: 2, avg_return: -0.02, win_rate: 0, total_return: -0.04 },
      },
    },
  },
  monthly_portfolio_horizons: {},
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
const startupRows = startupPreheatRows(candidateReplay);
const monthlyStyleRows = replayMonthlyStyleRows(candidateReplay.scopes.all, 10);

scopeRows[0].scope satisfies "all" | "action" | "action_long" | string;
breakdownRows[0].label satisfies string;
weakRows[0].month satisfies string;
preferenceRows[0].preferredHorizon satisfies number;
startupRows[0].horizon satisfies number;
monthlyStyleRows[0].month satisfies string;
candidateReplay.diagnosis.primary_scope satisfies string;
