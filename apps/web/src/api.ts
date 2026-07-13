export type RecommendationStatus = "pending" | "approved" | "rejected" | "applied";
export type DecisionStatus = "pending" | "approved" | "rejected";

export interface ParameterRecommendation {
  id: number;
  report_date: string;
  rule_id: string | null;
  scope_type: string;
  scope_value: string | null;
  target_type: string;
  target_name: string;
  action: string;
  priority: string;
  rationale: string;
  current: Record<string, unknown>;
  proposed: Record<string, unknown>;
  guardrails: string[];
  source_report_type: string;
  status: RecommendationStatus;
  decision_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface RecommendationSummary {
  by_status: Record<string, number>;
  pending: number;
}

export interface MechanicalReview {
  report_date: string | null;
  report_type: string;
  title: string;
  content_md: string;
  metrics: Record<string, unknown>;
  found: boolean;
}

export interface MonthlySummary {
  month: string;
  paper_review_count: number;
  backtest_trade_count: number;
  winning_reviews: number;
  losing_reviews: number;
  total_pnl: number;
  avg_review_return: number | null;
  avg_backtest_return: number | null;
  top_symbols: Record<string, unknown>[];
  top_rules: Record<string, unknown>[];
  factor_insights: Record<string, unknown>[];
  sector_opportunities: Record<string, unknown>[];
  excluded_symbols: string[];
  content_md: string;
}

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  amount: number | null;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma60: number | null;
}

export interface MarketOverview {
  trade_date: string | null;
  stock_count: number;
  up_count: number;
  down_count: number;
  flat_count: number;
  up_ratio: number | null;
  avg_change_pct: number | null;
  total_amount: number | null;
  amount_change_pct: number | null;
  active_security_count: number;
  coverage_ratio: number | null;
  is_full_market: boolean;
  message: string;
  is_live_snapshot: boolean;
  is_current_snapshot: boolean;
  snapshot_scope_label: string;
  stress_status: "risk_off" | "caution" | "neutral" | "supportive" | string;
  stress_label: string;
  stress_score: number;
  stress_reasons: string[];
  stress_scope_label: string;
  risk_action_label: string;
  indexes: MarketIndex[];
}

export interface MarketIndex {
  code: string;
  name: string;
  quote_date: string | null;
  price: number | null;
  change_pct: number | null;
  amount: number | null;
  source: string;
}

export interface DataHealthIssue {
  code: string;
  severity: string;
  message: string;
  metric: string;
  value: number | null;
  threshold: number | null;
}

export interface DataHealth {
  trade_date: string | null;
  status: string;
  daily_bar_count: number;
  feature_count: number;
  previous_daily_bar_count: number;
  amount_missing_ratio: number | null;
  previous_amount_missing_ratio: number | null;
  amount_ratio_5d_median: number | null;
  amount_ratio_5d_p10: number | null;
  volume_confirmation_median: number | null;
  amount_volume_multiplier_median: number | null;
  previous_amount_volume_multiplier_median: number | null;
  issues: DataHealthIssue[];
}

export interface SectorOverviewItem {
  sector_code: string;
  sector_name: string;
  canonical_sector_name: string | null;
  trade_date: string | null;
  month_start_date: string | null;
  month_rank: number | null;
  monthly_return_pct: number | null;
  day_change_pct: number | null;
  amount: number | null;
  fund_flow_net_amount: number | null;
  fund_flow_rate: number | null;
  sector_strength_score: number | null;
  sector_breadth_score: number | null;
  sector_momentum_score: number | null;
  sector_stock_count: number | null;
  sector_up_count: number | null;
  sector_gate_score: number | null;
  sector_gate_label: string | null;
  sector_gate_reasons: string[];
}

export interface SectorOverview {
  trade_date: string | null;
  month_start_date: string | null;
  feature_trade_date: string | null;
  moneyflow_trade_date: string | null;
  feature_sector_count: number;
  overview_sector_count: number;
  feature_coverage_ratio: number | null;
  moneyflow_sector_count: number;
  moneyflow_missing_count: number;
  moneyflow_coverage_ratio: number | null;
  moneyflow_reliability_label: string;
  sector_gate_summary: {
    main_allowed_count: number;
    observe_count: number;
    cooldown_count: number;
    unknown_count: number;
  };
  sectors: SectorOverviewItem[];
  monthly_rank: SectorOverviewItem[];
  activity_rank: SectorOverviewItem[];
  continuity_rank: SectorOverviewItem[];
}

export interface SectorCatalystItem {
  sector_name: string;
  catalyst_score: number;
  catalyst_label: string;
  keywords: string[];
  related_sectors: string[];
  source_titles: string[];
  risk_notes: string[];
}

