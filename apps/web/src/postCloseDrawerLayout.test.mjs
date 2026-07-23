import { readFileSync } from "node:fs";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const mobileStyles = styles.slice(styles.indexOf("@media (max-width: 760px)"));

const panelStart = app.indexOf('className="post-close-review-panel"');
const nextSection = app.indexOf('className="intraday-watch-strip"', panelStart);
const panelMarkup = app.slice(panelStart, nextSection);

assert(panelStart >= 0, "保留收盘复盘轻量入口");
assert(nextSection > panelStart, "能定位到收盘复盘入口的边界");
assert(app.includes("className={`post-close-review-drawer ${"), "收盘复盘重内容进入抽屉");
assert(styles.includes(".post-close-review-drawer"), "抽屉需要独立样式");
assert(!panelMarkup.includes("post-close-review-grid"), "复盘指标网格不能挤压主页面");
assert(!panelMarkup.includes("post-close-review-details"), "完整复盘文本不能挤压主页面");
assert(!panelMarkup.includes("after-close-push-status"), "6点推送明细不能挤压主页面");
assert(/body\s*\{[^}]*overflow:\s*auto/s.test(styles), "页面需要允许纵向滚动，避免工作区被顶部模块压扁");
assert(/\.app-shell\s*\{[^}]*height:\s*auto/s.test(styles), "桌面外壳不能固定 100vh 后隐藏主工作区");
assert(/\.workspace-layout\s*\{[^}]*min-height:\s*min\(520px,\s*calc\(100vh - 180px\)\)/s.test(styles), "股票工作区需要保留可用高度");
assert(app.includes('className="post-close-review-board"'), "收盘复盘抽屉需要三段式看板");
assert(app.includes('className="post-close-review-column market"'), "看板需要大盘段");
assert(app.includes('className="post-close-review-column sectors"'), "看板需要板块段");
assert(app.includes('className="post-close-review-column candidates"'), "看板需要候选段");
assert(styles.includes(".post-close-sector-bar"), "板块强弱需要条形表达，减少文字墙");
assert(app.includes("Tushare证据"), "收盘抽屉需要展示 Tushare 证据数据状态");
assert(app.includes("moneyflow_dc"), "收盘抽屉需要展示东财资金流状态");
assert(app.includes('moneyflow: "基础资金流"'), "收盘抽屉需要区分基础资金流口径");
assert(app.includes("cyq_perf"), "收盘抽屉需要展示筹码分布状态");
assert(app.includes("limit_list_d"), "收盘抽屉需要展示涨跌停事件状态");
assert(app.includes("tushare_evidence_health"), "收盘抽屉需要读取结构化证据健康状态");
assert(app.includes("late_market_index_evidence"), "收盘抽屉需要展示尾盘指数证据");
assert(app.includes("尾盘指数"), "尾盘指数证据需要有明确标签");
assert(styles.includes(".after-close-evidence"), "尾盘证据需要使用独立紧凑样式");
assert(app.includes("afterCloseStepText"), "收盘抽屉需要把盘后步骤名转换为中文");
assert(app.includes("health?.current_step"), "收盘抽屉需要展示当前执行步骤");
assert(app.includes("health?.last_heartbeat_at"), "收盘抽屉需要展示最近心跳时间");
assert(app.includes("plan_rows_refreshed"), "收盘抽屉需要展示资金流到达后的计划刷新数量");
assert(app.includes("moneyflow_updated_at"), "收盘抽屉需要展示基础资金流更新时间");
assert(app.includes("cyq_perf_status"), "收盘抽屉需要展示筹码分布补采状态");
assert(app.includes("cyq_perf_updated_at"), "收盘抽屉需要展示筹码分布更新时间");
assert(
  app.includes('const reviewTradeDate = reviewMetricRecord(review, "market_summary")?.trade_date;'),
  "盘后状态查询需要优先使用复盘数据交易日",
);
assert(
  !app.includes("loadAfterCloseStatus(marketOverview?.trade_date)"),
  "盘后状态不能使用可能领先于复盘的今日行情日期",
);
assert(
  /\.intraday-watch-list\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s.test(mobileStyles),
  "移动端盘中候选空状态不能撑出页面宽度",
);
assert(
  /\.post-close-review-board\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s.test(mobileStyles),
  "移动端收盘复盘需要单列展示，避免三栏内容过窄",
);
