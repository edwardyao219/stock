import { readFileSync } from "node:fs";

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");

for (const text of ["启动追踪", "启动观察", "启动确认", "历史验证", "当前跟踪", "进行中"]) {
  if (!app.includes(text)) throw new Error(`缺少启动追踪展示：${text}`);
}
if (!api.includes("fetchStartupTracking")) throw new Error("启动追踪必须由 API 获取");
