# 股票辅助交易系统交接文档 2026-07-22

本文件是当前开发状态的唯一交接入口。项目目录为 `/Users/yaotianshun/stock`，开发分支为 `codex/startup-signal-replay`。

## 系统定位与边界

- A 股辅助决策与纸面交易系统，不自动下单。
- 先看板块、市场环境与数据证据，再看个股；政策消息只能作为背景，不能直接形成买入结论。
- 收盘候选不等于可执行交易。必须区分观察、启动、确认、失效与计划可用性。
- 禁止未来函数、主观数据源、过度拟合；实时判断只能使用当时已落库快照。
- 不提交 `.stock-dev.sqlite`、`dump.rdb`，不输出任何 token、密码或钉钉 webhook。

## 运行环境

- API：`http://127.0.0.1:8000`，screen：`stock-api-funnel`。
- Web：`http://127.0.0.1:5173`，screen：`stock-web`。
- Celery worker 由系统守护，重启前先运行：
  ```bash
  .venv/bin/celery -A services.jobs.celery_app.celery_app inspect active --timeout=2
  ```
  仅在空闲时重启，禁止额外启动 screen worker。
- 数据库为 MySQL；当前不是 SQLite fallback。

## 已完成能力

### 数据证据与盘后恢复

- Tushare 的 `moneyflow`、`moneyflow_dc`、`cyq_perf`、`limit_list_d` 进入盘后证据门禁。
- 晚间补采成功且有新数据时，会静默重评估候选池、最终分层与交易计划；不会调用钉钉候选推送。
- 两个数据集均为 `skipped` 时不重复重评估。
- 历史日期可调用 `POST /jobs/after-close/candidate-recovery?trade_date=YYYY-MM-DD` 静默重放候选。
- 2026-07-21 已实际重放：写入 1 只、淘汰 3 只、生成 0 条计划；数据证据为 `ok`，没有重复钉钉。

### 候选与计划可用性

- 候选、工作台与钉钉均暴露 `plan_availability`：状态、原因、条件缺口。
- 最终分层会覆盖初筛计划状态，避免风险降级后仍显示可执行。
- 盘后状态含候选恢复的写入、淘汰、计划数及摘要。

### 淘汰可追溯

- 自动候选退休时写入 `retire_reason:本轮数据完整后未进入候选池` 与 `dropped:<feature_date>` 标签。
- 工作台 API 返回 `candidate_retire_reason`；候选详情可显示。
- `/jobs/after-close/status` 返回按查询交易日过滤的 `candidate_retire_reasons`，前端复盘区显示统计。

## 已完成：盘中启动确认闭环

- 生命周期统一为 `preheat / probing / confirmed / invalidated`，中文分别为启动预热、启动试探、启动确认、启动失效。
- 收盘候选只产生预热或试探。盘中确认要求 10:30 后板块持续扩散、个股量价承接、市场风险阀门允许、无硬风险且候选正式可用。
- `invalidated` 在同一交易日为终态；下一交易日可重新开始。
- 生命周期事件复用 `ResearchSignalLedger(source="startup_state")`，按交易日、股票、状态去重。10:30 定时任务先生成板块证据，再计算候选并持久化事件。
- 启动候选交易计划在确认前不能纸面开仓；失效只取消尚未执行的 `planned` 计划，不回滚已执行计划或已开持仓。
- 钉钉只发送本次新落库的确认与失效事件，预热、试探、重试、历史回放和恢复路径静默；通知在数据库提交后发送。
- 复盘按四态统计后续 1/3/5 个交易日收益、最大涨幅与最大回撤，并输出试探到确认、确认到失效转换率。没有 canonical 事件的旧日期仍读取 `starting / accelerating` snapshot。
- Workspace API 与 Web 直接使用 canonical state，展示状态时间、确认依据、失效原因、下一条件和计划可用性，不再从中文标签推断状态。
- Web 对旧 API payload 做空数组兼容。即使 API 与 Web 滚动升级不同步，也不会因缺少新 evidence 字段导致 React 空白页。
- `.stock-dev.sqlite` 与 `dump.rdb` 已加入 `.gitignore`，本地数据文件未删除、未提交。

