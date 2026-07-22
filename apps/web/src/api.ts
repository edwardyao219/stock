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
  recovery_stage: "blocked" | "limited" | "normal" | string;
  recovery_snapshot_count: number;
  recovery_required_count: number;
  indexes: MarketIndex[];
}

export interface IntradayMarketTurn {
  trade_date: string | null;
  snapshot_time: string | null;
  key: string;
  label: string;
  summary: string;
  data_ready: boolean;
  startup_watch_allowed: boolean;
  core_action_allowed: boolean;
  coverage_ratio: number | null;
  breadth_ratio: number | null;
  index_change_pct: number | null;
  sector_expansion_count: number | null;
  confirmed_signals: string[];
  pending_signals: string[];
  expanding_sectors: IntradayExpandingSector[];
  sustained_expanding_sectors: IntradaySustainedExpandingSector[];
  leading_sustained_sectors: IntradayLeadingSector[];
  cross_day_mainline: CrossDayMainline | null;
  quote_integrity: IntradayQuoteIntegrity | null;
}

export interface IntradayQuoteIntegrity {
  expected_symbol_count: number;
  valid_quote_count: number;
  coverage_ratio: number;
  source_counts: Record<string, number>;
  retry_applied: boolean;
}

export interface CrossDayMainline {
  status: string;
  summary: string;
  baseline_trade_date: string | null;
  checkpoint: string;
  confirmed_sectors: string[];
  sectors: CrossDayMainlineSector[];
}

export interface CrossDayMainlineSector {
  sector: string;
  status: string;
  reason: string;
  baseline_up_ratio: number | null;
  baseline_avg_change_pct: number | null;
  baseline_leader_change_pct: number | null;
  current_up_ratio: number | null;
  current_avg_change_pct: number | null;
  current_leader_change_pct: number | null;
}

export interface MainlineOutcomeHorizon {
  horizon: number;
  status: string;
  return_pct: number | null;
  reason: string | null;
}

export interface ConfirmedMainlineOutcome {
  signal_type: string;
  signal_date: string;
  sector: string;
  leader_symbol: string;
  horizons: MainlineOutcomeHorizon[];
  candidate_bindings: ConfirmedCandidateOutcome[];
}

export interface ConfirmedCandidateOutcome {
  symbol: string;
  sector: string;
  horizons: MainlineOutcomeHorizon[];
}

export interface MainlineOutcomeSummary {
  signal_type: string;
  window_limit: number;
  horizons: Array<{
    horizon: number;
    sample_count: number;
    total_signal_count: number;
    completed_count: number;
    waiting_count: number;
    waiting_reasons?: Record<string, number>;
    unavailable_count: number;
    unavailable_reasons: Record<string, number>;
    minimum_sample_count: number;
    eligible_for_policy: boolean;
    avg_return_pct: number | null;
    win_rate: number | null;
    failure_rate: number | null;
  }>;
  phase_summaries: Record<string, MainlineOutcomeSummary["horizons"]>;
  phase_market_states: Record<string, Array<{ key: string; sample_count: number; avg_return_pct: number; win_rate: number }>>;
  minimum_sample_count: number;
  policy_status: string;
  policy_label: string;
  breakdown_horizon: number;
  sectors: MainlineOutcomeBreakdownRow[];
  market_states: MainlineOutcomeBreakdownRow[];
}

export interface MainlineOutcomeBreakdownRow {
  key: string;
  sample_count: number;
  minimum_sample_count: number;
  eligible_for_policy: boolean;
  avg_return_pct: number;
  win_rate: number;
  failure_rate: number;
}

export interface ResearchSignalSummaryHorizon {
  horizon: number;
  sample_count: number;
  signal_count: number;
  completed_count: number;
  waiting_count: number;
  unavailable_count: number;
  minimum_sample_count: number;
  eligible_for_policy: boolean;
  avg_return_pct: number | null;
  win_rate: number | null;
}

export interface ResearchSignalBreakdown {
  key: string;
  sample_count: number;
  minimum_sample_count: number;
  eligible_for_policy: boolean;
  avg_return_pct: number;
  win_rate: number;
}

