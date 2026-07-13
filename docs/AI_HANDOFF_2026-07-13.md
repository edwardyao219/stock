# 股票辅助交易系统交接文档 2026-07-13

本文件用于在新会话中继续开发。以本文件为准，不要依赖旧会话的上下文。

## 1. 当前环境

- 实际项目目录：`/Users/yaotianshun/stock`
- 不要在 `/Users/yaotianshun/Documents/stock` 开发；该目录不是实际项目。
- Git 分支：`codex/startup-signal-replay`
- 本地最新提交：
  - `663e262 fix: localize cautious market status`
  - `e4591f9 feat: gate unconfirmed market rebounds`
- 分支相对 `origin/codex/startup-signal-replay`：领先 2 个提交。
- 推送未完成：仓库 Git 配置了本机代理 `127.0.0.1:7897`，当前不可用。不要删除或提交运行文件 `.stock-dev.sqlite`、`dump.rdb`。
- Python：`.venv/bin/python`
- 后端：FastAPI，`http://127.0.0.1:8000`，2026-07-13 15:06 健康检查正常。
- 前端：Vite React，`http://127.0.0.1:5173`，HTTP 200。
- 数据库：MySQL，配置在 `.env`。不要在文档、日志或提交中输出 token、密码、钉钉 webhook。

## 2. 用户目标与不可违反的边界

这是 A 股辅助决策和纸面实盘系统，不是展示型 dashboard，也不是自动实盘下单工具。

- 核心顺序：**先看板块，再看个股**。板块没有趋势、资金和扩散确认时，个股不能因为单项分数高就升级为行动。
- 主方向是 1 个月起步的中期趋势，不做银行、长江电力一类分红防守股逻辑；短线和做 T 只能作为持仓管理辅助。
- 候选并非越多越好。核心持仓通常不超过 3 只，但这是风险约束，不能被写死为无条件规则。
- 必须使用真实可得数据；盘中判断必须来自当时已落库的快照。
- **禁止未来函数**：信号日只能用信号日及之前的数据；回放的后续收益只能用于评估。
- **禁止过度拟合**：低维、可解释、跨月份和样本外稳定优先于高胜率或复杂模型。
- 不计算复利；总收益采用简单相加口径。最大回撤红线为 15%。
- 不能写死 `000001` 或某个行业。钉钉、前端候选必须来自当日真实策略筛选。
- 普通池排除 688；科创池单独管理。前端面向用户的标签均使用中文。

## 3. 策略与产品原则

### 3.1 低维核心

优先因子：板块趋势/扩散、个股趋势、相对强度、成交量确认、位置和过热风险。MACD、RSI、量比可以作为辅助，不能替代板块和趋势。

同事的有效观点已经被吸收为原则：主力趋势需要量能确认，但“上涨加放量”不等于买点，必须过滤高位放量、长上影、过度偏离均线和板块不共振。

### 3.2 多策略而非单策略押注

系统保留长期行动、启动前夜、启动确认、潜力观察等候选线做 PK。任何线只有在样本量、月份覆盖、总/平均收益和正收益月等门槛都合格时，才能升级为核心策略；否则只观察。

核心升级诊断在：`apps/api/app/routers/rules.py` 的 `diagnose_core_promotion_gate`。

### 3.3 市场状态门控

市场状态定义：`services/engine/features/market_regime.py`。

已有状态：`strong_trend`、`rebound`、`range`、`weak_trend`、`panic`、`unknown`。

本次新增：`rebound_unconfirmed`（反弹修复未确认）。

- 触发：市场整体趋势分 `<= 40`，但当日上涨广度 `>= 55%`。
- 含义：当天看上去普涨，底层趋势却仍弱，不能把修复日误判为新趋势。
- 候选效果：正式策略和潜力启动均禁止升级；只允许趋势、相对强度、板块、量能、风险和过热全部达标的高质量观察票。
- 仓位效果：情绪阀门为 `caution`、建议仓位比例 25%，通知分层核心仓位上限为 0。
- 这不是预测次日涨跌，而是避免在趋势未确认时追高扩仓。

实现位置：

- `services/engine/research_pool/candidates.py`：市场快照、情绪门控、候选上限、候选筛选、排序和诊断说明。
- `services/notifications/dispatcher.py`：核心行动阻断与提示。
- `apps/web/src/stockLabels.ts`：`caution` 显示为“谨慎观察”。

## 4. 已验证的长期回放

回放范围：2024-01-02 至 2026-07-10，最多 3 只持仓、20 日、非复利、最大回撤目标 15%。完整输出：`logs/long-replay-2024-2026-rank.txt`。

| 候选线 | 总收益 | 最大回撤 | 候选数 | 判断 |
|---|---:|---:|---:|---|
| `action_long` | 29.73% | -9.89% | 26 | 回撤合格，但样本太少且收益集中，不能升级 |
| `startup_preheat` | 17.30% | -13.73% | 386 | 回撤合格，但最新样本外为负，不能升级 |
| `startup_confirmed` | 32.10% | -17.06% | 120 | 回撤超标 |
| `potential_watch` | 19.89% | -18.07% | 455 | 回撤超标 |

结论：当前没有可无条件升级的核心策略。保留候选池、纸面实盘和板块跟踪，继续做滚动样本外验证，不能为追求 6 月收益而调参。

## 5. 最近真实市场复盘