export interface SectorCatalysts {
  as_of: string;
  source_count: number;
  catalysts: SectorCatalystItem[];
  message: string;
  snapshot_id: number | null;
  snapshot_trade_date: string | null;
  stored: boolean;
}

export interface WorkspacePlan {
  id: number;
  rule_id: string;
  strategy_type: string;
  plan_date: string;
  trade_date: string;
  position_size: number;
  confidence_score: number | null;
  entry_trigger_price: number | null;
  initial_stop: number | null;
  take_profit_1: number | null;
  take_profit_2: number | null;
  status: string;
  can_buy_now: boolean;
  execution_status: string;
  execution_label: string;
  execution_note: string;
  evidence: PlanEvidence[];
}

export interface PlanEvidence {
  category: string;
  label: string;
  value: string;
  verdict: string;
  note: string;
}

export interface PaperTradeSummary {
  rule_id: string;
  closed_count: number;
  open_count: number;
  win_rate: number;
  avg_return: number;
  total_return: number;
  avg_mfe: number;
  avg_mae: number;
  best_return: number;
  worst_return: number;
  latest_entry_date: string | null;
  latest_exit_date: string | null;
  latest_pnl_pct: number | null;
  latest_exit_reason: string | null;
}

export interface PaperTrade {
  id: number;
  trade_plan_id: number | null;
  rule_id: string;
  entry_date: string;
  entry_price: number;
  exit_date: string | null;
  exit_price: number | null;
  holding_days: number;
  pnl_pct: number | null;
  mfe_pct: number;
  mae_pct: number;
  highest_price: number;
  lowest_price: number;
  quantity: number;
  status: string;
  exit_reason: string | null;
  current_price: number | null;
  current_pnl_pct: number | null;
  current_stop: number | null;
  take_profit_1: number | null;
  quote_time: string | null;
}

export interface WorkspaceStock {
  symbol: string;
  name: string | null;
  industry: string | null;
  sector_style: string | null;
  source: string;
  manual_note: string | null;
  manual_tags: string[];
  candidate_rank: number | null;
  candidate_score: number | null;
  candidate_tier: "core_action" | "sector_watch" | "watch_wait" | "risk_reject" | null;
  candidate_tier_label: string | null;
  candidate_tier_reason: string | null;
  startup_signal_score: number | null;
  startup_signal_label: string | null;
  startup_signal_reasons: string[];
  feature_date: string | null;
  latest_trade_date: string | null;
  latest_close: number | null;
  current_price: number | null;
  day_change_pct: number | null;
  quote_time: string | null;
  return_5d: number | null;
  return_20d: number | null;
  trend_score: number | null;
  relative_strength_score: number | null;
  sector_strength_score: number | null;
  volume_confirmation_score: number | null;
  risk_score: number | null;
  overheat_score: number | null;
  volume_trap_risk_score: number | null;
  distance_to_ma20: number | null;
  amount_percentile_60d: number | null;
  amount_ratio_5d: number | null;
  pullback_volume_ratio: number | null;
  ma20_slope_20d: number | null;
  ma60_slope_20d: number | null;
  ma_alignment_score: number | null;
  trend_quality_score: number | null;
  route_score: number | null;
  route_label: string | null;
  route_reason: string | null;
  plans: WorkspacePlan[];
  paper_trade_summaries: PaperTradeSummary[];
  recent_paper_trades: PaperTrade[];
  manual_refresh?: ManualRefresh | null;
}

export interface TrackingSnapshot {
  symbol: string;
  snapshot_date: string;
  stage: string;
  stage_label: string;
  tracking_state_key: string;
  tracking_state_label: string;
  tracking_state_reason: string | null;
  startup_phase_key: string;
  startup_phase_label: string;
  startup_phase_reason: string | null;
  tracking_score: number | null;
  name: string | null;
  industry: string | null;
  sector_style: string | null;
  latest_trade_date: string | null;
  latest_close: number | null;
  current_price: number | null;
  day_change_pct: number | null;
  return_5d: number | null;
  return_20d: number | null;
  metrics: Record<string, unknown>;
  evidence: string[];
  risks: string[];
  source: Record<string, unknown>;
}

export interface TrackingSnapshotRun {
  snapshot_date: string;
  created_count: number;
  symbols: string[];
}

export interface TrackingSignalItem {
  symbol: string;
  name: string | null;
  industry: string | null;
  latest_snapshot_date: string | null;
  sample_count: number;
  score_delta: number | null;
  simple_return_pct: number | null;
  signal_alignment_key: string;
  signal_alignment_label: string;
  signal_alignment_tone: "good" | "warn" | "bad" | "neutral" | string;
}

