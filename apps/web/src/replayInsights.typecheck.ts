import type { CandidateReplayEffectReport, LowDimensionalReplayReport } from "./api";
import {
  dualLineLongReplaySummary,
  initialCandidateReplayQuery,
  longCandidateReplayQuery,
  monthlyStrategyPkRows,
  replayScopeRows,
  replayBreakdownRows,
  replayWeakMonthRows,
  replayStylePreferenceRows,
  strategyPkRows,
  startupSignalStyleReplayRows,
  startupSignalReplayRows,
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
    market_stress_gate_policy: {
      status: "effective_defense",
      label: "压力门控有效",
      horizon: 20,
      lookback_months: 2,
      weak_months: 2,
      defended_months: 2,
      best_core_scope: "action_long",
      best_core_label: "长期行动池",
      max_core_positions: 1,
      avoided_total_loss: 3.08,
      summary: "弱月收缩有效：核心行动池相对全候选池明显少亏或转正，压力大时继续少做。",
      rows: [
        {
          month: "2026-05",
          all_sample_count: 80,
          all_total_return: -2.4,
          core_scope: "action_long",
          core_label: "长期行动池",
          core_sample_count: 3,
          core_total_return: 0.03,
          avoided_loss: 2.43,
        },
      ],
      reasons: ["2026-05 全候选20日总收益-240.00%，长期行动池+3.00%，改善+243.00%"],
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
    strategy_pk: {
      return_mode: "simple_sum_no_compounding",
      horizons: [5, 10, 20],
      primary_horizon: 20,
      summary: "长期行动池作为主线，启动前夜池只做盘中观察。",
      rules: ["先看板块再看个股，策略PK只用于动态定位。"],
      rows: [
        {
          scope: "action_long",
          label: "长期行动池",
          policy: "core_candidate",
          policy_label: "核心候选",
          candidate_count: 19,
          primary_horizon: 20,
          sample_count: 18,
          avg_return: 0.057108,
          win_rate: 0.61,
          total_return: 1.027945,
          metrics_by_horizon: {
            5: {
              metric_label: "5日",
              sample_count: 18,
              avg_return: 0.02,
              win_rate: 0.56,
              total_return: 0.36,
            },
            10: {
              metric_label: "10日",
              sample_count: 18,
              avg_return: 0.04,
              win_rate: 0.61,
              total_return: 0.72,
            },
            20: {
              metric_label: "20日",
              sample_count: 18,
              avg_return: 0.057108,
              win_rate: 0.61,
              total_return: 1.027945,
            },
          },
          latest_month: "2026-06",
          latest_month_sample_count: 5,
          latest_month_avg_return: 0.08,
          latest_month_total_return: 0.4,
          month_count: 5,
          positive_months: 4,
          negative_months: 1,
          monthly_positive_ratio: 0.8,
          monthly_max_drawdown: -0.12,
          return_drawdown_ratio: 8.5662,
          avg_monthly_sample_count: 6.4,
          worst_month_total_return: -0.12,
          best_month_total_return: 0.52,
          rank_reason: "样本跨月更稳，适合作为核心线。",
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
    sector_leadership_policy: {
      status: "supported",
      label: "板块顺势有效",
      horizon: 20,
      summary: "强板块候选跑赢其他候选，只作门控验证，不直接当买点。",
      rhythm_status: "follow_with_confirmation",
      rhythm_label: "顺势跟随",
      rhythm_summary: "强板块连续有效时允许顺势跟随，但仍要确认个股趋势、量能和风险位。",
      latest_month_status: "effective",
      warnings: [],
      rules: ["板块顺势只作门控验证，不直接当买点。"],
      rows: [
        {
          scope: "action_long",
          label: "长期行动池",
          horizon: 20,
          month_count: 2,
          strong_sample_count: 7,
          strong_avg_return: 0.057143,
          strong_total_return: 0.4,
          other_sample_count: 2,
          other_avg_return: -0.025,
          other_total_return: -0.05,
          avg_return_lift: 0.082143,
          total_return_lift: 0.45,
          positive_months: 2,
          negative_months: 0,
          latest_month: "2026-06",
          monthly_rows: [
            {
              month: "2026-05",
              status: "effective",
              strong_sample_count: 3,
              strong_avg_return: 0.06,
              strong_total_return: 0.18,
              other_sample_count: 1,
              other_avg_return: -0.04,
              other_total_return: -0.04,
              avg_return_lift: 0.1,
              total_return_lift: 0.22,
            },
            {
              month: "2026-06",
              status: "effective",
              strong_sample_count: 4,
              strong_avg_return: 0.055,
              strong_total_return: 0.22,
              other_sample_count: 1,
              other_avg_return: -0.01,
              other_total_return: -0.01,
              avg_return_lift: 0.065,
              total_return_lift: 0.23,
            },
          ],
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
    action_long: {
      start_date: "2024-01-01",
      end_date: "2026-07-01",
      candidate_count: 19,
      warning_days: 0,
      top_sectors: [],
      style_counts: [{ style: "growth_cycle", count: 19 }],
      selection_mode_counts: [{ selection_mode: "formal_strategy", count: 19 }],
      startup_signal_counts: [],
      horizons: {
        20: {
          raw: { sample_count: 18, avg_return: 0.06, win_rate: 0.61, total_return: 1.08 },
          guarded: { sample_count: 18, avg_return: 0.057108, win_rate: 0.61, total_return: 1.027945 },
        },
      },
      portfolio_horizons: {
        20: {
          max_positions: 3,
          weighting: "equal_weight_by_signal_day",
          raw: { sample_count: 12, avg_return: 0.045, win_rate: 0.58, total_return: 0.54 },
          guarded: { sample_count: 12, avg_return: 0.04, win_rate: 0.58, total_return: 0.48 },
        },
      },
      monthly_horizons: {},
      monthly_portfolio_horizons: {
        20: {
          "2026-05": {
            max_positions: 3,
            weighting: "equal_weight_by_signal_day",
            raw: { sample_count: 3, avg_return: 0.045, win_rate: 0.67, total_return: 0.135 },
            guarded: { sample_count: 3, avg_return: 0.04, win_rate: 0.67, total_return: 0.12 },
          },
          "2026-06": {
            max_positions: 3,
            weighting: "equal_weight_by_signal_day",
            raw: { sample_count: 2, avg_return: -0.015, win_rate: 0, total_return: -0.03 },
            guarded: { sample_count: 2, avg_return: -0.02, win_rate: 0, total_return: -0.04 },
          },
        },
      },
      style_horizons: {},
      selection_mode_horizons: {},
      startup_signal_horizons: {},
      monthly_style_horizons: {},
      monthly_selection_mode_horizons: {},
      monthly_startup_signal_horizons: {},
      style_horizon_preferences: {},
      processed_days: 300,
      excluded_symbols: [],
    },
    startup_preheat: {
      start_date: "2024-01-01",
      end_date: "2026-07-01",
      candidate_count: 8,
      warning_days: 0,
      top_sectors: [],
      style_counts: [],
      selection_mode_counts: [{ selection_mode: "potential_watch", count: 8 }],
      startup_signal_counts: [{ bucket: "high", label: "高分启动观察", count: 3 }],
      horizons: {
        5: {
          raw: { sample_count: 8, avg_return: 0.04, win_rate: 0.63, total_return: 0.32 },
          guarded: { sample_count: 8, avg_return: 0.03, win_rate: 0.63, total_return: 0.24 },
        },
        20: {
          raw: { sample_count: 30, avg_return: 0.02, win_rate: 0.47, total_return: 0.6 },
          guarded: { sample_count: 30, avg_return: 0.015, win_rate: 0.47, total_return: 0.45 },
        },
      },
      portfolio_horizons: {
        20: {
          max_positions: 3,
          weighting: "equal_weight_by_signal_day",
          raw: { sample_count: 20, avg_return: 0.022, win_rate: 0.5, total_return: 0.44 },
          guarded: { sample_count: 20, avg_return: 0.018, win_rate: 0.5, total_return: 0.36 },
        },
      },
      monthly_horizons: {},
      monthly_portfolio_horizons: {
        20: {
          "2026-05": {
            max_positions: 3,
            weighting: "equal_weight_by_signal_day",
            raw: { sample_count: 3, avg_return: 0.02, win_rate: 0.67, total_return: 0.06 },
            guarded: { sample_count: 3, avg_return: 0.015, win_rate: 0.67, total_return: 0.045 },
          },
          "2026-06": {
            max_positions: 3,
            weighting: "equal_weight_by_signal_day",
            raw: { sample_count: 4, avg_return: 0.035, win_rate: 0.75, total_return: 0.14 },
            guarded: { sample_count: 4, avg_return: 0.03, win_rate: 0.75, total_return: 0.12 },
          },
        },
      },
      style_horizons: {},
      selection_mode_horizons: {},
      startup_signal_horizons: {
        1: {
          high: {
            raw: { sample_count: 3, avg_return: 0.035, win_rate: 0.67, total_return: 0.105 },
            guarded: { sample_count: 3, avg_return: 0.03, win_rate: 0.67, total_return: 0.09 },
          },
          low: {
            raw: { sample_count: 2, avg_return: -0.01, win_rate: 0, total_return: -0.02 },
            guarded: { sample_count: 2, avg_return: -0.015, win_rate: 0, total_return: -0.03 },
          },
        },
        5: {
          high: {
            raw: { sample_count: 3, avg_return: 0.08, win_rate: 1, total_return: 0.24 },
            guarded: { sample_count: 3, avg_return: 0.07, win_rate: 1, total_return: 0.21 },
          },
          low: {
            raw: { sample_count: 2, avg_return: -0.02, win_rate: 0, total_return: -0.04 },
            guarded: { sample_count: 2, avg_return: -0.025, win_rate: 0, total_return: -0.05 },
          },
        },
        10: {
          high: {
            raw: { sample_count: 3, avg_return: 0.06, win_rate: 0.67, total_return: 0.18 },
            guarded: { sample_count: 3, avg_return: 0.05, win_rate: 0.67, total_return: 0.15 },
          },
        },
        20: {
          high: {
            raw: { sample_count: 3, avg_return: 0.025, win_rate: 0.67, total_return: 0.075 },
            guarded: { sample_count: 3, avg_return: 0.02, win_rate: 0.67, total_return: 0.06 },
          },
        },
      },
      startup_signal_style_horizons: {
        20: {
          growth_cycle: {
            high: {
              raw: { sample_count: 3, avg_return: 0.055, win_rate: 0.67, total_return: 0.165 },
              guarded: { sample_count: 3, avg_return: 0.045, win_rate: 0.67, total_return: 0.135 },
            },
            low: {
              raw: { sample_count: 2, avg_return: -0.01, win_rate: 0, total_return: -0.02 },
              guarded: { sample_count: 2, avg_return: -0.02, win_rate: 0, total_return: -0.04 },
            },
          },
          cyclical: {
            high: {
              raw: { sample_count: 2, avg_return: -0.015, win_rate: 0, total_return: -0.03 },
              guarded: { sample_count: 2, avg_return: -0.025, win_rate: 0, total_return: -0.05 },
            },
          },
        },
      },
      monthly_style_horizons: {},
      monthly_selection_mode_horizons: {},
      monthly_startup_signal_horizons: {},
      style_horizon_preferences: {},
      processed_days: 300,
      excluded_symbols: [],
    },
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
    potential_watch: {
      start_date: "2024-01-01",
      end_date: "2026-07-01",
      candidate_count: 12,
      warning_days: 0,
      top_sectors: [],
      style_counts: [{ style: "growth_cycle", count: 12 }],
      selection_mode_counts: [{ selection_mode: "potential_watch", count: 12 }],
      startup_signal_counts: [],
      horizons: {},
      portfolio_horizons: {},
      monthly_horizons: {},
      monthly_portfolio_horizons: {
        20: {
          "2026-06": {
            max_positions: 3,
            weighting: "equal_weight_by_signal_day",
            raw: { sample_count: 5, avg_return: 0.022, win_rate: 0.6, total_return: 0.11 },
            guarded: { sample_count: 5, avg_return: 0.02, win_rate: 0.6, total_return: 0.1 },
          },
        },
      },
      style_horizons: {},
      selection_mode_horizons: {},
      startup_signal_horizons: {},
      monthly_style_horizons: {},
      monthly_selection_mode_horizons: {},
      monthly_startup_signal_horizons: {},
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
const strategyRows = strategyPkRows(candidateReplay);
const dualLineSummary = dualLineLongReplaySummary(candidateReplay);
const monthlyPkRows = monthlyStrategyPkRows(candidateReplay, 20);
const startupSignalRows = startupSignalReplayRows(candidateReplay);
const startupSignalStyleRows = startupSignalStyleReplayRows(candidateReplay, 20);
if (!dualLineSummary) {
  throw new Error("双线摘要应在长期行动池和启动前夜池都有样本时存在");
}

scopeRows[0].scope satisfies "all" | "action" | "action_long" | string;
breakdownRows[0].label satisfies string;
weakRows[0].month satisfies string;
preferenceRows[0].preferredHorizon satisfies number;
startupRows[0].horizon satisfies number;
startupRows[0].highSignalMetric?.sample_count satisfies number | undefined;
monthlyStyleRows[0].month satisfies string;
candidateReplay.diagnosis.primary_scope satisfies string;
strategyRows[0].policyLabel satisfies string;
strategyRows[0].primaryMetric?.total_return satisfies number | null | undefined;
strategyRows[0].monthlyMaxDrawdown satisfies number | null;
strategyRows[0].avgMonthlySampleCount satisfies number | null;
strategyRows[0].monthlyPositiveRatio satisfies number | null;
strategyRows[0].returnDrawdownRatio satisfies number | null;
dualLineSummary.mainLine.label satisfies "长期行动池";
dualLineSummary.supportLine.label satisfies "启动前夜池";
dualLineSummary.guidance satisfies string;
dualLineSummary.qualityLeader satisfies "main" | "support" | "none";
monthlyPkRows[0].month satisfies "2026-06" | string;
monthlyPkRows[0].postureLabel satisfies string;
monthlyPkRows[0].leaderLabel satisfies string;
monthlyPkRows[0].leaderTotalReturn satisfies number | null;
monthlyPkRows[0].worstLineLabel satisfies string;
monthlyPkRows[0].worstTotalReturn satisfies number | null;
monthlyPkRows[0].lines[0].label satisfies string;
monthlyPkRows[0].guidance satisfies string;
startupSignalRows[0].horizon satisfies 1 | 5 | 10 | 20 | number;
startupSignalRows[0].postureLabel satisfies string;
startupSignalRows[0].highSignalMetric?.sample_count satisfies number | undefined;
startupSignalRows[0].liftAvgReturn satisfies number | null;
startupSignalRows[0].guidance satisfies string;
startupSignalStyleRows[0].style satisfies string;
startupSignalStyleRows[0].label satisfies string;
startupSignalStyleRows[0].highSignalMetric?.sample_count satisfies number | undefined;
startupSignalStyleRows[0].postureLabel satisfies string;
startupSignalStyleRows[0].guidance satisfies string;
longCandidateReplayQuery.start_date satisfies "2025-01-02";
longCandidateReplayQuery.end_date satisfies "2026-06-05";
longCandidateReplayQuery.limit satisfies 15;
longCandidateReplayQuery.min_coverage_ratio satisfies 0.7;
longCandidateReplayQuery.include_fundamentals satisfies false;
longCandidateReplayQuery.use_monthly_shards satisfies true;
initialCandidateReplayQuery.start_date satisfies "2025-01-02";
initialCandidateReplayQuery.end_date satisfies "2026-06-05";
initialCandidateReplayQuery.use_monthly_shards satisfies true;
