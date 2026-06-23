# 系统架构设计

## 1. 定位

这个系统是本地自动化股票研究平台，核心目标是每天自动跑数据、回测、回归、总结和生成交易计划。

它不是单纯技术指标工具，也不是 AI 自动下单系统。系统的职责边界是：

- 机械规则负责买入、卖出、止损、止盈、仓位、回测和验证
- 统计引擎负责发现什么规则在什么市场环境下有效
- AI 负责新闻公告抽取、板块逻辑总结、交易归因和提出候选假设
- 所有 AI 假设必须重新进入回测验证，不能直接进入实盘执行

## 2. 总体数据流

```text
数据源
  -> 数据采集
  -> 原始数据层
  -> 清洗数据层
  -> 特征层
  -> 规则策略引擎
  -> 回测与规则回归
  -> 机械总结
  -> AI 复盘和假设生成
  -> 候选规则库
  -> 人工审核
  -> 启用规则
```

每日交易计划流：

```text
收盘数据
  -> 个股/板块/情绪/财务/新闻特征
  -> 市场状态识别
  -> 策略规则筛选
  -> 明日候选股
  -> 买入条件、止损、止盈、仓位建议
```

## 3. 服务拆分

### apps/api

后端 API 服务，建议使用 FastAPI。

职责：

- 用户界面 API
- 策略配置 API
- 回测任务 API
- 候选股 API
- 交易计划 API
- 复盘报告 API
- 系统任务状态 API

### apps/web

前端工作台。

核心页面：

- 市场总览
- 板块强度
- 候选股
- 策略研究
- 回测报告
- 交易计划
- 机械总结
- AI 复盘
- 系统任务管理

### services/collector

数据采集服务。

第一阶段数据源：

- AKShare
- Tushare，可选

采集范围：

- A 股日线
- 指数日线
- 行业/概念板块
- 涨跌停数据
- 基础股票信息
- 财务摘要，可分阶段接入
- 公告/新闻，可分阶段接入

### services/engine

研究和回归引擎。

职责：

- 特征计算
- 市场状态识别
- 策略信号生成
- 事件驱动回测
- 规则组合实验
- Walk-forward 验证
- MFE/MAE 统计
- 规则表现评分

### services/jobs

定时任务入口。

职责：

- 开盘前检查
- 盘中监控，可选
- 收盘后数据同步
- 晚间回测和规则回归
- 每日机械总结
- 每周深度复盘

## 4. 数据库建议

第一阶段使用：

```text
PostgreSQL
Redis
```

后续数据量上来后扩展：

```text
TimescaleDB 或 ClickHouse
MinIO 存储 Parquet 和报告文件
pgvector 或 Qdrant 做新闻公告向量检索
```

## 5. 核心表设计草案

### securities

股票基础信息。

```text
id
symbol
name
exchange
list_date
industry
is_st
is_active
created_at
updated_at
```

### trading_calendar

交易日历。

```text
trade_date
is_open
previous_trade_date
next_trade_date
```

### daily_bars

日线行情。

```text
symbol
trade_date
open
high
low
close
pre_close
volume
amount
turnover_rate
limit_up
limit_down
is_suspended
```

唯一键：

```text
symbol + trade_date
```

### sector_daily

板块日表现。

```text
sector_code
sector_name
trade_date
open
high
low
close
pct_change
amount
up_count
down_count
limit_up_count
limit_down_count
new_high_count
relative_strength
```

### stock_features_daily

个股日特征。

```text
symbol
trade_date
trend_score
volume_score
position_score
volatility_score
relative_strength_score
risk_score
atr_14
return_1d
return_3d
return_5d
return_20d
distance_to_ma5
distance_to_ma20
distance_to_20d_high
amount_percentile_60d
turnover_percentile_60d
```

### sector_features_daily

板块特征。

```text
sector_code
trade_date
strength_score
money_score
emotion_score
news_score
fundamental_score
trend_stage
rank_1d
rank_3d
rank_5d
rank_20d
amount_ratio_20d
limit_up_count
leader_symbols
```

### market_regime_daily

市场状态。

```text
trade_date
regime
trend_score
breadth_score
emotion_score
volatility_score
risk_level
description
```

示例：

```text
strong_trend
weak_trend
range
panic
rebound
```

### strategy_rules

策略规则定义。

```text
id
name
strategy_type
version
status
entry_rule_json
exit_rule_json
stop_rule_json
take_profit_rule_json
position_rule_json
market_filter_json
created_by
created_at
updated_at
```

status：

```text
draft
testing
paper_enabled
live_candidate
disabled
```

### rule_experiments

规则实验批次。

