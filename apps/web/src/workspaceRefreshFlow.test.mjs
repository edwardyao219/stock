import { readFileSync } from "node:fs";

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const loadStart = app.indexOf("  async function loadWorkspace(");
const loadEnd = app.indexOf("  async function loadCandles", loadStart);
const loadWorkspace = app.slice(loadStart, loadEnd);

if (loadStart < 0 || loadEnd < 0) throw new Error("找不到工作台刷新逻辑");
if (loadWorkspace.includes("refreshWorkspaceStocks")) {
  throw new Error("工作台刷新不能与盘中候选重复抓取实时行情");
}
if (!loadWorkspace.includes("const refreshedIntradayCandidates = options.refreshQuotes")) {
  throw new Error("实时刷新需要先更新盘中候选和热门板块行情");
}
if (!app.includes("isHeavyTaskRunning: refreshing ||")) {
  throw new Error("上一轮自动刷新未结束时不能继续排队");
}