export interface TrackingSignalSector {
  industry: string;
  symbol_count: number;
  mature_count: number;
  aligned_count: number;
  divergent_count: number;
  insufficient_count: number;
  avg_score_delta: number | null;
  avg_simple_return_pct: number | null;
  maturity_label: string;
  signal_label: string;
}

export interface TrackingSignalSummary {
  symbol_count: number;
  aligned_count: number;
  divergent_count: number;
  insufficient_count: number;
  mature_count: number;
  maturity_ratio: number;
  maturity_label: string;
  maturity_note: string;
  sectors: TrackingSignalSector[];
  items: TrackingSignalItem[];
}

export interface IntradayCandidate {
  symbol: string;
  name: string | null;
  sector: string | null;
  quote_time: string;
  price: number | null;
  day_change_pct: number | null;
  candidate_rank: number | null;
  candidate_score: number | null;
  intraday_state: string;
  intraday_label: string;
  intraday_score: number;
  review_window: string;
  review_window_label: string;
  sector_signal: string;
  sector_signal_label: string;
  sector_quality_score: number;
  sector_quality_label: string;
  selection_tier: string;
  selection_tier_label: string;
  selection_reason: string;
  summary: string;
  theme_signal_label: string | null;
  theme_signal_reason: string | null;
  caution_reasons: string[];
  support_flags: string[];
  risk_flags: string[];
}

export interface CandidateBatch {
  auto_feature_date: string | null;
  auto_hold_until: string | null;
  source_item_count: number;
  usable_item_count: number;
  current_auto_candidate_count: number;
  manual_focus_count: number;
  stale_auto_candidate_count: number;
}

export interface IntradayMarketStress {
  trade_date: string | null;
  snapshot_scope_label: string | null;
  stress_status: string;
  stress_label: string;
  stress_score: number | null;
  risk_action_label: string | null;
  stress_reasons: string[];
}

export interface IntradayQuoteCoverageSector {
  sector: string;
  target_symbol_count: number;
  valid_quote_count: number;
  coverage_ratio: number;
  missing_symbols: string[];
}

export interface IntradayQuoteCoverage {
  target_symbol_count: number;
  valid_quote_count: number;
  coverage_ratio: number;
  latest_quote_time: string | null;
  missing_symbols: string[];
  sectors: IntradayQuoteCoverageSector[];
}

export interface IntradayCandidateList {
  trade_date: string;
  as_of: string | null;
  pool_name: string;
  candidate_count: number;
  candidate_batch: CandidateBatch;
  market_stress: IntradayMarketStress | null;
  quote_coverage: IntradayQuoteCoverage | null;
  candidates: IntradayCandidate[];
}

export interface IntradayCandidateSnapshot extends IntradayCandidateList {
  stage: string;
  stage_label: string;
}

export interface IntradaySnapshotLearning {
  symbol: string;
  name: string | null;
  sector: string | null;
  from_stage: string;
  from_stage_label: string;
  to_stage: string;
  to_stage_label: string;
  from_state: string;
  from_label: string;
  to_state: string;
  to_label: string;
  from_score: number;
  to_score: number;
  score_delta: number;
  verdict: string;
  verdict_label: string;
  reason: string;
}

export interface IntradaySectorVerdict {
  sector: string;
  transition_count: number;
  weakened_count: number;
  repaired_count: number;
  held_strength_count: number;
  stayed_weak_count: number;
}

export interface IntradaySnapshotLearningSummary {
  sample_days: number;
  transition_count: number;
  verdict_counts: Record<string, number>;
  sector_verdicts: IntradaySectorVerdict[];
  pattern_notes: string[];
}

export interface IntradayCandidateSnapshotList {
  trade_date: string;
  pool_name: string;
  snapshots: IntradayCandidateSnapshot[];
  learning: IntradaySnapshotLearning[];
  learning_summary: IntradaySnapshotLearningSummary | null;
}

export interface ManualRefresh {
  symbol: string;
  security_rows: number;
  daily_rows: number;
  feature_rows: number;
  sector_rows: number;
  fundamental_ok: number;
  formal_plan_rows: number;
  watch_plan_rows: number;
  feature_date: string | null;
  warnings: string[];
}

export interface StrategyFitRecommendation {
  id: number;
  priority: string;
  target_type: string;
  target_name: string;
  action: string;
  rationale: string;
  proposed: Record<string, unknown>;
  status: string;
}

