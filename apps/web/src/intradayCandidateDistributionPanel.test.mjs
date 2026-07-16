import { readFileSync } from "node:fs";

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");

if (!app.includes("候选板块") || !app.includes("intradaySectorDistributionText")) {
  throw new Error("盘中候选必须展示板块分布说明");
}
if (!api.includes("sector_distribution")) {
  throw new Error("盘中候选 API 类型必须包含板块分布");
}
