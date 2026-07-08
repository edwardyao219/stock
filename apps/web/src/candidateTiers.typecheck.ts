import {
  candidateListGateSummary,
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
  {
    symbol: "600111",
    name: "北方稀土",
    industry: "小金属",
    source: "manual",
    manual_note: "候选理由",
    manual_tags: ["after_close_candidate", "tier:sector_watch"],
    candidate_rank: 2,
    candidate_score: 81.0,
    candidate_tier: "sector_watch",
    candidate_tier_label: "板块观察",
    candidate_tier_reason: "防守阶段板块观察：周期资源方向保留代表票",
  },
] as unknown as WorkspaceStock[];

const grouped = groupStocksByCandidateTier(sampleStocks);
const listGateSummary = candidateListGateSummary(
  { ...grouped, coreAction: [] },
  "今天防守阶段，没有核心候选。",
);

grouped.coreAction[0].candidate_tier satisfies
  | "core_action"
  | "sector_watch"
  | "watch_wait"
  | "risk_reject"
  | null;
grouped.sectorWatch.length satisfies number;
grouped.startupPreheat.length satisfies number;
grouped.expansionConfirm.length satisfies number;
grouped.watchWait.length satisfies number;
grouped.riskReject.length satisfies number;
listGateSummary.title satisfies string;
listGateSummary.reason satisfies string;
listGateSummary.coreLimitText satisfies string;
listGateSummary.supportLineText satisfies string;
listGateSummary.styleGateText satisfies string | null;

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

if (/core_action|sector_watch|startup_preheat|risk_reject/.test(Object.values(listGateSummary).join(" "))) {
  throw new Error("候选列表门控摘要不能展示英文分层枚举");
}

if (!listGateSummary.reason.includes("今天防守阶段")) {
  throw new Error("候选列表门控摘要应保留当前无核心候选原因");
}