export interface ResearchSignalLedger {
  signal_count: number;
  minimum_sample_count: number;
  policy_status: string;
  policy_label: string;
  horizons: Record<number, ResearchSignalSummaryHorizon>;
  breakdown_horizon: number;
  signal_types: ResearchSignalBreakdown[];
  sectors: ResearchSignalBreakdown[];
  execution_funnel: {
    research_only_count: number;
    planned_count: number;
    waiting_entry_count: number;
    not_entered_count: number;
    open_count: number;
    closed_count: number;
    avg_entry_slippage_pct: number | null;
    closed_avg_pnl_pct: number | null;
    closed_win_rate: number | null;
  };
  execution_outcomes: Record<string, Record<number, ResearchSignalSummaryHorizon>>;
  execution_cohorts: Array<{
    signal_type: string;
    market_regime: string;
    horizon: number;
    signal_count: number;
    eligible_group_count: number;
    comparable: boolean;
    fully_comparable: boolean;
    groups: Record<string, ResearchSignalSummaryHorizon>;
  }>;
}

export interface HistoricalSignalReplay {
  source_type: "historical_replay";
  cache_version: string;
  policy_eligible: false;
  research_sample_sufficient: boolean;
  policy_label: string;
  available_snapshot_count: number;
  source_snapshot_count: number;
  evaluated_snapshot_count: number;
  excluded_snapshot_count: number;
  exclusion_reasons: Record<string, number>;
  candidate_exclusion_reasons: Record<string, number>;
  signal_count: number;
  start_date: string | null;
  end_date: string | null;
  covered_month_count: number;
  minimum_sample_count: number;
  horizons: Record<number, ResearchSignalSummaryHorizon>;
  breakdown_horizon: number;
  selection_modes: ResearchSignalBreakdown[];
  market_regimes: ResearchSignalBreakdown[];
  market_states: ResearchSignalBreakdown[];
  sectors: ResearchSignalBreakdown[];
  stability: {
    horizon: number;
    split_method: "chronological_70_30";
    train_end_date: string | null;
    validation_start_date: string | null;
    train: HistoricalReplayResearchMetric;
    validation: HistoricalReplayResearchMetric;
    validation_attribution?: HistoricalReplayAttribution;
    selection_modes: HistoricalReplayStabilityCohort[];
    market_regimes: HistoricalReplayStabilityCohort[];
    market_states: HistoricalReplayStabilityCohort[];
    sectors: HistoricalReplayStabilityCohort[];
    combinations: HistoricalReplayStabilityCohort[];
    monthly: Array<HistoricalReplayResearchMetric & { month: string }>;
  };
  recent_signals: Array<{
    source_type: "historical_replay";
    signal_date: string;
    symbol: string;
    name: string | null;
    sector: string | null;
    selection_mode: string;
    score: number;
    rank: number;
    market_regime: string;
    market_state: string;
    market_participation_score: number | null;
    market_liquidity_score: number | null;
    moneyflow_support_score: number | null;
    sector_fund_flow_score: number | null;
    signal_price: number;
    horizons: Record<number, {
      status: string;
      return_pct: number | null;
      reason: string | null;
    }>;
  }>;
}

export interface HistoricalReplayResearchMetric {
  sample_count: number;
  signal_day_count: number;
  minimum_sample_count: number;
  minimum_signal_day_count: number;
  research_sample_sufficient: boolean;
  avg_return_pct: number | null;
  win_rate: number | null;
}

export interface HistoricalReplayStabilityCohort {
  key: string;
  train: HistoricalReplayResearchMetric;
  validation: HistoricalReplayResearchMetric;
  comparable: boolean;
  stable_positive: boolean;
  validation_delta_pct: number | null;
}

export interface HistoricalReplayAttributionItem {
  key: string;
  sample_count: number;
  signal_day_count: number;
  research_sample_sufficient: boolean;
  sample_share: number;
  avg_return_pct: number;
  win_rate: number;
  return_contribution_pct: number;
}

export interface HistoricalReplayAttribution {
  horizon: number;
  sample_count: number;
  signal_day_count: number;
  market_state_known_count: number;
  market_state_coverage_ratio: number;
  market_participation_known_count: number;
  market_participation_coverage_ratio: number;
  market_liquidity_known_count: number;
  market_liquidity_coverage_ratio: number;
  stock_moneyflow_known_count: number;
  stock_moneyflow_coverage_ratio: number;
  sector_moneyflow_known_count: number;
  sector_moneyflow_coverage_ratio: number;
  selection_modes: HistoricalReplayAttributionItem[];
  market_regimes: HistoricalReplayAttributionItem[];
  market_states: HistoricalReplayAttributionItem[];
  rank_bands: HistoricalReplayAttributionItem[];
  score_bands: HistoricalReplayAttributionItem[];
  market_participation_bands: HistoricalReplayAttributionItem[];
  market_liquidity_bands: HistoricalReplayAttributionItem[];
  stock_moneyflow_bands: HistoricalReplayAttributionItem[];
  sector_moneyflow_bands: HistoricalReplayAttributionItem[];
  sectors: HistoricalReplayAttributionItem[];
}

