import { readFileSync } from "node:fs";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

assert(app.includes("数据链路"), "数据健康面板需要展示数据链路状态");
assert(app.includes("收盘任务"), "数据健康面板需要提示收盘任务节点");
assert(app.includes("指数日期"), "数据健康面板需要对比指数日期和日线日期");
assert(styles.includes(".data-health-schedule"), "数据链路状态需要独立样式，避免挤进异常文本");
