import {
  BarChart3,
  ClipboardList,
  RefreshCw,
  Search,
  TrendingUp,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  Candle,
  WorkspaceStock,
  addManualStock,
  fetchCandles,
  fetchWorkspaceStocks,
} from "./api";
import { StrategyEvidenceChart } from "./StrategyEvidenceChart";

const sourceLabels: Record<string, string> = {
  auto: "系统筛选",
  manual: "手动关注",
  "auto+manual": "系统+手动",
};

const strategyLabels: Record<string, string> = {
  short_term: "短线",
  swing: "波段",
  long_term: "长线",
  filter: "过滤",
};

const pageItems = [
  { key: "stocks", label: "股票" },
  { key: "sectors", label: "板块" },
] as const;

type PageKey = (typeof pageItems)[number]["key"];
type PaperTrade = WorkspaceStock["recent_paper_trades"][number];

function pct(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function price(value: number | null | undefined) {
  if (value === null || value === undefined) return "-";
  return value.toFixed(2);
}

function riskText(plan: WorkspaceStock["plans"][number]) {
  return `仓位 ${(plan.position_size * 100).toFixed(1)}% / 止损 ${price(
    plan.initial_stop,
  )} / 止盈 ${price(plan.take_profit_1)}`;
}

function exitReasonText(value: string | null | undefined) {
  const labels: Record<string, string> = {
    stop_loss: "止损",
    take_profit: "止盈",
    trailing_take_profit: "跟踪止盈",
    time_exit: "时间退出",
  };
  return value ? labels[value] ?? value : "-";
}

function tradeStatusText(value: string | null | undefined) {
  const labels: Record<string, string> = {
    open: "持仓中",
    closed: "已卖出",
  };
  return value ? labels[value] ?? value : "-";
}

function primaryPaperTrade(stock: WorkspaceStock): PaperTrade | null {
  return stock.recent_paper_trades.find((trade) => trade.status === "open") ?? stock.recent_paper_trades[0] ?? null;
}

function tradeReturnPct(trade: PaperTrade | null, latestClose: number | null | undefined) {
  if (!trade) return null;
  if (trade.pnl_pct !== null && trade.pnl_pct !== undefined) return trade.pnl_pct;
  if (trade.status === "open" && latestClose && trade.entry_price) {
    return latestClose / trade.entry_price - 1;
  }
  return null;
}

function paperClosedCount(stock: WorkspaceStock) {
  return stock.paper_trade_summaries.reduce((total, item) => total + item.closed_count, 0);
}

function paperWinRate(stock: WorkspaceStock) {
  const closedCount = paperClosedCount(stock);
  if (!closedCount) return null;
  const wins = stock.paper_trade_summaries.reduce(
    (total, item) => total + item.win_rate * item.closed_count,
    0,
  );
  return wins / closedCount;
}

export function App() {
  const [activePage, setActivePage] = useState<PageKey>("stocks");
  const [stocks, setStocks] = useState<WorkspaceStock[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [manualSymbol, setManualSymbol] = useState("");
  const [manualNote, setManualNote] = useState("");
  const [sourceFilter, setSourceFilter] = useState<"all" | "auto" | "manual">("all");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [tradeDialogOpen, setTradeDialogOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => stocks.find((item) => item.symbol === selectedSymbol) ?? stocks[0] ?? null,
    [stocks, selectedSymbol],
  );

  const filteredStocks = useMemo(() => {
    const keyword = query.trim();
    return stocks.filter((item) => {
      const matchSource =
        sourceFilter === "all" ||
        (sourceFilter === "auto" && item.source.includes("auto")) ||
        (sourceFilter === "manual" && item.source.includes("manual"));
      const matchKeyword =
        !keyword ||
        item.symbol.includes(keyword) ||
        (item.name ?? "").includes(keyword) ||
        (item.industry ?? "").includes(keyword);
      return matchSource && matchKeyword;
    });
  }, [stocks, query, sourceFilter]);

  async function loadWorkspace() {
    setLoading(true);
    setError(null);
    try {
      const nextStocks = await fetchWorkspaceStocks();
      setStocks(nextStocks);
      setSelectedSymbol((current) => {
        if (current && nextStocks.some((item) => item.symbol === current)) return current;
        return nextStocks[0]?.symbol ?? null;
      });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  async function loadCandles(symbol: string) {
    try {
      setCandles(await fetchCandles(symbol));
    } catch {
      setCandles([]);
    }
  }

  async function addManualFocus() {
    const symbol = manualSymbol.trim();
    if (!symbol) return;
    await addManualStock(symbol, manualNote, []);
    setManualSymbol("");
    setManualNote("");
    setSelectedSymbol(symbol);
    await loadWorkspace();
  }

  useEffect(() => {
    loadWorkspace();
  }, []);

  useEffect(() => {
    if (selected?.symbol) loadCandles(selected.symbol);
    setTradeDialogOpen(false);
  }, [selected?.symbol]);

  const autoCount = stocks.filter((item) => item.source.includes("auto")).length;
  const manualCount = stocks.filter((item) => item.source.includes("manual")).length;
  const paperStockCount = stocks.filter((item) => item.paper_trade_summaries.length).length;
  const selectedTrade = selected ? primaryPaperTrade(selected) : null;
  const selectedTradeReturn = selected
    ? tradeReturnPct(selectedTrade, selected.latest_close)
    : null;

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand-line">
          <BarChart3 size={24} />
          <div>
            <h1>股票研究工作台</h1>
            <p>股票负责筛选、模拟交易、完整买卖记录和复盘；板块负责强弱逻辑和情绪资金。</p>
          </div>
        </div>
        <nav className="page-nav">
          {pageItems.map((page) => (
            <button
              className={activePage === page.key ? "active" : ""}
              key={page.key}
              type="button"
              onClick={() => setActivePage(page.key)}
            >
              {page.label}
            </button>
          ))}
        </nav>
        <button className="refresh-button" type="button" onClick={loadWorkspace}>
          <RefreshCw size={16} />
          刷新
        </button>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      {activePage === "stocks" ? (
        <>
          <section className="summary-strip">
            <div>
              <span>系统筛选股票</span>
              <strong>{autoCount}</strong>
            </div>
            <div>
              <span>手动关注股票</span>
              <strong>{manualCount}</strong>
            </div>
            <div>
              <span>已有实盘模拟</span>
              <strong>{paperStockCount}</strong>
            </div>
            <div>
              <span>列表股票总数</span>
              <strong>{stocks.length}</strong>
            </div>
          </section>

          <section className="workspace-layout">
        <div className="stock-list-panel">
          <div className="list-toolbar">
            <div className="search-box">
              <Search size={16} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索股票、名称、行业"
              />
            </div>
            <div className="source-tabs">
              <button
                className={sourceFilter === "all" ? "active" : ""}
                type="button"
                onClick={() => setSourceFilter("all")}
              >
                全部
              </button>
              <button
                className={sourceFilter === "auto" ? "active" : ""}
                type="button"
                onClick={() => setSourceFilter("auto")}
              >
                系统筛选
              </button>
              <button
                className={sourceFilter === "manual" ? "active" : ""}
                type="button"
                onClick={() => setSourceFilter("manual")}
              >
                手动关注
              </button>
            </div>
          </div>

          <div className="manual-add-row">
            <input
              value={manualSymbol}
              onChange={(event) => setManualSymbol(event.target.value)}
              placeholder="股票代码"
            />
            <input
              value={manualNote}
              onChange={(event) => setManualNote(event.target.value)}
              placeholder="关注备注"
            />
            <button type="button" onClick={addManualFocus}>
              加入关注
            </button>
          </div>

          <div className="stock-table">
            <div className="stock-table-head">
              <span>股票</span>
              <span>来源</span>
              <span>近期表现</span>
              <span>实盘模拟</span>
            </div>
            {loading ? <div className="empty">加载中</div> : null}
            {!loading && !filteredStocks.length ? <div className="empty">暂无股票</div> : null}
            {filteredStocks.map((item) => (
              <button
                key={item.symbol}
                className={`stock-row ${selected?.symbol === item.symbol ? "selected" : ""}`}
                type="button"
                onClick={() => setSelectedSymbol(item.symbol)}
              >
                <span>
                  <strong>{item.symbol}</strong>
                  <small>{item.name ?? "未命名"} {item.industry ? ` / ${item.industry}` : ""}</small>
                </span>
                <span className={`source-pill ${item.source.includes("auto") ? "auto" : "manual"}`}>
                  {sourceLabels[item.source] ?? item.source}
                </span>
                <span>
                  <em className={(item.return_5d ?? 0) >= 0 ? "up" : "down"}>{pct(item.return_5d)}</em>
                  <small>20日 {pct(item.return_20d)}</small>
                </span>
                <span>
                  <strong>
                    {primaryPaperTrade(item)
                      ? `${tradeStatusText(primaryPaperTrade(item)?.status)} ${pct(
                          tradeReturnPct(primaryPaperTrade(item), item.latest_close),
                        )}`
                      : "-"}
                  </strong>
                  <small>
                    {primaryPaperTrade(item)
                      ? `胜率 ${pct(paperWinRate(item))} / 已平${paperClosedCount(item)}笔`
                      : "无模拟"}
                  </small>
                </span>
              </button>
            ))}
          </div>
        </div>

        <aside className="stock-detail-panel">
          {selected ? (
            <>
              <div className="stock-title">
                <div>
                  <span>{sourceLabels[selected.source] ?? selected.source}</span>
                  <h2>{selected.symbol} {selected.name ?? ""}</h2>
                  <p>{selected.industry ?? "暂无行业"} / {selected.sector_style ?? "暂无风格"}</p>
                </div>
                <div className="latest-price">
                  <span>最新收盘</span>
                  <strong>{price(selected.latest_close)}</strong>
                  <small>{selected.latest_trade_date ?? "-"}</small>
                </div>
              </div>

              <div className="return-cards">
                <div>
                  <span>5日表现</span>
                  <strong className={(selected.return_5d ?? 0) >= 0 ? "up" : "down"}>{pct(selected.return_5d)}</strong>
                </div>
                <div>
                  <span>20日表现</span>
                  <strong className={(selected.return_20d ?? 0) >= 0 ? "up" : "down"}>{pct(selected.return_20d)}</strong>
                </div>
              </div>

              <section className="detail-section">
                <div className="section-title with-action">
                  <div>
                    <ClipboardList size={16} />
                    <h3>实盘模拟交易</h3>
                  </div>
                  {selected.recent_paper_trades.length ? (
                    <button type="button" onClick={() => setTradeDialogOpen(true)}>
                      历史记录
                    </button>
                  ) : null}
                </div>
                {selectedTrade ? (
                  <div className="active-trade-card">
                    <div>
                      <span>{selectedTrade.status === "open" ? "当前持仓" : "最近一笔"}</span>
                      <strong>
                        {selectedTrade.rule_id} / {tradeStatusText(selectedTrade.status)} /{" "}
                        {pct(selectedTradeReturn)}
                      </strong>
                    </div>
                    <p>
                      买入 {selectedTrade.entry_date} @ {price(selectedTrade.entry_price)}，
                      卖出 {selectedTrade.exit_date ?? "未卖出"} @ {price(selectedTrade.exit_price)}
                    </p>
                    <p>
                      数量 {selectedTrade.quantity} / 持有 {selectedTrade.holding_days}天 /
                      最高 {price(selectedTrade.highest_price)} / 最低 {price(selectedTrade.lowest_price)} /
                      顶峰浮盈 {pct(selectedTrade.mfe_pct)} / 最大浮亏 {pct(selectedTrade.mae_pct)}
                    </p>
                    <p>
                      胜率 {pct(paperWinRate(selected))} / 已平 {paperClosedCount(selected)}笔 /
                      退出原因 {exitReasonText(selectedTrade.exit_reason)}
                    </p>
                  </div>
                ) : (
                  <div className="empty compact">暂无实盘模拟交易，需要先按交易日运行纸面实盘。</div>
                )}
              </section>

              <section className="detail-section">
                <div className="section-title">
                  <ClipboardList size={16} />
                  <h3>当前交易计划</h3>
                </div>
                {selected.plans.length ? (
                  selected.plans.map((plan) => (
                    <div className="plan-card" key={plan.id}>
                      <div>
                        <strong>{plan.rule_id} / {strategyLabels[plan.strategy_type] ?? plan.strategy_type}</strong>
                        <span>
                          计划交易日 {plan.trade_date} / {plan.execution_label} /
                          置信分 {price(plan.confidence_score)}
                        </span>
                      </div>
                      <p>{riskText(plan)}</p>
                      <p className={plan.can_buy_now ? "execution-note tradable" : "execution-note blocked"}>
                        {plan.execution_note}
                      </p>
                      {plan.evidence.length ? (
                        <div className="evidence-grid">
                          {plan.evidence.map((item) => (
                            <div className={`evidence-item ${item.verdict}`} key={`${item.category}-${item.label}`}>
                              <span>{item.category}</span>
                              <strong>{item.label}: {item.value}</strong>
                              <small>{item.note}</small>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <div className="empty compact">暂无当前交易计划。</div>
                )}
              </section>

              <section className="chart-panel in-detail">
                <div className="panel-head">
                  <div>
                    <span>策略证据图</span>
                    <h3>{selected.symbol} 日K与均线</h3>
                  </div>
                  <span>{candles.length} 根K线</span>
                </div>
                <StrategyEvidenceChart candles={candles} recommendation={null} />
              </section>

              <section className="detail-section">
                <div className="section-title">
                  <ClipboardList size={16} />
                  <h3>复盘总结</h3>
                </div>
                {selected.paper_trade_summaries.length ? (
                  <p className="manual-note">
                    当前展示的是按真实交易日推进的纸面实盘记录：每笔来自系统当日交易计划，
                    买入后每天用真实行情更新最高价、最低价、浮盈浮亏，并在触发止损、跟踪止盈或时间退出时平仓。
                    后续这里会接入机械规则总结和 AI 总结，解释哪些买点有效、哪些卖点拖累收益，
                    以及止损止盈是否应该按股票或板块单独调整。
                  </p>
                ) : (
                  <div className="empty compact">暂无可复盘交易，先为该股票跑模拟交易。</div>
                )}
              </section>
            </>
          ) : (
            <div className="empty">选择一只股票查看详情</div>
          )}
        </aside>
      </section>
        </>
      ) : null}

      {tradeDialogOpen && selected ? (
        <div className="modal-backdrop" role="presentation">
          <section className="trade-dialog" role="dialog" aria-modal="true" aria-label="实盘模拟交易明细">
            <div className="dialog-head">
              <div>
                <span>{selected.symbol} {selected.name ?? ""}</span>
                <h3>实盘模拟交易明细</h3>
              </div>
              <button type="button" onClick={() => setTradeDialogOpen(false)}>
                关闭
              </button>
            </div>
            <div className="trade-record-list">
              {selected.recent_paper_trades.map((trade) => (
                <div className="trade-record" key={trade.id}>
                  <div>
                    <strong>{trade.rule_id} / {tradeStatusText(trade.status)} / {pct(trade.pnl_pct)}</strong>
                    <span>
                      买入 {trade.entry_date} @ {price(trade.entry_price)}，
                      卖出 {trade.exit_date ?? "未卖出"} @ {price(trade.exit_price)}
                    </span>
                  </div>
                  <p>
                    数量 {trade.quantity} / 持有 {trade.holding_days}天 /
                    最高 {price(trade.highest_price)} / 最低 {price(trade.lowest_price)} /
                    顶峰浮盈 {pct(trade.mfe_pct)} / 最大浮亏 {pct(trade.mae_pct)} /
                    退出原因 {exitReasonText(trade.exit_reason)}
                  </p>
                </div>
              ))}
            </div>
          </section>
        </div>
      ) : null}

      {activePage === "sectors" ? (
        <section className="page-panel">
          <div className="panel-head">
            <div>
              <span>独立板块分析</span>
              <h3>板块强弱、政策新闻、情绪、技术和资金</h3>
            </div>
            <span>待接入真实板块数据</span>
          </div>
          <div className="sector-grid">
            <div className="sector-list">
              <div className="stock-table-head sector-head">
                <span>板块</span>
                <span>强度</span>
                <span>观察信号</span>
              </div>
              <div className="empty compact">
                下一步接入 akshare 板块行情、涨跌家数、成交额和领涨股。
              </div>
            </div>
            <div className="sector-detail">
              <section className="detail-section">
                <div className="section-title">
                  <ClipboardList size={16} />
                  <h3>政策 / 新闻</h3>
                </div>
                <div className="empty compact">记录催化事件、政策方向和新闻密度。</div>
              </section>
              <section className="detail-section">
                <div className="section-title">
                  <TrendingUp size={16} />
                  <h3>情绪 / 技术 / 资金</h3>
                </div>
                <div className="empty compact">
                  汇总板块涨跌家数、连板高度、均线结构、放量持续性和资金流向。
                </div>
              </section>
            </div>
          </div>
        </section>
      ) : null}

    </main>
  );
}
