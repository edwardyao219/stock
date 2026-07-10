import { readFileSync } from "node:fs";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

assert(app.includes('{ key: "tracking", label: "个股追踪" }'), "顶部导航需要有独立的个股追踪页");
assert(app.includes('activePage === "tracking"'), "个股追踪必须独立渲染");
assert(app.includes("trackingProfiles"), "个股追踪页需要使用独立追踪数据源");
assert(app.includes("tracking-timeline"), "个股追踪页需要时间线表达");
assert(app.includes("tracking-candle-path"), "个股追踪页需要单独展示K线趋势路径");
assert(!app.includes("{!loading ? trackingProfiles.map(renderTrackingRow) : null}"), "刷新中有旧追踪数据时也要继续展示列表");
assert(styles.includes(".tracking-workspace-panel"), "个股追踪需要独立布局样式");
assert(styles.includes(".tracking-timeline"), "追踪时间线需要独立样式，避免挤在详情页文本里");
assert(styles.includes(".tracking-candle-path"), "K线趋势路径需要独立样式，避免塞成文字墙");

const stockDetailStart = app.indexOf('className="stock-detail-panel"');
const trackingPageStart = app.indexOf('activePage === "tracking"');
const stockDetailMarkup = app.slice(stockDetailStart, trackingPageStart);

assert(!stockDetailMarkup.includes("tracking-timeline"), "追踪时间线不能塞进普通股票详情页");
assert(!stockDetailMarkup.includes("tracking-candle-path"), "K线趋势路径不能塞进普通股票详情页");
