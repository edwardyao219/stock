import { readFileSync } from "node:fs";

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");

for (const text of ["启动追踪", "历史验证", "当前跟踪", "进行中"]) {
  if (!app.includes(text)) throw new Error(`缺少启动追踪展示：${text}`);
}
for (const field of [
  "state",
  "state_label",
  "state_time",
  "confirmation_evidence",
  "invalidation_reasons",
  "next_conditions",
  "plan_available",
]) {
  if (!api.includes(field)) throw new Error(`启动追踪类型缺少 ${field}`);
}
for (const field of [
  "item.state",
  "item.state_label",
  "item.confirmation_evidence",
  "item.invalidation_reasons",
  "item.next_conditions",
  "item.plan_available",
]) {
  if (!app.includes(field)) throw new Error(`启动追踪展示缺少 ${field}`);
}
if (app.includes('signal_label === "')) throw new Error("不能通过中文标签推断启动状态");
if (!app.includes("invalidation_reasons?.[0]")) throw new Error("旧追踪载荷缺少失效原因时不能崩溃");
if (!app.includes("confirmation_evidence?.[0]")) throw new Error("旧追踪载荷缺少确认依据时不能崩溃");
if (!app.includes("next_conditions?.[0]")) throw new Error("旧追踪载荷缺少下一条件时不能崩溃");
if (!api.includes("fetchStartupTracking")) throw new Error("启动追踪必须由 API 获取");
