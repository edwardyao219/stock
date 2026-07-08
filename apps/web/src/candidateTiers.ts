import type { WorkspaceStock } from "./api";

export type CandidateTier = "core_action" | "sector_watch" | "watch_wait" | "risk_reject";

export interface CandidateTierMeta {
  tier: CandidateTier;
  label: string;
  reason: string;
}

export interface CandidateTierGroups {
  coreAction: WorkspaceStock[];
  sectorWatch: WorkspaceStock[];
  startupPreheat: WorkspaceStock[];
  expansionConfirm: WorkspaceStock[];
  watchWait: WorkspaceStock[];
  riskReject: WorkspaceStock[];
}

export interface CandidateListGateSummary {
  title: string;
  reason: string;
  postureText: string;
  coreLimitText: string;
  dingPolicyText: string;
  mainLineText: string;
  supportLineText: string;
  styleGateText: string | null;
}

const tierLabels: Record<CandidateTier, string> = {
  core_action: "核心行动",
  sector_watch: "板块观察",
  watch_wait: "观察等待",
  risk_reject: "淘汰/风险",
};

function tagValue(stock: WorkspaceStock, prefix: string) {
  const tag = stock.manual_tags.find((item) => item.startsWith(prefix));
  return tag ? tag.slice(prefix.length).trim() : null;
}

function fallbackTier(stock: WorkspaceStock): CandidateTier {
  const tags = stock.manual_tags;
  const note = stock.manual_note ?? "";
  if (/放量诱多|放量回落|冲高翻绿|近涨停未封|风险信号偏重/.test(note)) {
    return "risk_reject";
  }
  if (
    tags.includes("mode:observation") ||
    tags.includes("mode:potential_watch") ||
    tags.includes("mode:exploration")
  ) {
    return "watch_wait";
  }
  if (stock.candidate_rank !== null && stock.candidate_rank !== undefined && stock.candidate_rank <= 3) {
    return "core_action";
  }
  return "watch_wait";
}

export function candidateTierMeta(stock: WorkspaceStock): CandidateTierMeta {
  const tagTier = tagValue(stock, "tier:") as CandidateTier | null;
  const tier = stock.candidate_tier ?? tagTier ?? fallbackTier(stock);
  const reason =
    stock.candidate_tier_reason ??
    tagValue(stock, "tier_reason:") ??
    (tier === "core_action"
      ? "板块和个股趋势同时在线，作为核心行动候选；盘中仍看承接。"
      : tier === "sector_watch"
        ? "防守阶段板块观察：每个方向保留代表票，交给人盘中判断，非买点。"
      : tier === "watch_wait"
        ? "趋势仍可跟踪，但还需要买点、板块延续或盘中承接确认。"
        : "风险信号偏重，暂不纳入行动池。");
  return {
    tier,
    label: stock.candidate_tier_label ?? tierLabels[tier],
    reason,
  };
}

export function groupStocksByCandidateTier(stocks: WorkspaceStock[]): CandidateTierGroups {
  return stocks.reduce<CandidateTierGroups>(
    (groups, stock) => {
      const { tier } = candidateTierMeta(stock);
      if (tier === "core_action") {
        groups.coreAction.push(stock);
      } else if (tier === "sector_watch") {
        groups.sectorWatch.push(stock);
      } else if (tier === "risk_reject") {
        groups.riskReject.push(stock);
      } else if (stock.manual_tags.includes("candidate_pool:startup_preheat")) {
        groups.startupPreheat.push(stock);
      } else if (stock.manual_tags.includes("candidate_pool:expansion_confirm")) {
        groups.expansionConfirm.push(stock);
      } else {
        groups.watchWait.push(stock);
      }
      return groups;
    },
    {
      coreAction: [],
      sectorWatch: [],
      startupPreheat: [],
      expansionConfirm: [],
      watchWait: [],
      riskReject: [],
    },
  );
}

export function candidateCoreBlockReason(stocks: WorkspaceStock[]): string | null {
  for (const stock of stocks) {
    const reason = tagValue(stock, "candidate_summary:");
    if (reason) return reason;
  }
  return null;
}

export function candidateListGateSummary(
  groups: CandidateTierGroups,
  blockReason?: string | null,
): CandidateListGateSummary {
  const coreCount = groups.coreAction.length;
  const supportCount = groups.sectorWatch.length + groups.startupPreheat.length + groups.expansionConfirm.length;
  return {
    title: coreCount > 0 ? `今天核心行动 ${coreCount} 只` : "今天先观察，不推核心",
    reason:
      blockReason ??
      (coreCount > 0
        ? "已有少数核心候选，仍要等板块延续、量能和盘中承接确认。"
        : "当前候选以板块观察、启动前夜和风险淘汰为主，先交给盘中验证。"),
    postureText: `候选分层：核心 ${coreCount} 只，观察预热 ${supportCount} 只，风险淘汰 ${groups.riskReject.length} 只。`,
    coreLimitText:
      coreCount > 0
        ? `页面核心 ${coreCount} 只，钉钉仍按少量核心处理。`
        : "钉钉核心上限暂按 0 只处理，网页端保留观察和学习。",
    dingPolicyText: coreCount > 0 ? "钉钉策略：核心少量推送" : "钉钉策略：暂不推核心，只做网页观察",
    mainLineText: coreCount > 0 ? "主线：已有核心候选，继续看板块和量能" : "主线：未确认，不追高",
    supportLineText: `辅线：板块观察 ${groups.sectorWatch.length} 只，启动前夜 ${groups.startupPreheat.length} 只，扩散确认 ${groups.expansionConfirm.length} 只。`,
    styleGateText: "风格门控：等待回放诊断加载，先看板块强弱和个股承接。",
  };
}

export function candidatePoolReason(stock: WorkspaceStock): string | null {
  return tagValue(stock, "candidate_pool_reason:");
}
