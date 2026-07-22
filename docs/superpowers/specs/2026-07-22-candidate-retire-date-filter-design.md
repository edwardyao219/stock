# 候选淘汰原因按交易日过滤设计

## 背景

`/jobs/after-close/status` 支持查询指定交易日，但当前候选淘汰原因汇总会读取全部历史退休候选，导致历史原因串入所查询日期。候选退休流程已经写入 `dropped:<feature_date>` 标签，可直接作为过滤依据。

## 目标

- 查询某个交易日的收盘状态时，只统计带有对应 `dropped:<trade_date>` 标签的退休候选。
- 保留 `retired_reason_summary(items)` 汇总全部历史退休原因的既有行为。
- 不改变候选淘汰规则、标签格式、响应结构或前端展示。

## 方案

给 `retired_reason_summary` 增加可选的 `dropped_date` 参数。传入日期时，在解析 `retire_reason:` 前跳过不含对应 `dropped:` 标签的条目；未传日期时保持现有汇总行为。

`get_after_close_status` 使用已经确定的 `target_date` 调用该函数。继续在 Python 中过滤，避免引入数据库 JSON 方言差异，也不新增查询或数据模型。

## 数据流

1. API 根据请求参数或本地日期得到 `target_date`。
2. API 读取研究池条目并调用 `retired_reason_summary(items, target_date)`。
3. 汇总函数仅累计状态为 `retired`、包含 `dropped:<target_date>` 且含有 `retire_reason:` 的条目。
4. 结果继续写入现有 `candidate_retire_reasons` 响应字段。

## 兼容与异常

- `db` 不可用时仍返回空字典。
- 无匹配条目时返回空字典。
- 无 `retire_reason:`、非退休状态或日期不匹配的条目不计数。
- 不校验可选日期参数的格式；API 已负责解析查询日期，汇总函数只做精确标签匹配。

## 测试

- 仓储层单元测试覆盖目标日期、其他日期、非退休条目、缺少原因和不传日期的兼容行为。
- API 测试覆盖查询指定日期时只返回该日淘汰原因。
- 运行相关测试、完整后端回归和 `git diff --check`。