export interface IntradayExpandingSector {
  sector: string;
  symbol_count: number;
  up_count: number;
  up_ratio: number;
  avg_change_pct: number;
  total_amount?: number;
  leader_symbol?: string;
  leader_change_pct?: number;
}

export interface IntradaySustainedExpandingSector extends IntradayExpandingSector {
  prior_up_ratio: number;
  prior_avg_change_pct: number;
  consecutive_snapshots: number;
}

export interface IntradayLeadingSector extends IntradaySustainedExpandingSector {
  total_amount: number;
  leader_symbol: string;
  leader_change_pct: number;
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
  expected_security_count: number;
  eligible_daily_bar_count: number;
  daily_coverage_ratio: number;
  candidate_generation_allowed: boolean;
  market_regime: string | null;
  market_regime_updated_at: string | null;
  candidate_block_reasons: string[];
  late_market_turn_20d: Record<string, number>;
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

export interface PlanAvailability {
  status: string;
  label: string;
  reason: string;
  gaps: string[];
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
  candidate_retire_reason: string | null;
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
  plan_availability: PlanAvailability;
  plans: WorkspacePlan[];
  paper_trade_summaries: PaperTradeSummary[];
  recent_paper_trades: PaperTrade[];
  manual_refresh?: ManualRefresh | null;
}

export type StartupState = "preheat" | "probing" | "confirmed" | "invalidated";

export interface StartupTrackingRow {
  symbol: string;
  state: StartupState;
  state_label: string;
  state_time: string | null;
  signal_type: `startup_${StartupState}`;
  signal_label: string;
  signal_date: string | null;
  signal_score: number | null;
  signal_reasons: string[];
  confirmation_evidence: string[];
  invalidation_reasons: string[];
  next_conditions: string[];
  plan_available: boolean;
  historical: Record<number, { sample_count: number; win_rate: number | null; raw_return: number | null; guarded_return: number | null }>;
  current_tracking: { realised_return: number | null; horizons: Record<number, "completed" | "in_progress" | "data_pending"> };
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
  startup_stage: StartupState;
  startup_label: string;
  startup_score: number;
  startup_reason: string;
  startup_tracked: boolean;
  startup_prior_state: StartupState | null;
  startup_confirmation_evidence: string[];
  startup_invalidation_reasons: string[];
  startup_next_conditions: string[];
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
  recovery_stage: "blocked" | "limited" | "normal" | string;
  recovery_snapshot_count: number;
  recovery_required_count: number;
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

export interface IntradayCandidateSectorDistributionItem {
  sector: string;
  count: number;
  ratio: number;
}

export interface IntradayCandidateSectorDistribution {
  eligible_count: number;
  displayed_count: number;
  sector_count: number;
  top_sectors: IntradayCandidateSectorDistributionItem[];
}

export interface IntradayCandidateList {
  trade_date: string;
  as_of: string | null;
  pool_name: string;
  candidate_count: number;
  candidate_batch: CandidateBatch;
  market_stress: IntradayMarketStress | null;
  quote_coverage: IntradayQuoteCoverage | null;
  sector_distribution: IntradayCandidateSectorDistribution;
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

export interface IntradayStartupHorizon {
  horizon: number;
  status: "completed" | "waiting" | "unavailable";
  target_trade_date: string | null;
  return_pct: number | null;
  max_gain_pct: number | null;
  max_drawdown_pct: number | null;
}

export interface IntradayStartupOutcome {
  signal_date: string;
  signal_time: string;
  signal_stage: string;
  signal_stage_label: string;
  symbol: string;
  name: string | null;
  sector: string | null;
  startup_stage: StartupState | "starting" | "accelerating";
  startup_label: string;
  startup_score: number;
  signal_price: number;
  market_context: string;
  market_context_label: string;
  market_breadth_ratio: number | null;
  market_index_change_pct: number | null;
  market_regime: string | null;
  previous_market_regime: string | null;
  regime_transition: string | null;
  horizons: Record<number, IntradayStartupHorizon>;
  confirmation_evidence: string[];
  invalidation_reasons: string[];
  next_conditions: string[];
}

export interface IntradayStartupOutcomeSummary {
  sample_count: number;
  win_rate: number | null;
  avg_return_pct: number | null;
  avg_max_gain_pct: number | null;
  avg_max_drawdown_pct: number | null;
}

export interface IntradayRegimeTransitionSummary {
  regime_transition: string;
  sample_count: number;
  win_rate: number;
  avg_return_pct: number;
  is_sufficient_samples: boolean;
}

export interface IntradayStartupOutcomeReport {
  observed_day_count: number;
  signal_day_count: number;
  signal_count: number;
  completed_count: number;
  waiting_count: number;
  unavailable_count: number;
  context_counts: Record<string, number>;
  summary: Record<number, IntradayStartupOutcomeSummary>;
  state_summary: Record<StartupState, Record<number, IntradayStartupOutcomeSummary>>;
  probing_to_confirmed_rate: number | null;
  confirmed_to_invalidated_rate: number | null;
  regime_transition_summary: Record<number, IntradayRegimeTransitionSummary[]>;
  outcomes: IntradayStartupOutcome[];
}

export interface IntradayHistoryHealth {
  window_days: number;
  observed_days: number;
  eligible_days: number;
  missing_quote_days: number;
  missing_market_snapshot_days: number;
  low_coverage_days: number;
  not_ready_days: number;
}

export interface IntradayCandidateSnapshotList {
  trade_date: string;
  pool_name: string;
  snapshots: IntradayCandidateSnapshot[];
  learning: IntradaySnapshotLearning[];
  learning_summary: IntradaySnapshotLearningSummary | null;
  history_health: IntradayHistoryHealth;
  startup_outcomes: IntradayStartupOutcomeReport;
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

export interface ReplayCapitalCurvePoint {
  entry_date: string;
  period_return: number;
  cumulative_return: number;
  drawdown: number;
}

export interface ReplayCapitalReturnSummary extends ReplayReturnSummary {
  max_drawdown: number;
  max_drawdown_limit_pct: number;
  max_drawdown_passed: boolean;
  curve: ReplayCapitalCurvePoint[];
}

export interface ReplayCapitalValidationWindow extends ReplayReturnSummary {
  window: string;
  status: "passed" | "failed" | "insufficient";
  max_drawdown: number;
  max_drawdown_limit_pct: number;
  max_drawdown_passed: boolean;
}

export interface ReplayCapitalValidationSummary {
  status: "passed" | "failed" | "insufficient";
  min_samples_per_window: number;
  valid_window_count: number;
  passed_window_count: number;
  windows: ReplayCapitalValidationWindow[];
}

export interface ReplayCapitalCurveHorizonSummary {
  max_positions: number;
  weighting: string;
  holding_period_days: number;
  return_calculation: string;
  defensive_policy: string;
  raw: ReplayCapitalReturnSummary;
  guarded: ReplayCapitalReturnSummary;
  defensive_breadth: ReplayCapitalReturnSummary;
  defensive_validation?: ReplayCapitalValidationSummary;
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
  capital_curve_horizons?: Record<number, ReplayCapitalCurveHorizonSummary>;
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

export interface MarketStressRecoveryReplayRow {
  threshold_label: string;
  limited_after: number;
  normal_after: number;
  risk_event_count: number;
  completed_recovery_count: number;
  evaluated_recovery_count: number;
  unresolved_event_count: number;
  false_rebound_count: number;
  false_rebound_rate: number | null;
  avg_recovery_days: number | null;
  blocked_days: number;
  limited_days: number;
  blocked_opportunity_days: number;
  limited_opportunity_days: number;
  is_current: boolean;
}

export interface MarketStressRecoveryYearlyRow {
  year: number;
  snapshot_count: number;
  observed_trade_day_count: number;
  data_gap_count: number;
  risk_event_count: number;
  completed_recovery_count: number;
  evaluated_recovery_count: number;
  unresolved_event_count: number;
  false_rebound_count: number;
  false_rebound_rate: number | null;
  avg_recovery_days: number | null;
  blocked_opportunity_days: number;
  limited_opportunity_days: number;
}

export interface MarketStressRecoveryRegimeRow {
  regime: string;
  snapshot_count: number;
  risk_event_count: number;
  completed_recovery_count: number;
  evaluated_recovery_count: number;
  unresolved_event_count: number;
  false_rebound_count: number;
  false_rebound_rate: number | null;
  avg_recovery_days: number | null;
}

export interface MarketStressRecoveryReplayReport {
  start_date: string;
  end_date: string;
  data_source: string;
  market_regime_data_source: string;
  market_regime_cache_version: string;
  min_coverage_ratio: number;
  first_trade_date: string | null;
  last_trade_date: string | null;
  snapshot_count: number;
  observed_trade_day_count: number;
  data_gap_count: number;
  market_regime_coverage_count: number;
  market_regime_gap_count: number;
  false_rebound_window: number;
  recommendation: {
    status: string;
    label: string;
    threshold_label: string;
    summary: string;
  };
  rows: MarketStressRecoveryReplayRow[];
  yearly_rows: MarketStressRecoveryYearlyRow[];
  regime_rows: MarketStressRecoveryRegimeRow[];
  cache: {
    hit: boolean;
    cache_key: string;
    version: string;
  };
}

export interface MarketStressRecoveryReplayQuery {
  start_date?: string;
  end_date?: string;
  min_coverage_ratio?: number;
  force_refresh?: boolean;
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
  core_promotion_gate: {
    scope: string;
    label: string;
    status: string;
    sample_count: number;
    month_count: number;
    positive_months: number;
    negative_months: number;
    min_samples: number;
    min_months: number;
    max_core_positions: number;
    summary: string;
  };
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
  candidate_web_status: string;
  review_status: string;
  dingtalk_status: string;
  moneyflow_status: string;
  moneyflow_rows: number;
  moneyflow_updated_at: string | null;
  plan_refresh_status: string;
  existing_plans: number;
  plan_rows_refreshed: number;
  candidate_recovery_status: string;
  candidate_recovery_summary: string | null;
  candidate_recovery_written: number;
  candidate_recovery_retired: number;
  candidate_retire_reasons: Record<string, number>;
  candidate_recovery_plan_rows: number;
  market_summary: string | null;
  market_regime: string | null;
  market_regime_risk_level: string | null;
  late_market_turn_health: Record<string, unknown>;
  late_market_index_evidence: Record<string, unknown>;
  tushare_evidence_health: TushareEvidenceHealth;
  data_evidence_risk: Record<string, unknown>;
  scheduler_health: Record<string, unknown>;
  source: string;
}

export interface TushareEvidenceDatasetHealth {
  name: "moneyflow" | "moneyflow_dc" | "cyq_perf" | "limit_list_d" | string;
  rows: number;
  matched_rows: number;
  coverage_ratio: number | null;
  status: "ok" | "partial" | "missing" | string;
}

export interface TushareEvidenceHealth {
  trade_date: string;
  daily_symbol_count: number;
  datasets: TushareEvidenceDatasetHealth[];
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
    candidate_retire_reason: item.candidate_retire_reason ?? null,
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
    plan_availability: item.plan_availability ?? {
      status: "unknown",
      label: "计划待确认",
      reason: "计划状态暂未返回。",
      gaps: [],
    },
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

export function fetchIntradayMarketTurn() {
  return request<IntradayMarketTurn>("/market/intraday-turn");
}

export function fetchConfirmedMainlineOutcomes() {
  return request<ConfirmedMainlineOutcome[]>("/market/mainline-outcomes");
}

export function fetchMainlineOutcomeSummary() {
  return request<MainlineOutcomeSummary>("/market/mainline-outcome-summary");
}

export function fetchResearchSignalLedger() {
  return request<ResearchSignalLedger>("/market/research-signal-ledger");
}

export function fetchHistoricalSignalReplay() {
  return request<HistoricalSignalReplay>("/market/research-signal-replay");
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

export function fetchStartupTracking(poolName = "experiment") {
  return request<StartupTrackingRow[]>(`/workspace/startup-tracking?pool_name=${poolName}`);
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
  lookbackDays = 20,
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

export function fetchMarketStressRecoveryReplay(
  query: MarketStressRecoveryReplayQuery = {},
) {
  const params = new URLSearchParams();
  if (query.start_date) params.set("start_date", query.start_date);
  if (query.end_date) params.set("end_date", query.end_date);
  if (query.min_coverage_ratio !== undefined) {
    params.set("min_coverage_ratio", String(query.min_coverage_ratio));
  }
  if (query.force_refresh !== undefined) {
    params.set("force_refresh", String(query.force_refresh));
  }
  return request<MarketStressRecoveryReplayReport>(
    `/rules/market-stress-recovery-replay?${params.toString()}`,
  );
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
