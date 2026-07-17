import { readFileSync } from "node:fs";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const mobileStyles = styles.slice(styles.indexOf("@media (max-width: 760px)"));

for (const field of ["startup_stage", "startup_label", "startup_score", "startup_reason"]) {
  assert(api.includes(field), `盘中候选类型缺少 ${field}`);
}

assert(app.includes("item.startup_label"), "盘中候选需要直接显示启动阶段");
assert(app.includes("item.startup_score.toFixed(1)"), "盘中候选需要显示启动分");
assert(app.includes("item.startup_reason"), "盘中候选需要展示可解释的启动依据");
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