```text
id
rule_id
experiment_name
train_start
train_end
test_start
test_end
parameters_json
status
created_at
finished_at
```

### backtest_trades

回测交易明细。

```text
id
experiment_id
rule_id
symbol
signal_date
entry_date
entry_price
exit_date
exit_price
holding_days
pnl
pnl_pct
mfe_pct
mae_pct
exit_reason
market_regime
sector_code
sector_strength_score
entry_snapshot_json
exit_snapshot_json
```

### rule_performance_daily

规则每日滚动表现。

```text
rule_id
trade_date
window_days
trade_count
win_rate
avg_return
expectancy
profit_factor
max_drawdown
avg_mfe
avg_mae
score
notes
```

### trade_plans

每日交易计划。

```text
id
plan_date
trade_date
symbol
rule_id
strategy_type
sector_code
entry_condition_json
entry_price_range_low
entry_price_range_high
initial_stop
take_profit_1
take_profit_2
max_holding_days
position_size
confidence_score
risk_notes
status
```

### news_events

新闻/公告/政策事件。

```text
id
event_date
source
title
url
raw_text_hash
symbols
sectors
event_type
impact_direction
impact_horizon
confidence
summary
structured_json
created_at
```

### review_reports

机械或 AI 复盘报告。

```text
id
report_date
report_type
scope
generator
content_md
metrics_json
created_at
```

report_type：

```text
daily_mechanical
daily_ai
weekly_ai
sector_review
rule_review
trade_review
```

### strategy_hypotheses

AI 或人工提出的策略假设。

```text
id
source
title
description
evidence_json
proposed_rule_json
status
created_at
reviewed_at
```

status：

```text
proposed
approved_for_backtest
rejected
backtested
promoted_to_rule
```

## 6. 规则表达

规则不要写死在代码里，第一版可以用 JSON 描述，再由 Python 解释执行。

示例：

```json
{
  "entry": {
    "all": [
      {"feature": "sector_strength_score", "op": ">=", "value": 75},
      {"feature": "relative_strength_score", "op": ">=", "value": 70},
      {"feature": "amount_percentile_60d", "op": ">=", "value": 80},
      {"feature": "distance_to_20d_high", "op": "<=", "value": 0.03}
    ]
  },
  "trigger": {
    "all": [
      {"field": "price", "op": ">", "ref": "previous_high"},
      {"field": "intraday_amount_ratio", "op": ">=", "value": 1.2}
    ]
  },
  "stop": {
    "type": "atr",
    "atr_multiple": 1.5
  },
  "take_profit": {
    "type": "trailing",
    "drawdown_from_high_pct": 0.06
  },
  "time_exit": {
    "max_holding_days": 5
  }
}
```

## 7. 回测原则

必须强制避免未来函数：

- T 日收盘后生成信号
- 最早 T+1 交易日买入
- 财报、公告、新闻按真实发布时间进入系统
- 涨跌停、停牌、流动性不足要影响成交模拟
- 加入手续费、印花税和滑点

核心统计：

- 胜率
- 平均收益
- 盈亏比
- 期望收益
- 最大回撤
- MFE
- MAE
- 平均持仓天数
- 连续亏损次数
- 按板块、市场状态、规则版本分组表现

## 8. 板块与叙事分析

板块层每天总结：

- 哪些板块强
- 强势来自技术、资金、情绪、新闻、财务中的哪一类
- 龙头是否持续
- 后排是否扩散
- 是否进入分化或退潮
- 适合追强、低吸、观察还是回避

机械输出事实：

```text
涨幅排名
成交额放大
涨停数量
上涨家数占比
相对指数强度
龙头股表现
```

AI 输出叙事：

```text
板块强势原因
证据链
交易含义
风险信号
失效条件
候选策略假设
```

## 9. AI 层边界

AI 可以做：

- 新闻摘要
- 公告解读
- 财报变化提取
- 板块逻辑总结
- 交易失败归因
- 规则假设生成
- 报告生成

AI 不应该做：

- 直接下单
- 绕过回测修改启用规则
- 单独决定仓位
- 在没有证据链时给交易结论

所有 AI 输出必须落库，带来源、证据和状态。

## 10. 本地部署建议

第一阶段本地机器：

```text
CPU: 8 核以上
内存: 32GB 起步，64GB 更好
硬盘: 1TB NVMe 起步
系统: macOS 或 Ubuntu
```

如果后续跑分钟级数据、大规模参数回归或本地大模型：

```text
CPU: 16 核以上
内存: 64GB-128GB
硬盘: 2TB-4TB NVMe
GPU: NVIDIA 24GB 显存以上，可选
```

第一版不依赖 GPU。
