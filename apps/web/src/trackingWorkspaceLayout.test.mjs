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
assert(app.includes("trackingHistory"), "个股追踪页需要读取真实追踪快照历史");
assert(app.includes("tracking-history-panel"), "个股追踪页需要独立展示追踪分变化");
assert(app.includes("信号汇总"), "个股追踪页需要展示多票分价验证汇总");
assert(app.includes("数据成熟度"), "个股追踪页需要提示追踪快照是否足够验证");
assert(app.includes("板块验证"), "个股追踪页需要先按板块验证，再看个股");
assert(app.includes("追踪路径"), "个股追踪页需要用路径视图表达单票跟踪质量");
assert(app.includes("跟踪收益"), "个股追踪页需要展示真实价格表现，避免只看追踪分自循环");
assert(app.includes("信号验证"), "个股追踪页需要展示追踪分和真实收益是否同向");
assert(app.includes("追踪状态"), "个股追踪页需要展示当前追踪状态");
assert(app.includes("启动阶段"), "个股追踪页需要展示启动阶段");
assert(app.includes("tracking-state-grid"), "追踪状态和启动阶段需要独立视觉区域");
assert(app.includes("生成今日快照"), "个股追踪页需要提供手动生成今日快照入口");
assert(!app.includes("{!loading ? trackingProfiles.map(renderTrackingRow) : null}"), "刷新中有旧追踪数据时也要继续展示列表");
assert(styles.includes(".tracking-workspace-panel"), "个股追踪需要独立布局样式");
assert(styles.includes(".tracking-timeline"), "追踪时间线需要独立样式，避免挤在详情页文本里");
assert(styles.includes(".tracking-candle-path"), "K线趋势路径需要独立样式，避免塞成文字墙");
assert(styles.includes(".tracking-history-panel"), "追踪分变化需要独立样式，避免继续堆文字");
assert(styles.includes(".tracking-path-chart"), "追踪路径需要独立图形样式，避免继续堆文字");

const stockDetailStart = app.indexOf('className="stock-detail-panel"');
const trackingPageStart = app.indexOf('activePage === "tracking"');
const stockDetailMarkup = app.slice(stockDetailStart, trackingPageStart);

assert(!stockDetailMarkup.includes("tracking-timeline"), "追踪时间线不能塞进普通股票详情页");
assert(!stockDetailMarkup.includes("tracking-candle-path"), "K线趋势路径不能塞进普通股票详情页");
assert(!stockDetailMarkup.includes("tracking-history-panel"), "追踪分变化不能塞进普通股票详情页");

const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
assert(api.includes("export interface TrackingSnapshot"), "API 类型需要暴露追踪快照");
assert(api.includes("tracking_state_label"), "API 类型需要暴露追踪状态标签");
assert(api.includes("startup_phase_label"), "API 类型需要暴露启动阶段标签");
assert(api.includes("export interface TrackingSignalSector"), "API 类型需要暴露板块追踪汇总");
assert(api.includes("fetchTrackingSnapshots"), "前端需要读取单只股票追踪快照历史");
assert(api.includes("createTrackingSnapshots"), "前端需要触发生成今日追踪快照");
