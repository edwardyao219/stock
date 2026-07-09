import { candidatePoolTextForStock, manualTagTextForStock } from "./stockLabels";

function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

const normalCandidateWithHistoricalStarTag = {
  symbol: "601066",
  manual_tags: ["after_close_candidate", "next_session", "star_pool"],
};

const starCandidate = {
  symbol: "688001",
  manual_tags: ["after_close_candidate", "next_session"],
};

const expansionCandidate = {
  symbol: "002669",
  manual_tags: ["after_close_candidate", "next_session", "candidate_pool:expansion_confirm"],
};

const startupPreheatCandidate = {
  symbol: "002558",
  manual_tags: ["after_close_candidate", "next_session", "candidate_pool:startup_preheat"],
};

assertEqual(
  candidatePoolTextForStock(normalCandidateWithHistoricalStarTag),
  "普通池",
  "普通股即使带历史 star_pool 标签也不能显示成科创池",
);
assertEqual(candidatePoolTextForStock(starCandidate), "科创池", "688 才显示科创池");
assertEqual(
  candidatePoolTextForStock(expansionCandidate),
  "扩散确认池",
  "扩散确认候选需要单独显示池子",
);
assertEqual(
  candidatePoolTextForStock(startupPreheatCandidate),
  "启动前夜池",
  "启动前夜候选需要单独显示池子",
);
assertEqual(
  manualTagTextForStock("star_pool", normalCandidateWithHistoricalStarTag),
  "历史分池",
  "普通股历史 star_pool 标签不能翻译成科创池",
);
assertEqual(
  manualTagTextForStock("star_pool", starCandidate),
  "科创池",
  "688 的 star_pool 标签仍可显示为科创池",
);
assertEqual(
  manualTagTextForStock("style:growth_cycle", normalCandidateWithHistoricalStarTag),
  "科技成长",
  "候选风格标签需要显示为用户可读文本",
);
assertEqual(
  manualTagTextForStock("style:market_beta", normalCandidateWithHistoricalStarTag),
  "市场弹性",
  "风格标签里不能显示英文 Beta",
);
assertEqual(
  manualTagTextForStock("style_horizon:10d", normalCandidateWithHistoricalStarTag),
  "建议10日观察",
  "候选周期标签需要显示为用户可读文本",
);
assertEqual(
  manualTagTextForStock("style_gate:upgrade_allowed", startupPreheatCandidate),
  "门控：盘中重点观察",
  "门控状态不能露出英文枚举",
);
assertEqual(
  manualTagTextForStock("style_gate:stand_down", startupPreheatCandidate),
  "门控：暂不升级",
  "暂不升级门控需要显示为中文",
);
assertEqual(
  manualTagTextForStock(
    "style_gate_reason:科技成长启动前夜可盘中重点观察，不代表买点。",
    startupPreheatCandidate,
  ),
  "科技成长启动前夜可盘中重点观察，不代表买点。",
  "门控原因需要直接显示中文理由",
);
assertEqual(
  manualTagTextForStock("candidate_pool:expansion_confirm", expansionCandidate),
  "扩散确认池",
  "扩散确认标签需要显示为用户可读文本",
);
assertEqual(
  manualTagTextForStock("candidate_pool:startup_preheat", startupPreheatCandidate),
  "启动前夜池",
  "启动前夜标签需要显示为用户可读文本",
);
assertEqual(
  manualTagTextForStock(
    "candidate_pool_reason:只做Web观察，不进核心。",
    startupPreheatCandidate,
  ),
  "只做网页端观察，不进核心。",
  "后端原因里的 Web 也要显示成中文",
);
assertEqual(
  manualTagTextForStock(
    "candidate_pool_reason:风格周期：unknown偏10日观察；允许升级为Web重点；growth_cycle继续看承接。",
    startupPreheatCandidate,
  ),
  "风格周期：未分类偏10日观察；允许升级为网页端重点；科技成长继续看承接。",
  "后端原因里的风格枚举也要显示成中文",
);
assertEqual(
  manualTagTextForStock(
    "candidate_summary:没有核心行动：情绪阀门risk_off，先按弱市降级观察。",
    startupPreheatCandidate,
  ),
  "没有核心行动：情绪阀门弱市防守，先按弱市降级观察。",
  "候选摘要里的风险枚举不能露出英文",
);
assertEqual(
  manualTagTextForStock("mode:potential_watch", startupPreheatCandidate),
  "潜力观察",
  "候选模式标签不能露出英文枚举",
);
assertEqual(
  manualTagTextForStock("tier:watch_wait", startupPreheatCandidate),
  "分层：观察等待",
  "候选分层标签不能露出英文枚举",
);
assertEqual(
  manualTagTextForStock("strategy:watch_breakout", startupPreheatCandidate),
  "策略：观察突破",
  "策略标签不能露出英文枚举",
);
assertEqual(
  manualTagTextForStock("rank:3", startupPreheatCandidate),
  "排序：3",
  "候选排序标签不能露出英文前缀",
);
assertEqual(
  manualTagTextForStock("startup_signal_score:82.5", startupPreheatCandidate),
  "启动信号：82.5分",
  "启动信号分数不能露出英文前缀",
);
assertEqual(
  manualTagTextForStock("startup_signal_label:启动观察", startupPreheatCandidate),
  "启动观察",
  "启动信号标签需要直接显示中文",
);
assertEqual(
  manualTagTextForStock(
    "startup_signal_reason:风险可控：不代表买点，只观察次日承接",
    startupPreheatCandidate,
  ),
  "风险可控：不代表买点，只观察次日承接",
  "启动信号原因需要直接显示中文",
);
assertEqual(
  manualTagTextForStock("score:70.25", startupPreheatCandidate),
  "分数：70.25",
  "候选分数标签不能露出英文前缀",
);
