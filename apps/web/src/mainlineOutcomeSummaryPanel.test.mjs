import { readFileSync } from "node:fs";

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");

for (const text of ["平均收益", "胜率", "失效率"]) {
  if (!app.includes(text)) throw new Error(`启动信号汇总缺少：${text}`);
}
if (!api.includes("fetchMainlineOutcomeSummary")) {
  throw new Error("前端必须读取启动信号汇总接口");
}
