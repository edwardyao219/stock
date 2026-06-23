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
