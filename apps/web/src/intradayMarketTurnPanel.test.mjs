import { readFileSync } from "node:fs";

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");

for (const text of ["市场环境", "主线启动", "启动观察", "启动确认", "未启动"]) {
  if (!app.includes(text)) throw new Error(`盘中摘要缺少主线启动状态：${text}`);
}
if (!app.includes("intradayMainlineStatus")) {
  throw new Error("主线启动状态必须由独立函数计算");
}