### 2026-07-10（上周五）

全市场日线数据完整：5521/5540 只。

- 上涨 3772，下跌 1678，上涨占比 68.32%。
- 平均涨跌 +1.04%，成交额较前日 +16.32%。
- 但特征宇宙 5310 只的趋势均分仅 31.68，5 日背景收益偏弱。
- 强趋势样本 7.21%，上升信号样本仅 0.90%。
- 参与分 47.74，流动性分 35.95，弱结构占比 83.69%。

因此当日已经被新门控识别为 `rebound_unconfirmed`，正确动作应是观察，不追高扩仓。

### 2026-07-13（今天）

可读到的实时指数：上证约 -2.06%，深成约 -3.48%，创业板约 -3.10%。这说明周五的普涨没有演化为趋势确认。

今日全市场日线尚未落库，`/market/overview` 日线结果仍是 7 月 10 日；实时数据库只保存了 13 只候选跟踪股票，不能据此计算或展示“全市场下跌家数”。用户反馈市场约 4800 家下跌，系统需要补齐真实的全市场收盘快照后才能独立验证。

对 7 月 14 日的工作判断：基准情景是超跌后的弱修复或大幅震荡，不将技术反抽当反转。早盘只在以下条件同时出现时，才从观察升级：市场宽度修复、指数守住早盘低点、至少 2 至 3 个板块同步回流、成交承接存在。否则维持防守，不新开仓。

## 6. 数据链路现状和优先修复项

### 可用

- MySQL 已运行，历史日线、特征、板块、Tushare 数据和候选回放可用。
- Tushare/tinyshare 授权已配置在 `.env`，禁止打印或复制授权码。
- 盘中候选股实时跟踪可用。
- 北交所 `92` 开头股票已修正为 BJ/Sina `bjxxxxxx`，例如三元基因 `920344` 的实时涨幅可正确为负。

### 关键缺口

1. 全市场日内/收盘快照没有稳定归档到 5540 只覆盖，导致“今日涨跌家数、均值、成交额变化”会回退到上一交易日。
2. 实时 `RealtimeQuote.pct_change` 为空，且当前只覆盖候选跟踪股票。不要用这张表直接统计全市场广度。
3. `/market/overview` 能取到实时指数，但全市场实时源失败时会正确回退到最近日线。前端必须清楚标注“最近交易日”，不能伪装成今日数据。

下一步优先事项是修复全市场收盘归档和实时覆盖质量，再让次日开盘的市场宽度门控真正有可靠输入。先修数据，再增加策略因子。

## 7. 前后端重点位置

- 候选发现：`services/engine/research_pool/candidates.py`
- 市场状态：`services/engine/features/market_regime.py`
- 回放：`services/engine/backtest/walk_forward.py`
- 长回放报告：`services/engine/backtest/run_long_replay_baseline.py`
- 策略诊断 API：`apps/api/app/routers/rules.py`
- 市场概览 API：`apps/api/app/routers/market.py`
- 工作台与实时压力：`apps/api/app/routers/workspace.py`
- 通知/候选分层：`services/notifications/dispatcher.py`
- 纸面实盘：`services/engine/paper/realtime.py`
- 前端主界面：`apps/web/src/App.tsx`
- 前端中文标签：`apps/web/src/stockLabels.ts`

前端遵循：不要把所有内容挤在主页面；复盘使用抽屉或独立 tab；核心是股票、板块、纸面实盘和清楚的理由/风险理由。

## 8. 验证与运行命令

本次改动已验证：

```bash
.venv/bin/pytest tests/test_market_regime.py tests/test_next_session_candidates.py tests/test_notifications.py tests/test_jobs_pipeline.py tests/test_market_api.py tests/test_realtime_quotes.py tests/test_strategy_fit_api.py -q --disable-warnings
.venv/bin/ruff check services/engine/features/market_regime.py services/engine/research_pool/candidates.py services/notifications/dispatcher.py tests/test_market_regime.py tests/test_next_session_candidates.py
cd apps/web && node --experimental-strip-types src/stockLabels.test.ts
cd apps/web && npm run build
```

新增关键测试：

- `tests/test_market_regime.py`：`rebound_unconfirmed` 分类和只允许观察。
- `tests/test_next_session_candidates.py`：端到端确保强票在该状态下不能进入正式策略池。
- `apps/web/src/stockLabels.test.ts`：确保 `caution` 不在中文页面裸露。

## 9. 下一会话建议顺序

1. 检查并修复今日全市场快照/收盘数据同步，建立数据完整性指标和明确的降级展示。
2. 用修复后的真实 7 月 13 日收盘数据生成总复盘：指数、广度、成交、板块强弱、强弱股分化、候选表现，而不只复盘系统选股。
3. 将明早 9:30 至 10:30 的“弱修复确认”变为盘中快照门控：广度、指数低点、板块回流、成交承接四项。先回放验证，再启用。
4. 继续 2024-2026 的滚动样本外回放，按市场状态和板块风格评估策略线；只记录结果，不根据单月收益追参。
5. 盘后仍需运行真实候选发现和纸面实盘复盘；钉钉可推盘中和盘后真实候选，其他细节留在 Web。

每次完成一个优化后应：说明做了什么、跑了哪些回归、收益/回撤变化、是否存在过拟合或数据缺口；再给出下一步计划。
