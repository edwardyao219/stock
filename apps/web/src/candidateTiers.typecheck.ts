import {
  candidateCoreBlockReason,
  candidatePoolReason,
  groupStocksByCandidateTier,
} from "./candidateTiers";
import type { WorkspaceStock } from "./api";

const sampleStocks = [
  {
    symbol: "603005",
    name: "晶方科技",
    industry: "半导体",
    source: "manual",
    manual_note: "候选理由",
    manual_tags: ["after_close_candidate", "tier:core_action"],
    candidate_rank: 1,
    candidate_score: 88.4,
    candidate_tier: "core_action",
    candidate_tier_label: "核心行动",
    candidate_tier_reason: "板块和个股趋势同时在线",
  },
] as unknown as WorkspaceStock[];

const grouped = groupStocksByCandidateTier(sampleStocks);

grouped.coreAction[0].candidate_tier satisfies "core_action" | "watch_wait" | "risk_reject" | null;
grouped.expansionConfirm.length satisfies number;
grouped.watchWait.length satisfies number;
grouped.riskReject.length satisfies number;

const blockReason = candidateCoreBlockReason([
  {
    symbol: "002669",
    name: "康达新材",
    industry: "化工原料",
    source: "manual",
    manual_note: "候选理由",
    manual_tags: ["candidate_summary:没有核心行动：当前候选都是潜力观察，板块或买点还没确认。"],
    candidate_rank: 1,
    candidate_score: 66.9,
  },
] as unknown as WorkspaceStock[]);

blockReason satisfies string | null;

const expansionReason = candidatePoolReason({
  symbol: "002669",
  name: "康达新材",
  industry: "化工原料",
  source: "manual",
  manual_note: "候选理由",
  manual_tags: [
    "candidate_pool:expansion_confirm",
    "candidate_pool_reason:扩散确认：板块扩散和个股启动同步，先观察承接，不进核心。",
  ],
  candidate_rank: 2,
  candidate_score: 72,
} as unknown as WorkspaceStock);

expansionReason satisfies string | null;
