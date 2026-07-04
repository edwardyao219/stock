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
  manualTagTextForStock("style_horizon:10d", normalCandidateWithHistoricalStarTag),
  "建议10日观察",
  "候选周期标签需要显示为用户可读文本",
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