export interface StrategyFitMetric {
  rule_id: string;
  scope_type: string;
  scope_value: string;
  trade_count: number;
  win_rate: number;
  avg_return: number;
  profit_factor: number;
  avg_mfe: number;
  avg_mae: number;
  evidence_quality: string | null;
  positive_learning_allowed: boolean | null;
  train_sample_count: number | null;
  validation_sample_count: number | null;
  train_avg_return: number | null;
  validation_avg_return: number | null;
  train_win_rate: number | null;
  validation_win_rate: number | null;
  train_profit_factor: number | null;
  validation_profit_factor: number | null;
  train_total_return: number | null;
  validation_total_return: number | null;
  out_of_sample_passed: boolean | null;
  out_of_sample_status: string | null;
  fit_status: string;
  summary: string;
  recommendations: StrategyFitRecommendation[];
}

export interface StrategyFitRule {
  rule_id: string;
  overall: StrategyFitMetric;
  sectors: StrategyFitMetric[];
  symbols: StrategyFitMetric[];
}

export interface StrategyFitReport {
  report_date: string | null;
  rules: StrategyFitRule[];
}

export interface ReplayReturnSummary {
  sample_count: number;
  avg_return: number | null;
  win_rate: number | null;
  total_return: number | null;
  exit_reasons?: Record<string, number>;
}

export interface ReplayHorizonSummary {
  raw: ReplayReturnSummary;
  guarded: ReplayReturnSummary;
}

export interface ReplayMonthlyHorizonSummary {
  raw: ReplayReturnSummary;
  guarded: ReplayReturnSummary;
}

export interface ReplayPortfolioHorizonSummary extends ReplayMonthlyHorizonSummary {
  max_positions: number;
  weighting: string;
}

export interface ReplayStylePreference {
  preferred_horizon: number;
  preferred_metric: string;
  sample_count: number;
  avg_return: number | null;
  total_return: number | null;
  actionable: boolean;
  reason: string;
}

export interface ReplayCountItem {
  count: number;
}

export interface ReplaySectorCount extends ReplayCountItem {
  sector: string;
}

export interface ReplayStyleCount extends ReplayCountItem {
  style: string;
}

export interface ReplaySelectionModeCount extends ReplayCountItem {
  selection_mode: string;
}

export interface ReplayStartupSignalCount extends ReplayCountItem {
  bucket: string;
  label: string;
}

export interface ReplayDataCoverageMonth {
  month: string;
  grade: string;
  is_incomplete_tail_month: boolean;
  trade_days: number;
  feature_days: number;
  sector_days: number;
  avg_daily_bar_symbols: number | null;
  avg_feature_symbols: number | null;
  avg_sector_rows: number | null;
  feature_day_ratio: number | null;
  sector_day_ratio: number | null;
  avg_market_feature_coverage: number | null;
  avg_feature_active_coverage: number | null;
  warnings: string[];
}

export interface ReplayDataCoverage {
  start_date: string;
  end_date: string;
  overall: {
    grade: string;
    months: number;
    usable_months: number;
    warning_months: number;
    active_symbols: number;
    min_trade_days: number;
    min_active_feature_coverage: number;
    min_sector_rows: number;
  };
  months: ReplayDataCoverageMonth[];
  warnings: string[];
}

export interface ReplayScopeSummary {
  start_date: string;
  end_date: string;
  processed_days: number;
  candidate_count: number;
  excluded_symbols: string[];
  warning_days: number;
  top_sectors: ReplaySectorCount[];
  style_counts: ReplayStyleCount[];
  selection_mode_counts: ReplaySelectionModeCount[];
  startup_signal_counts?: ReplayStartupSignalCount[];
  horizons: Record<number, ReplayHorizonSummary>;
  portfolio_horizons: Record<number, ReplayPortfolioHorizonSummary>;
  style_horizons: Record<number, Record<string, ReplayHorizonSummary>>;
  selection_mode_horizons: Record<number, Record<string, ReplayHorizonSummary>>;
  startup_signal_horizons?: Record<number, Record<string, ReplayHorizonSummary>>;
  startup_signal_style_horizons?: Record<
    number,
    Record<string, Record<string, ReplayHorizonSummary>>
  >;
  style_horizon_preferences: Record<string, ReplayStylePreference>;
  monthly_horizons: Record<number, Record<string, ReplayMonthlyHorizonSummary>>;
  monthly_portfolio_horizons: Record<number, Record<string, ReplayPortfolioHorizonSummary>>;
  monthly_style_horizons: Record<number, Record<string, Record<string, ReplayHorizonSummary>>>;
  monthly_selection_mode_horizons: Record<
    number,
    Record<string, Record<string, ReplayHorizonSummary>>
  >;
  monthly_startup_signal_horizons?: Record<
    number,
    Record<string, Record<string, ReplayHorizonSummary>>
  >;
}

export interface LowDimensionalReplayReport extends ReplayScopeSummary {
  data_coverage: ReplayDataCoverage;
}