## 当前 Git 状态

启动闭环提交：

- `7295352 test: update tracking workspace fixture`
- `dba0925 feat: display startup lifecycle`
- `ed66410 feat: report startup lifecycle outcomes`
- `2a6e7e9 feat: notify startup state changes`
- `a89bbda feat: gate startup paper plans`
- `53a81e2 feat: persist startup state events`
- `a025542 feat: unify startup candidate states`
- `e5261a2 feat: define startup state transitions`
- `af55bba docs: plan startup state loop`
- `4c808ed docs: define startup state loop`

此前已推送提交：

- `cd8cb31 feat: 汇总候选淘汰原因`
- `6a63f7f feat: 展示候选淘汰原因`
- `37bbe45 feat: 记录候选淘汰原因`
- `7b09680 feat: 展示候选恢复淘汰数量`
- `dbadaad feat: 支持静默重放历史候选`
- `e1bfc12 feat: 补采后静默重评估候选`

仍有两处本轮开始前就存在的未提交改动：

- `apps/api/app/routers/jobs.py`
- `services/engine/research_pool/repository.py`

它们用于按查询交易日过滤候选淘汰原因，本轮未重置也未纳入启动闭环提交。继续前先阅读 diff，不要 reset 或 checkout。

## 验证基线

2026-07-22 本轮验证：

- 启动闭环聚焦后端回归：`336 passed`。
- 完整后端回归：`781 passed`，0 failed。
- `tests/test_tracking_snapshots.py`：`7 passed`；修复此前 `candidate_retire_reason` 字段新增后 fixture 未同步的问题。
- 前端 lifecycle 契约测试通过；`npm run build` 通过。Vite 仅保留现有的单 chunk 超过 500 kB 提示。
- `git diff --check` 无输出。
- 应用内浏览器验证桌面 `1440x900`、移动 `390x844` 均无横向溢出；旧 API payload 下 React 页面不会崩溃。
- Celery 检查结果：1 个 worker 在线，active 为空。本轮没有重启 API、Web 或 worker。
- 最新真实数据检查：盘中市场日期 `2026-07-22`；特征、板块和资金日期 `2026-07-21`。

2026-07-23 运行态上线验证：

- 从 `main` 重启 API screen，当前 `stock-api-funnel` 会话 PID 为 `8924`，8000 仅由新的 Uvicorn PID `8942` 监听。
- `/jobs/after-close/status` 已返回 `candidate_retire_reasons`；`/workspace/startup-tracking` 可读，当前返回 0 条数据属正常样本不足状态。
- launchd worker 从 PID `17399` 重启为 PID `14319`；`inspect ping`、生命周期相关任务注册和 `inspect active` 均正常，active 为空。
- Celery beat 保持运行，未手工触发盘中/盘后任务，未发送测试通知；2026-07-22 的 `cyq_perf` 缺失数据门禁保持不变。

常用命令：

```bash
.venv/bin/pytest -q
cd apps/web && npm run build
.venv/bin/celery -A services.jobs.celery_app.celery_app inspect active --timeout=2
```

## 下一位开发者的执行顺序

1. 在 worker 空闲时按现有守护方式重启 API 和 Celery worker，使新 lifecycle 代码进入运行态；不要额外启动重复 worker。
2. 观察至少若干真实交易日的 09:35、10:30、14:50 事件，确认预热/试探不推送、确认/失效只推送一次、失效只取消未执行计划。
3. canonical lifecycle 从本次上线后才开始积累，当前转换率与分状态 1/3/5 日样本可能为空或很少。样本不足时只展示，不调阈值、不改策略因子。
4. 清理并单独提交上述淘汰原因日期过滤改动；每次历史补采或候选重放继续保持 `suppress_candidate_notification=True`。
