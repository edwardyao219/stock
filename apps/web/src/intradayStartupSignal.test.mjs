import { readFileSync } from "node:fs";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const mobileStyles = styles.slice(styles.indexOf("@media (max-width: 760px)"));

for (const field of [
  "startup_stage",
  "startup_label",
  "startup_score",
  "startup_reason",
  "startup_tracked",
  "startup_prior_state",
  "startup_confirmation_evidence",
  "startup_invalidation_reasons",
  "startup_next_conditions",
]) {
  assert(api.includes(field), `盘中候选类型缺少 ${field}`);
}

for (const field of [
  "startup_outcomes",
  "max_gain_pct",
  "max_drawdown_pct",
  "market_context_label",
  "regime_transition_summary",
  "state_summary",
  "probing_to_confirmed_rate",
  "confirmed_to_invalidated_rate",
  "is_sufficient_samples",
  "history_health",
  "eligible_days",
]) {
  assert(api.includes(field), `启动效果类型缺少 ${field}`);
}

assert(app.includes("item.startup_label"), "盘中候选需要直接显示启动阶段");
assert(app.includes("item.startup_stage"), "盘中候选样式必须使用规范化状态");
assert(app.includes("item.startup_confirmation_evidence"), "盘中候选需要显示确认依据");
assert(app.includes("item.startup_invalidation_reasons"), "盘中候选需要显示失效原因");
assert(app.includes("item.startup_next_conditions"), "盘中候选需要显示下一观察条件");
assert(app.includes("startup_invalidation_reasons?.[0]"), "旧候选载荷缺失失效原因时不能崩溃");
assert(app.includes("startup_confirmation_evidence?.[0]"), "旧候选载荷缺失确认依据时不能崩溃");
assert(app.includes("startup_next_conditions?.[0]"), "旧候选载荷缺失下一条件时不能崩溃");
assert(app.includes("item.startup_score.toFixed(1)"), "盘中候选需要显示启动分");
assert(app.includes("item.startup_reason"), "盘中候选需要展示可解释的启动依据");
assert(app.includes("[1, 3, 5].map"), "盘中复盘需要覆盖1/3/5日启动效果");
assert(app.includes("{horizon}日验证"), "盘中复盘需要显示各期限验证标签");
assert(app.includes("market_context_label"), "启动效果需要显示信号发生时的市场环境");
assert(app.includes("阶段切换回看"), "启动效果需要展示市场阶段切换回看");
assert(app.includes("仅观察"), "阶段切换统计必须明确仅观察");
assert(app.includes("历史数据门禁"), "启动效果需要展示历史数据门禁结果");
assert(styles.includes(".startup-outcome-list"), "启动效果列表需要独立且直观的排版");
assert(styles.includes(".regime-transition-table"), "阶段切换回看需要紧凑表格排版");
assert(styles.includes(".history-health-strip"), "历史数据门禁需要独立且紧凑的排版");
assert(styles.includes(".startup-state.startup-probing"), "启动试探需要独立状态色");
assert(styles.includes(".startup-state.startup-invalidated"), "启动失效需要独立状态色");
assert(!app.includes('startup_label === "'), "不能通过中文标签推断启动状态");
assert(
  /\.intraday-watch-strip\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s.test(
    mobileStyles,
  ),
  "移动端盘中候选标题和内容需要纵向堆叠",
);
assert(
  /\.intraday-watch-item\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s.test(
    mobileStyles,
  ),
  "移动端单只候选的启动信息需要纵向展示",
);
