# Development Notes

## 当前状态

项目已经具备：

- FastAPI 应用入口
- 配置加载
- PostgreSQL/Redis compose
- MySQL 兼容连接和 upsert
- Celery 应用占位
- 每日研究流水线占位
- 规则表达模型
- 三条 MVP 规则
- 机械复盘占位

## macOS 后台调度

使用 `infra/launchd/` 中的两个模板启动 Celery worker 和 beat。先将模板内的
`REPLACE_WITH_YOUR_USER` 替换为本机用户名，复制到 `~/Library/LaunchAgents/`，再执行：

```bash
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.stock-research.celery-worker.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.stock-research.celery-beat.plist
```

worker 默认 `--concurrency=2`，避免本机在盘中被大量 fork 进程抢占。状态确认：

beat 模板通过系统自带的 `caffeinate -s` 在接通交流电时阻止整机休眠，避免盘中
定时任务因 Mac 休眠漏跑；使用电池时仍遵循系统休眠设置。已错过的盘中任务不会
补执行，盘后状态会把缺失的 14:50 尾盘快照标记为调度断档。

```bash
redis-cli ping
.venv/bin/celery -A services.jobs.celery_app.celery_app inspect ping --timeout=3
```

## 下一步开发顺序

### 1. 数据库模型和迁移

已经先放入 SQLAlchemy ORM 草案。下一步引入 Alembic，把草案变成正式迁移：

- securities
- trading_calendar
- daily_bars
- sector_daily
- stock_features_daily
- sector_features_daily
- strategy_rules
- trade_plans
- review_reports

### 2. 数据采集

优先接入 AKShare：

- 股票列表，已接入
- 交易日历，已接入
- A 股日线，已接入指定股票同步
- 指数日线，已接入
- 板块数据
- 涨跌停数据

### 3. 特征计算

先实现日线特征：

- return_1d/3d/5d/20d，已实现
- MA5/MA10/MA20/MA60，已实现
- ATR14，已实现
- amount_percentile_60d，已实现
- relative_strength_score，已实现基础版本
- distance_to_20d_high，已实现
- sector_strength_score

### 4. 规则执行

把 `StrategyRule` 解释成候选股筛选：

```text
feature row + rule entry condition -> signal，已实现基础版本
signal + trigger model -> trade plan，已实现收盘后计划生成，盘中 trigger 待实现
```

### 5. 回测引擎

先做日线 T+1 回测：

```text
T 收盘生成信号，已实现
T+1 按开盘模拟买入，已实现；突破触发待实现
持仓期间检查止损、止盈、时间退出，已实现基础版本
记录 MFE/MAE，已实现
```

### 6. 前端

在做前端前，后端研究闭环已经具备：

- 数据采集入口
- 特征计算
- 交易计划生成
- 日线回测
- 回测结果持久化
- 机械复盘
- 模拟交易账户、订单、持仓、成交
- 动态风险参数 profile，可后续由前端编辑
- profile 支持 global/sector/style/strategy_type/priority 匹配
- 个性化交易参数：触发价、结构/ATR 止损、1R/2R 止盈、风险仓位、失效条件
- 基本面快照和框架化评分，作为长持有逻辑的背景证据，不直接作为买卖信号

先做四个页面：

- 规则列表
- 市场总览
- 候选股
- 每日复盘
