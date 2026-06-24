# Stock Research System

一个本地运行的 A 股研究、回测、规则回归和复盘系统。

目标不是让 AI 直接炒股，而是让系统每天自动完成：

- 拉取行情、板块、情绪、新闻、公告、财务数据
- 计算个股与板块特征
- 生成候选股和交易计划
- 对买入、卖出、止损、止盈规则做滚动回测
- 机械总结规则表现
- 可选接入 AI，做新闻/公告抽取、板块逻辑总结、交易归因和策略假设生成

## Project Layout

```text
apps/
  api/        FastAPI 后端服务
  web/        前端工作台
services/
  collector/  数据采集服务
  engine/     特征、回测、规则回归引擎
  jobs/       定时任务入口
docs/
  architecture.md
  mvp.md
infra/
  docker-compose.yml
```

## First Milestone

第一阶段先做本地研究闭环：

```text
日线/板块数据 -> 特征计算 -> 规则回测 -> 机械总结 -> 明日交易计划
```

实盘自动下单不在第一阶段范围内。

## Local Development

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
docker compose -f infra/docker-compose.yml up -d postgres redis
uvicorn apps.api.app.main:app --reload
```

如果使用本地 MySQL，先在 Navicat 里创建数据库：

```sql
CREATE DATABASE stock_research CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

然后把 `.env` 里的 `DATABASE_URL` 改成你的本地账号密码：

```text
DATABASE_URL=mysql+pymysql://root:你的密码@127.0.0.1:3306/stock_research?charset=utf8mb4
```

本地按交易节奏运行流水线：

```bash
# 收盘后准备下一交易日候选，默认会应用纸面复盘学习参数
python -m services.jobs.run_pipeline --stage prepare --trade-date 2026-06-24 --next-trade-date 2026-06-25

# 盘中单次实时纸面监控，非交易时段会自动跳过；测试时可加 --force
python -m services.jobs.run_pipeline --stage intraday --trade-date 2026-06-25

# 收盘后生成纸面交易复盘、学习建议和规则回归
python -m services.jobs.run_pipeline --stage after-close --trade-date 2026-06-25 --next-trade-date 2026-06-26
```

创建当前 ORM 草案对应的数据表：

```bash
python -m services.shared.create_tables
python -m services.shared.sync_schema
```

同步基础数据：

```bash
python -m services.collector.run_sync bootstrap
python -m services.collector.run_sync indexes --start-date 20240101
python -m services.collector.run_sync stocks 000001 600519 --start-date 20240101
```

维护行业/板块映射：

```bash
python -m services.engine.sector.run_seed
python -m services.collector.run_industry_mapping 000001=银行 600519=白酒
```

计算日线特征：

```bash
python -m services.engine.features.run_compute --symbols 000001 600519
python -m services.engine.features.run_compute --limit 200
```

生成交易计划：

```bash
python -m services.engine.plans.run_generate --plan-date 2026-06-23 --trade-date 2026-06-24
```

运行第一版日线回测：

```bash
python -m services.engine.backtest.run_backtest --symbols 000001 600519 --rules R001
python -m services.engine.backtest.run_backtest --limit 200 --persist --run-date 2026-06-23
```

导入基本面快照 CSV：

```bash
python -m services.engine.fundamental.run_import data/fundamentals.csv
```

CSV 字段示例：

```text
symbol,report_date,revenue_growth,profit_growth,roe,dividend_yield,pe_ttm,pb,gross_margin,net_margin,debt_ratio
000001,2026-03-31,0.03,0.02,0.11,0.055,5.2,0.58,,, 
```

生成机械复盘：

```bash
python -m services.engine.review.run_review --report-date 2026-06-23
```

运行每日模拟交易：

```bash
python -m services.engine.paper.run_simulation --trade-date 2026-06-24
```

动态参数目前由 `risk_profiles` 表驱动。默认 profile 包括：

- 单笔风险比例
- 最大/最小仓位
- ATR 止损倍数
- 结构止损缓冲
- 最大/最小止损幅度
- 1R/2R 止盈倍数
- 移动止盈回撤
- 高开取消阈值
- 突破触发缓冲

`risk_profiles` 支持按范围匹配：

- `global`: 全局默认参数
- `sector`: 板块/行业参数，例如银行偏复利、长持有、宽止损
- `style`: 交易风格参数，例如题材短线
- `strategy_type`: 限定短线、波段或长线策略
- `priority`: 多个 profile 命中时优先级高者生效

查看 API：

```text
GET http://127.0.0.1:8000/health
GET http://127.0.0.1:8000/rules
GET http://127.0.0.1:8000/market/overview
GET http://127.0.0.1:8000/trade-plans/latest
```
