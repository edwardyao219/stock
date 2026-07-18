import {
  fetchMarketStressRecoveryReplay,
  type MarketStressRecoveryReplayReport,
} from "./api";

const report = {
  start_date: "2024-01-01",
  end_date: "2026-07-16",
  data_source: "daily_bars",
  market_regime_data_source: "market_regime_daily",
  market_regime_cache_version: "market-regime-daily-v1",
  min_coverage_ratio: 0.8,
  first_trade_date: "2024-01-02",
  last_trade_date: "2026-07-16",
  snapshot_count: 611,
  observed_trade_day_count: 613,
  data_gap_count: 2,
  market_regime_coverage_count: 613,
  market_regime_gap_count: 0,
  false_rebound_window: 3,
  recommendation: {
    status: "keep_current",
    label: "维持2/4",
    threshold_label: "2/4",
    summary: "继续使用当前阈值。",
  },
  rows: [
    {
      threshold_label: "2/4",
      limited_after: 2,
      normal_after: 4,
      risk_event_count: 19,
      completed_recovery_count: 18,
      evaluated_recovery_count: 18,
      unresolved_event_count: 1,
      false_rebound_count: 11,
      false_rebound_rate: 0.611111,
      avg_recovery_days: 4.94,
      blocked_days: 431,
      limited_days: 121,
      blocked_opportunity_days: 114,
      limited_opportunity_days: 88,
      is_current: true,
    },
  ],
  yearly_rows: [
    {
      year: 2026,
      snapshot_count: 131,
      observed_trade_day_count: 131,
      data_gap_count: 0,
      risk_event_count: 4,
      completed_recovery_count: 3,
      evaluated_recovery_count: 3,
      unresolved_event_count: 1,
      false_rebound_count: 2,
      false_rebound_rate: 0.666667,
      avg_recovery_days: 5.0,
      blocked_opportunity_days: 28,
      limited_opportunity_days: 19,
    },
  ],
  regime_rows: [
    {
      regime: "range",
      snapshot_count: 341,
      risk_event_count: 18,
      completed_recovery_count: 17,
      evaluated_recovery_count: 17,
      unresolved_event_count: 1,
      false_rebound_count: 11,
      false_rebound_rate: 0.647059,
      avg_recovery_days: 4.88,
    },
  ],
  cache: {
    hit: true,
    cache_key: "example",
    version: "market-stress-recovery-v6",
  },
} satisfies MarketStressRecoveryReplayReport;

report.rows[0].threshold_label satisfies string;
report.yearly_rows[0].year satisfies number;
report.regime_rows[0].regime satisfies string;
fetchMarketStressRecoveryReplay({ start_date: "2024-01-01", force_refresh: true });
