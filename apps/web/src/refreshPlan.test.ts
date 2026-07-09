// @ts-ignore Node's experimental TypeScript runner needs the explicit extension.
import { buildAutoRefreshPlan } from "./refreshPlan.ts";

function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${String(expected)}, got ${String(actual)}`);
  }
}

const stockPagePlan = buildAutoRefreshPlan({
  activePage: "stocks",
  selectedSymbol: "003043",
  isDocumentVisible: true,
});

assertEqual(stockPagePlan.workspace, true, "股票页仍要刷新工作台和盘中候选");
assertEqual(stockPagePlan.intradayCandidates, false, "工作台刷新已经包含盘中候选，不能重复请求");
assertEqual(stockPagePlan.sectorOverview, false, "股票页自动刷新不能重复拉板块总览");
assertEqual(stockPagePlan.candles, true, "选中股票时仍要刷新K线");

const sectorPagePlan = buildAutoRefreshPlan({
  activePage: "sectors",
  selectedSymbol: null,
  isDocumentVisible: true,
});

assertEqual(sectorPagePlan.sectorOverview, true, "板块页需要刷新板块总览");
assertEqual(sectorPagePlan.sectorCatalysts, true, "板块页需要刷新消息催化");
assertEqual(sectorPagePlan.dataHealth, true, "板块页需要刷新数据健康");

const hiddenPlan = buildAutoRefreshPlan({
  activePage: "sectors",
  selectedSymbol: "003043",
  isDocumentVisible: false,
});

assertEqual(hiddenPlan.workspace, false, "隐藏标签页不能后台打重请求");
assertEqual(hiddenPlan.marketOverview, false, "隐藏标签页不能刷新行情总览");
