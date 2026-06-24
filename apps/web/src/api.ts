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
  latest_trade_date: string | null;
  latest_close: number | null;
  current_price: number | null;
  day_change_pct: number | null;
  quote_time: string | null;
  return_5d: number | null;
  return_20d: number | null;
  plans: WorkspacePlan[];
  paper_trade_summaries: PaperTradeSummary[];
  recent_paper_trades: PaperTrade[];
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

function normalizeWorkspaceStock(item: WorkspaceStock): WorkspaceStock {
  return {
    ...item,
    manual_tags: item.manual_tags ?? [],
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

export function fetchWorkspaceStocks(poolName = "experiment") {
  const params = new URLSearchParams({ pool_name: poolName });
  return request<WorkspaceStock[]>(`/workspace/stocks?${params.toString()}`).then((items) =>
    items.map(normalizeWorkspaceStock),
  );
}

export function addManualStock(symbol: string, note: string, tags: string[]) {
  return request<WorkspaceStock>("/workspace/manual-stocks", {
    method: "POST",
    body: JSON.stringify({ symbol, note: note || null, tags }),
  }).then(normalizeWorkspaceStock);
}

export function runPipelineStage(payload: PipelineRunPayload) {
  return request<PipelineRunResult>("/jobs/pipeline/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
