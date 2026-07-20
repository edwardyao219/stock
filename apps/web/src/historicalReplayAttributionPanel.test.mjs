import { readFileSync } from "node:fs";

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

for (const field of [
  "validation_attribution",
  "return_contribution_pct",
  "market_state_coverage_ratio",
]) {
  if (!api.includes(field)) throw new Error(`历史回放归因接口缺少：${field}`);
}

for (const text of [
  "近期亏损归因",
  "市场状态覆盖",
  "市场环境拖累",
  "对近期均值贡献",
  "占比",
  "胜率",
  "覆盖不足，不据此调参",
  "暂无成熟样本 / 覆盖待评估",
]) {
  if (!app.includes(text)) throw new Error(`历史回放归因面板缺少：${text}`);
}

if (!styles.includes(".historical-attribution-grid")) {
  throw new Error("历史回放归因必须使用稳定响应式网格");
}
if (!styles.includes(".historical-replay-attribution .snapshot-review-head")) {
  throw new Error("窄屏归因标题与样本说明必须上下排列");
}

if (!app.includes("historicalSignalReplay.stability.validation_attribution ?")) {
  throw new Error("旧版 API 缺少归因字段时不能导致板块页白屏");
}
for (const field of [
  "validation_attribution.market_regimes",
  "validation_attribution.market_states",
  "item.sample_share",
  "item.win_rate",
  "validation_attribution.sample_count ?",
]) {
  if (!app.includes(field)) throw new Error(`历史回放归因展示缺少：${field}`);
}