export interface CandidateReplayDiagnosisScopeRow {
  scope: string;
  label: string;
  candidate_count: number;
  sample_count: number;
  avg_return: number | null;
  win_rate: number | null;
  total_return: number | null;
}

export interface CandidateReplayStyleGateRow {
  style: string;
  label: string;
  status: string;
  status_label: string;
  latest_month: string;
  latest_sample_count: number;
  latest_avg_return: number | null;
  latest_win_rate: number | null;
  latest_total_return: number | null;
  recent_months: number;
  recent_sample_count: number;
  recent_avg_return: number | null;
  recent_total_return: number | null;
  positive_months: number;
  negative_months: number;
  summary: string;
}

export interface CandidateReplayStyleGatePolicy {
  scope: string;
  horizon: number;
  lookback_months: number;
  summary: string;
  rows: CandidateReplayStyleGateRow[];
  upgrade_styles: string[];
  observe_styles: string[];
  stand_down_styles: string[];
}

export interface StrategyPkHorizonMetric {
  metric_label: string;
  sample_count: number;
  avg_return: number | null;
  win_rate: number | null;
  total_return: number | null;
}

export interface StrategyPkRow {
  scope: string;
  label: string;
  policy: string;
  policy_label: string;
  candidate_count: number;
  primary_horizon: number;
  sample_count: number;
  avg_return: number | null;
  win_rate: number | null;
  total_return: number | null;
  metrics_by_horizon: Record<number, StrategyPkHorizonMetric>;
  latest_month: string | null;
  latest_month_sample_count: number;
  latest_month_avg_return: number | null;
  latest_month_total_return: number | null;
  month_count: number;
  positive_months: number;
  negative_months: number;
  monthly_positive_ratio: number | null;
  monthly_max_drawdown: number | null;
  return_drawdown_ratio: number | null;
  avg_monthly_sample_count: number | null;
  worst_month_total_return: number | null;
  best_month_total_return: number | null;
  rank_reason: string;
}

export interface StrategyPkReport {
  return_mode: "simple_sum_no_compounding" | string;
  horizons: number[];
  primary_horizon: number;
  summary: string;
  rows: StrategyPkRow[];
  rules: string[];
}

export interface CandidateReplaySectorLeadershipRow {
  scope: string;
  label: string;
  horizon: number;
  month_count: number;
  strong_sample_count: number;
  strong_avg_return: number | null;
  strong_total_return: number | null;
  other_sample_count: number;
  other_avg_return: number | null;
  other_total_return: number | null;
  avg_return_lift: number | null;
  total_return_lift: number | null;
  positive_months: number;
  negative_months: number;
  latest_month: string | null;
  monthly_rows: CandidateReplaySectorLeadershipMonthRow[];
}

export interface CandidateReplaySectorLeadershipMonthRow {
  month: string;
  status: string;
  strong_sample_count: number;
  strong_avg_return: number | null;
  strong_total_return: number | null;
  other_sample_count: number;
  other_avg_return: number | null;
  other_total_return: number | null;
  avg_return_lift: number | null;
  total_return_lift: number | null;
}

export interface CandidateReplaySectorLeadershipPolicy {
  status: string;
  label: string;
  horizon: number;
  summary: string;
  rhythm_status: string;
  rhythm_label: string;
  rhythm_summary: string;
  latest_month_status: string | null;
  warnings: string[];
  rows: CandidateReplaySectorLeadershipRow[];
  rules: string[];
}

export interface CandidateReplayMarketStressGatePolicy {
  status: string;
  label: string;
  horizon: number;
  lookback_months: number;
  weak_months: number;
  defended_months: number;
  best_core_scope: string | null;
  best_core_label: string | null;
  max_core_positions: number;
  avoided_total_loss: number | null;
  summary: string;
  rows: {
    month: string;
    all_sample_count: number;
    all_total_return: number | null;
    core_scope: string | null;
    core_label: string | null;
    core_sample_count: number;
    core_total_return: number | null;
    avoided_loss: number | null;
  }[];
  reasons: string[];
}

