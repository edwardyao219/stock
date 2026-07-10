import { readFileSync } from "node:fs";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");

assert(app.includes('{ key: "paper", label: "实盘模拟" }'), "顶部导航需要有独立的实盘模拟页");
assert(!app.includes('holding: "持仓"'), "普通股票列表不能再混入持仓筛选页签");
assert(app.includes('activePage === "paper"'), "实盘模拟页需要独立渲染，不和股票列表混在一起");
assert(app.includes("paperTradeStocks"), "实盘模拟页需要使用独立列表数据源");

const focusStart = app.indexOf("function isFocusStock");
const focusEnd = app.indexOf("function stockSourceLabel", focusStart);
const focusMarkup = app.slice(focusStart, focusEnd);
const rowStart = app.indexOf("function renderStockRow");
const rowEnd = app.indexOf("function renderPaperTradeRow", rowStart);
const stockRowMarkup = app.slice(rowStart, rowEnd);

assert(!focusMarkup.includes("hasOpenAutoTrade"), "普通重点列表不能靠实盘持仓进入");
assert(!stockRowMarkup.includes("rowTradeLabel"), "普通股票行不能显示实盘模拟收益标签");
assert(!stockRowMarkup.includes("has-open-trade"), "普通股票行不能用实盘持仓高亮");
assert(!stockRowMarkup.includes("paperWinRate"), "普通股票行不能混入纸面交易胜率");