export interface CandidateReplayDiagnosis {
  horizon: number;
  primary_scope: string;
  primary_scope_label: string;
  policy_label: string;
  ding_policy: string;
  summary: string;
  scope_rows: CandidateReplayDiagnosisScopeRow[];
  reasons: string[];
  overfit_guardrails: string[];
  tactical_opportunities: string[];
  potential_watch_policy: {
    status: string;
    label: string;
    month: string | null;
    horizon: number | null;
    sample_count: number;
    avg_return: number | null;
    total_return: number | null;
    summary: string;
  };
  startup_preheat_policy: CandidateReplayStyleGatePolicy;
  market_phase_policy: {
    status: string;
    label: string;
    lookback_months: number;
    strong_months: number;
    weak_months: number;
    expansion_allowed: boolean;
    max_core_positions: number;
    summary: string;
    reasons: string[];
  };
  market_stress_gate_policy: CandidateReplayMarketStressGatePolicy;
  dual_line_policy: {
    active_line: string;
    ding_policy: string;
    max_core_positions: number;
    summary: string;
    main_line: {
      name: string;
      status: string;
      scope: string;
      label: string;
      sample_count: number;
      avg_return: number | null;
      total_return: number | null;
      summary: string;
    };
    support_line: {
      name: string;
      status: string;
      month: string | null;
      horizon: number | null;
      sample_count: number;
      avg_return: number | null;
      total_return: number | null;
      summary: string | null;
    };
    rules: string[];
  };
  style_gate_policy: CandidateReplayStyleGatePolicy;
  sector_leadership_policy: CandidateReplaySectorLeadershipPolicy;
  strategy_pk: StrategyPkReport;
  monthly_posture: {
    month: string | null;
    posture: string;
    posture_label: string;
    summary: string;
    scope_rows: Omit<CandidateReplayDiagnosisScopeRow, "candidate_count">[];
    reasons: string[];
  };
}

export interface CandidateReplayEffectReport {
  start_date: string;
  end_date: string;
  scopes: Record<string, ReplayScopeSummary>;
  discovery_cache_dir: string | null;
  data_coverage: ReplayDataCoverage;
  diagnosis: CandidateReplayDiagnosis;
  replay_cache?: {
    hit: boolean;
    cache_key: string;
    version: string;
    mode?: string;
    shard_count?: number;
    shard_hits?: number;
    shard_misses?: number;
  };
}

export interface CandidateReplayEffectQuery {
  start_date?: string;
  end_date?: string;
  limit?: number;
  min_coverage_ratio?: number;
  include_fundamentals?: boolean;
  force_refresh?: boolean;
  use_monthly_shards?: boolean;
}

export type PipelineStage = "daily" | "prepare" | "intraday" | "after-close";

export interface PipelineStep {
  name: string;
  status: string;
  detail: string;
  summary: string | null;
  details: string[];
}

export interface PipelineRunResult {
  trade_date: string;
  next_trade_date: string;
  stage: string;
  steps: PipelineStep[];
}

export interface PipelineRunPayload {
  stage: PipelineStage;
  trade_date?: string;
  next_trade_date?: string;
  limit?: number;
  account?: string;
  force?: boolean;
  full_market_sync?: boolean;
  disable_learning_adjustments?: boolean;
  dry_run_entries?: boolean;
  dry_run_exits?: boolean;
}

export interface HistoricalReplayDay {
  trade_date: string;
  next_trade_date: string | null;
  feature_rows: number;
  sector_rows: number;
  contexts: number;
  candidates: number;
  plans: number;
  written_plans: number;
  opened: number;
  closed: number;
  skipped: number;
  paper_reviews: number;
  backtest_trades: number;
  paper_learning: number;
  backtest_learning: number;
  messages: string[];
}

export interface HistoricalReplayAccountSummary {
  initial_cash: number;
  cash: number;
  market_value: number;
  equity: number;
  total_return_pct: number;
  realized_pnl: number;
  open_positions: number;
  closed_positions: number;
  win_rate: number | null;
  avg_closed_return_pct: number | null;
}

export interface HistoricalReplayResult {
  start_date: string;
  end_date: string;
  account: string;
  symbols: string[];
  processed_days: number;
  generated_plans: number;
  opened: number;
  closed: number;
  skipped: number;
  account_summary: HistoricalReplayAccountSummary;
  days: HistoricalReplayDay[];
}

export interface HistoricalReplayPayload {
  start_date: string;
  end_date: string;
  symbols: string[];
  account?: string;
  initial_cash?: number;
  limit?: number;
  use_learning_adjustments?: boolean;
  generate_learning?: boolean;
  dry_run?: boolean;
}

export type RuleRegressionStatusValue = "running" | "queued" | "idle" | "never_run";

export interface RuleRegressionStatus {
  status: RuleRegressionStatusValue;
  is_running: boolean;
  active_tasks: number;
  reserved_tasks: number;
  scheduled_tasks: number;
  latest_run_date: string | null;
  latest_trade_count: number;
  latest_performance_rows: number;
  message: string;
}

export interface AfterCloseStatus {
  trade_date: string;
  next_trade_date: string | null;
  status: string;
  message: string;
  updated_at: string | null;
  candidate_count: number;
  plan_count: number;
  dingtalk_statuses: string[];
  market_summary: string | null;
  source: string;
}

function normalizeWorkspaceStock(item: WorkspaceStock): WorkspaceStock {
  return {
    ...item,
    manual_tags: item.manual_tags ?? [],
    candidate_rank: item.candidate_rank ?? null,
    candidate_score: item.candidate_score ?? null,
    candidate_tier: item.candidate_tier ?? null,
    candidate_tier_label: item.candidate_tier_label ?? null,
    candidate_tier_reason: item.candidate_tier_reason ?? null,
    startup_signal_score: item.startup_signal_score ?? null,
    startup_signal_label: item.startup_signal_label ?? null,
    startup_signal_reasons: item.startup_signal_reasons ?? [],
    feature_date: item.feature_date ?? null,
    trend_score: item.trend_score ?? null,
    relative_strength_score: item.relative_strength_score ?? null,
    sector_strength_score: item.sector_strength_score ?? null,
    volume_confirmation_score: item.volume_confirmation_score ?? null,
    risk_score: item.risk_score ?? null,
    overheat_score: item.overheat_score ?? null,
    volume_trap_risk_score: item.volume_trap_risk_score ?? null,
    distance_to_ma20: item.distance_to_ma20 ?? null,
    amount_percentile_60d: item.amount_percentile_60d ?? null,
    amount_ratio_5d: item.amount_ratio_5d ?? null,
    pullback_volume_ratio: item.pullback_volume_ratio ?? null,
    ma20_slope_20d: item.ma20_slope_20d ?? null,
    ma60_slope_20d: item.ma60_slope_20d ?? null,
    ma_alignment_score: item.ma_alignment_score ?? null,
    trend_quality_score: item.trend_quality_score ?? null,
    plans: (item.plans ?? []).map((plan) => ({ ...plan, evidence: plan.evidence ?? [] })),
    paper_trade_summaries: item.paper_trade_summaries ?? [],
    recent_paper_trades: item.recent_paper_trades ?? [],
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchRecommendations(status: RecommendationStatus | "all") {
  const params = new URLSearchParams();
  if (status !== "all") params.set("status", status);
  return request<ParameterRecommendation[]>(
    `/parameter-recommendations${params.size ? `?${params.toString()}` : ""}`,
  );
}

export function fetchRecommendationSummary() {
  return request<RecommendationSummary>("/parameter-recommendations/summary");
}

export function fetchMechanicalReview() {
  return request<MechanicalReview>("/paper-learning/mechanical-review");
}

export function fetchMonthlySummary(month: string) {
  const params = new URLSearchParams({ month });
  return request<MonthlySummary>(`/paper-learning/monthly-summary?${params.toString()}`);
}

export function updateRecommendationDecision(
  id: number,
  status: DecisionStatus,
  decisionReason: string,
) {
  return request<ParameterRecommendation>(`/parameter-recommendations/${id}/decision`, {
    method: "PATCH",
    body: JSON.stringify({ status, decision_reason: decisionReason || null }),
  });
}

export function fetchCandles(symbol: string) {
  return request<Candle[]>(`/market/candles/${symbol}?limit=240`);
}

export function fetchMarketOverview(live = false) {
  const params = new URLSearchParams();
  if (live) params.set("live", "true");
  return request<MarketOverview>(`/market/overview${params.size ? `?${params.toString()}` : ""}`);
}

export function fetchSectorOverview() {
  return request<SectorOverview>("/market/sectors/overview");
}

export function fetchSectorCatalysts() {
  return request<SectorCatalysts>("/market/sectors/catalysts");
}

export function fetchDataHealth(tradeDate?: string | null) {
  const params = new URLSearchParams();
  if (tradeDate) params.set("trade_date", tradeDate);
  return request<DataHealth>(`/market/data-health${params.size ? `?${params.toString()}` : ""}`);
}

export function fetchWorkspaceStocks(poolName = "experiment", includeGrowthBoard = false) {
  const params = new URLSearchParams({ pool_name: poolName });
  if (includeGrowthBoard) params.set("include_growth_board", "true");
  return request<WorkspaceStock[]>(`/workspace/stocks?${params.toString()}`).then((items) =>
    items.map(normalizeWorkspaceStock),
  );
}

export function refreshWorkspaceStocks(poolName = "experiment", includeGrowthBoard = false) {
  const params = new URLSearchParams({ pool_name: poolName });
  if (includeGrowthBoard) params.set("include_growth_board", "true");
  return request<WorkspaceStock[]>(`/workspace/refresh?${params.toString()}`, {
    method: "POST",
  }).then((items) => items.map(normalizeWorkspaceStock));
}

export function fetchTrackingSnapshots(symbol: string, limit = 120) {
  const params = new URLSearchParams({ limit: String(limit) });
  return request<TrackingSnapshot[]>(
    `/workspace/tracking-snapshots/${encodeURIComponent(symbol)}?${params.toString()}`,
  );
}

export function fetchTrackingSignalSummary(
  poolName = "experiment",
  includeGrowthBoard = false,
  limitPerSymbol = 18,
) {
  const params = new URLSearchParams({
    pool_name: poolName,
    limit_per_symbol: String(limitPerSymbol),
  });
  if (includeGrowthBoard) params.set("include_growth_board", "true");
  return request<TrackingSignalSummary>(
    `/workspace/tracking-snapshots/summary?${params.toString()}`,
  );
}

export function createTrackingSnapshots(
  poolName = "experiment",
  includeGrowthBoard = false,
  snapshotDate?: string,
) {
  const params = new URLSearchParams({ pool_name: poolName });
  if (includeGrowthBoard) params.set("include_growth_board", "true");
  if (snapshotDate) params.set("snapshot_date", snapshotDate);
  return request<TrackingSnapshotRun>(`/workspace/tracking-snapshots?${params.toString()}`, {
    method: "POST",
  });
}

export function fetchIntradayCandidates(
  poolName = "experiment",
  includeGrowthBoard = false,
  refreshQuotes = false,
) {
  const params = new URLSearchParams({ pool_name: poolName });
  if (includeGrowthBoard) params.set("include_growth_board", "true");
  if (refreshQuotes) params.set("refresh_quotes", "true");
  return request<IntradayCandidateList>(`/workspace/intraday-candidates?${params.toString()}`);
}

export function fetchIntradayCandidateSnapshots(
  poolName = "experiment",
  includeGrowthBoard = false,
  lookbackDays = 5,
) {
  const params = new URLSearchParams({ pool_name: poolName });
  params.set("lookback_days", String(lookbackDays));
  if (includeGrowthBoard) params.set("include_growth_board", "true");
  return request<IntradayCandidateSnapshotList>(
    `/workspace/intraday-candidate-snapshots?${params.toString()}`,
  );
}

export function fetchStrategyFit(symbol?: string | null) {
  const params = new URLSearchParams({
    min_samples: "1",
    per_scope_limit: "12",
    include_recommendations: "false",
  });
  if (symbol) {
    params.set("symbol", symbol);
  } else {
    params.set("include_symbols", "false");
  }
  return request<StrategyFitReport>(`/rules/strategy-fit?${params.toString()}`);
}

export function fetchLowDimensionalReplay() {
  return request<LowDimensionalReplayReport>("/rules/low-dimensional-replay");
}

function formatDateParam(value: Date) {
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${value.getFullYear()}-${month}-${day}`;
}

function defaultCandidateReplayStartDate() {
  const start = new Date();
  start.setMonth(start.getMonth() - 3, 1);
  return formatDateParam(start);
}

export function fetchCandidateReplayEffect(query: CandidateReplayEffectQuery = {}) {
  const params = new URLSearchParams();
  params.set("start_date", query.start_date ?? defaultCandidateReplayStartDate());
  if (query.end_date) params.set("end_date", query.end_date);
  if (query.limit !== undefined) params.set("limit", String(query.limit));
  if (query.min_coverage_ratio !== undefined) {
    params.set("min_coverage_ratio", String(query.min_coverage_ratio));
  }
  if (query.include_fundamentals !== undefined) {
    params.set("include_fundamentals", String(query.include_fundamentals));
  }
  if (query.force_refresh !== undefined) {
    params.set("force_refresh", String(query.force_refresh));
  }
  if (query.use_monthly_shards !== undefined) {
    params.set("use_monthly_shards", String(query.use_monthly_shards));
  }
  return request<CandidateReplayEffectReport>(`/rules/candidate-replay-effect?${params.toString()}`);
}

export function addManualStock(symbol: string, note: string, tags: string[], poolName = "experiment") {
  return request<WorkspaceStock>("/workspace/manual-stocks", {
    method: "POST",
    body: JSON.stringify({ symbol, note: note || null, tags, pool_name: poolName }),
  }).then(normalizeWorkspaceStock);
}

export function runPipelineStage(payload: PipelineRunPayload) {
  return request<PipelineRunResult>("/jobs/pipeline/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function runHistoricalReplay(payload: HistoricalReplayPayload) {
  return request<HistoricalReplayResult>("/jobs/historical-replay/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchRuleRegressionStatus() {
  return request<RuleRegressionStatus>("/jobs/rule-regression/status");
}

export function fetchAfterCloseStatus(tradeDate?: string | null) {
  const params = new URLSearchParams();
  if (tradeDate) params.set("trade_date", tradeDate);
  return request<AfterCloseStatus>(`/jobs/after-close/status${params.size ? `?${params.toString()}` : ""}`);
}
