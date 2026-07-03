# 股票辅助交易系统交接文档 2026-06-24

这份文档是给下一个接手的 AI/开发者看的。目标不是讲概念，而是快速接上当前系统、理解用户真实诉求、知道已经做到哪里、下一步该怎么推进。

## 1. 项目基本信息

- 项目真实路径：`/Users/yaotianshun/stock`
- 注意：`/Users/yaotianshun/Documents/stock` 只是一个空 git 壳，不要在里面开发。
- Git 分支：`main`
- Git 远程：`https://github.com/edwardyao219/stock.git`
- Git 代理：仅本仓库配置了 `127.0.0.1:7897`
- Python 虚拟环境：`.venv/bin/python`
- 后端：FastAPI，通常运行在 `127.0.0.1:8000`
- 前端：Vite React，路径 `apps/web`，通常运行在 `http://localhost:5173`
- 数据库：本地 MySQL
  - host：`127.0.0.1`
  - port：`3306`
  - database：`stock_research`
  - username：`root`
  - password：`yyy123`
- 当前日期：`2026-06-24`
- 当前时区：`Asia/Shanghai`

## 2. 用户真实目标

用户不是要一个展示型 dashboard，也不是单股分析玩具。目标是做一个真正能提高 A 股交易胜率的辅助系统：

- 每天自动拉真实数据。
- 每天自动生成候选股票和交易计划。
- 盘中按真实交易时间模拟买入、卖出、止盈、止损。
- 每一笔纸面交易都要像真实交易一样记录：
  - 买入时间
  - 买入价格
  - 数量
  - 当前持仓状态
  - 卖出时间
  - 卖出价格
  - 收益
  - 最高浮盈 / 顶峰价格
  - 最大不利波动
  - 退出原因
- 回归历史数据是为了优化策略，不是伪造收益。
- 当前持仓没有卖出时，收益为空或浮动收益，不能伪造成完整交易收益。
- 最终希望系统能辅助实盘：
  - 提示当日是否可以买入
  - 或提示次日开盘是否应该买入
  - 给出支撑理由和风险理由
- 系统要不断学习：
  - 机械性规则总结
  - AI 总结
  - 纸面实盘复盘
  - 历史回归结果
  - 人工手动止盈/止损记录

用户强调很多次：这不是玩具，要结合实际市场，尤其要避免 A 股常见的“早盘疯狂放量诱多，高位站岗”。

## 3. 用户偏好的产品形态

前端不要全部挤在一个页面。用户认可的主结构是：

- 一级菜单只保留两个核心入口：
  - 股票
  - 板块
- 股票页里包含：
  - 自动筛选出来的纸面实盘股票
  - 手动添加的股票
  - 当前持仓或最近一笔交易
  - 胜率
  - 当天涨幅
  - 近期表现
  - 交易计划
  - 点击进入详情或弹窗看历史交易
- 板块页里包含：
  - 板块强弱
  - 政策
  - 情绪
  - 技术面
  - 资金面
  - 板块内个股表现

用户不喜欢：

- 太多英文
- 菜单太多
- 交易明细堆在页面底部
- 所有功能压在一个页面
- 只做单股详情分析
- 让用户审批策略建议

## 4. 当前系统能力概览

### 4.1 数据

目前主要通过 AKShare 拉取真实 A 股数据，已经做过真实数据同步和回归。

已接入的数据方向：

- 日线行情
- 实时行情快照
- 板块数据
- 财务数据
- 估值数据

财务相关模块：

- `services/engine/fundamental/akshare_client.py`
- `services/engine/fundamental/repository.py`
- `services/engine/fundamental/scoring.py`
- `services/engine/fundamental/sync.py`

已对实验股票同步过真实财务数据：

- `002837` 英维克
- `603083` 剑桥科技
- `600183` 生益科技

最近一次已知财务评分：

- `002837` 英维克：
  - 营收增长约 `+26%`
  - 利润增长约 `-82%`
  - ROE 约 `0.25%`
  - PE 约 `215`
  - PB 约 `30`
  - 结论：`weak`
  - 基本面分约 `29`
- `600183` 生益科技：
  - 营收增长约 `+45%`
  - 利润增长约 `+105%`
  - ROE 约 `6.68%`
  - PE 约 `103`
  - PB 约 `22.7`
  - 结论：`neutral`
  - 基本面分约 `66`
- `603083` 剑桥科技：
  - 营收增长约 `+44%`
  - 利润增长约 `+276%`
  - ROE 约 `1.58%`
  - PE 约 `250`
  - PB 约 `11.6`
  - 结论：`neutral`
  - 基本面分约 `58`

### 4.2 当前策略

核心策略定义文件：

- `services/engine/rules/seed_rules.py`

已有策略：

- `R001 强势板块放量突破`
  - 早期突破策略
  - 回归表现偏弱
  - 目前不应作为核心
- `R002 强势板块缩量回踩`
  - 当前比较重要
  - 在实验股票上表现较好
- `R005 缩量蓄势突破确认`
  - 用来避免追当天疯狂放量
  - 胜率相对高
- `R006 高强度趋势延续`
  - 适合液冷、通信、PCB 等强题材趋势段
  - 期望较好，但胜率不高
- `R004 稳定复利趋势`
  - 给银行等低波动复利资产使用
  - 不应该套用题材股参数
- `R007 趋势量能确认`
  - 今天新增
  - 目的是把用户同事说的“上升趋势 + 量能综合判断”做成可回归的基准策略
  - 不把它当万能策略，而是当 benchmark
  - 如果复杂策略跑不赢 R007，就要怀疑复杂策略是否只是噪音

### 4.3 今天新增的 R007 思路

用户提到同事系统主要看上升趋势和量能。我的判断是：需要，但不能直接“上涨 + 放量 = 买入”。A 股里这很容易变成高位接盘。

所以 R007 的原则是：

- 要趋势结构完整：
  - 均线多头排列
  - MA20 / MA60 斜率为正
  - 价格不能离 MA20 太远
- 要量能确认，但不能过热：
  - 温和放量
  - 不是极端放量
  - 收盘位置不能太差
  - 上影线不能太重
- 要过滤高位诱多：
  - 20 日涨幅不能过大
  - 距离 MA20 不能过远
  - `volume_trap_risk_score` 不能高
  - `overheat_score` 不能高
- 要结合基本面：
  - `fundamental_verdict != weak`

新增日线特征在：

- `services/engine/features/daily.py`

新增特征包括：

- `ma20_slope_20d`
- `ma60_slope_20d`
- `ma_alignment_score`
- `trend_quality_score`
- `volume_confirmation_score`
- `overheat_score`

交易参数接入在：

- `services/engine/risk/trade_parameters.py`

R007 入场参考价：

- `min(max(close, ma10), signal_day_high)`

这样不是单纯追突破高点，而是保守地做趋势确认。

### 4.4 真实回归结果

用三只实验股票：

- `002837` 英维克
- `603083` 剑桥科技
- `600183` 生益科技

区间：

- `2024-01-01` 到 `2026-06-24`

最近一次回归结果：

| 策略 | 交易数 | 胜率 | 平均收益 | 盈亏因子 | 结论 |
|---|---:|---:|---:|---:|---|
| R001 | 62 | 48.39% | -1.61% | 0.51 | 不适合作核心 |
| R002 | 36 | 52.78% | +2.20% | 2.27 | 当前重点 |
| R005 | 20 | 65.00% | +1.12% | 1.51 | 胜率好，继续观察 |
| R006 | 42 | 47.62% | +2.19% | 1.70 | 期望好但波动大 |
| R007 | 26 | 46.15% | +0.29% | 1.07 | 只能当基准，不是核心 |

R007 分股票拆解：

| 股票 | 样本数 | 胜率 | 平均收益 | 结论 |
|---|---:|---:|---:|---|
| 002837 英维克 | 10 | 40.00% | -1.16% | 不适合直接套用 |
| 600183 生益科技 | 11 | 72.73% | +4.92% | 对 PCB/成长周期可能适配 |
| 603083 剑桥科技 | 5 | 0.00% | -6.97% | 明显不适配 |

重要结论：

- “上升趋势 + 量能”需要，但只能做基准策略。
- 它对 `600183` 这种 PCB / 成长周期可能有效。
- 它对液冷、通信强题材不能无脑套。
- 后续必须按板块、题材、股票分别学习参数。

## 5. 纸面实盘和实时监控

当前已经有纸面实盘监控逻辑：

- `services/engine/paper/realtime.py`

已有关键设计：

- 计划价触发不等于立即买入。
- 加了盘中买入质量门禁：
  - 当天涨幅太热，拦截
  - 突破后回落，拦截
  - 收盘/当前价位置弱，拦截
  - 接近涨停但没封住，拦截
  - 高开回落跌破开盘，拦截
- 被拦截的计划会产生 `paper_entry_deferred` 预警。
- 盘中监控任务之前通过 `launchctl` 跑过：
  - label：`com.yaotianshun.stock.realtime-monitor`
  - 参数大致是：
    - `--trade-date 2026-06-24`
    - `--interval-seconds 30`
    - `--ticks 480`
    - `--execute-exits`

曾经看到的纸面持仓示例：

- `603083`
- entry：约 `259.23`
- qty：`100`
- 当时最新价：约 `262.21`
- 浮盈约：`+1.15%`
- stop：约 `232.1094`
- TP1：约 `267.0506`
- 多次出现 `limit_up_touched` 预警

用户特别强调：

- 如果有一笔 `000001` 纸面持仓是 `2026-06-23` 买入，价格 `10.65`，数量 `9300`，当前还没卖出，那么收益应该为空或显示持仓中，不能伪造成完整收益。

## 6. 前端当前状态

前端路径：

- `apps/web`

已经做过：

- 自动刷新，默认 15 秒轮询
- 顶部显示最后刷新时间
- 列表显示：
  - 当前价
  - 当天涨幅
  - 5 日 / 20 日表现
  - 计划 / 交易状态
  - 触发价 / 止损 / 止盈
  - 胜率
- 纸面持仓卡片显示：
  - entry
  - current/sell
  - today change
  - stop
  - peak
  - high/low
  - win rate

但用户对前端仍然不完全满意：

- 当前布局还不够直观。
- 交易明细不应放在下面，应点开弹窗。
- 股票页和板块页应该拆开。
- 当前重要信息提炼还不够。
- 后续要有控制面板，而不是都靠命令行。

不过用户后面明确说：前端暂时不用改，盈利能力主要看后端回归算法。

## 7. 今天未完成但已经动到的代码

当前工作区有未提交改动。

主要改动文件：

- `services/engine/features/daily.py`
- `services/engine/rules/seed_rules.py`
- `services/engine/risk/trade_parameters.py`
- `services/engine/plans/learning_adjustments.py`
- `services/engine/plans/sync.py`
- `services/jobs/pipeline.py`
- `services/engine/backtest/learning.py`
- `tests/test_daily_features.py`
- `tests/test_trade_plan_generator.py`
- `tests/test_backtest_learning.py`
- `tests/test_plan_learning_adjustments.py`
- `tests/test_jobs_pipeline.py`

已经跑过并通过：

```bash
.venv/bin/python -m pytest -q
```

最后一次全量测试结果：

- `76 passed`

已经跑过并通过相关 lint：

```bash
.venv/bin/python -m ruff check services/engine/backtest/learning.py services/engine/plans/learning_adjustments.py services/engine/plans/sync.py services/jobs/pipeline.py tests/test_backtest_learning.py tests/test_plan_learning_adjustments.py tests/test_jobs_pipeline.py
```

## 8. 当前重要问题：回归学习落库有重复数据冲突

今天新增了：

- `services/engine/backtest/learning.py`

目的：

- 从历史回归交易里学习策略在不同板块、不同股票上的适配性。
- 自动生成 `ParameterRecommendation`。
- 让后续计划生成读取这些学习建议，对不适配组合降权或要求额外确认。

已接入：

- `services/engine/plans/learning_adjustments.py`
  - 学习来源从只读 `paper_learning_review`
  - 扩展为读取：
    - `paper_learning_review`
    - `backtest_learning_review`
- `services/engine/plans/sync.py`
  - 加了 `symbol=context.get("symbol")`
- `services/jobs/pipeline.py`
  - 收盘流程里加了 `generate_backtest_learning_review`

但是最后真实落库时遇到错误：

```text
sqlalchemy.exc.MultipleResultsFound:
Multiple rows were found when one or none was required
```

触发命令：

```bash
.venv/bin/python - <<'PY'
from services.engine.backtest.learning import generate_backtest_learning_report
print({'changed': generate_backtest_learning_report('2026-06-24')})
PY
```

原因判断：

- `upsert_parameter_recommendations` 在 `services/engine/review/repository.py` 里用 `scalar_one_or_none()` 查唯一建议。
- 但本地数据库里已经有旧版 `backtest_learning_review` 建议数据。
- 今天我先生成过一次 38 条旧结构建议，后面又把 scope 从 `signal` 伪装改成了真正的 `symbol` / `sector`。
- 数据库里可能已经存在同一天、同 scope、同 target/action 的多条历史建议。
- 另外 `source_report_type` 没有包含在去重查询条件里，也可能导致纸面学习和回归学习在同 target/action 下互相撞。

建议下一步先修这个，不要继续堆功能。

推荐修法：

1. 在 `upsert_parameter_recommendations` 的查询条件中加入：
   - `ParameterRecommendation.source_report_type == source_report_type`
2. 对已有重复数据做一次清理，至少清理 `2026-06-24` 的 `backtest_learning_review`：

```sql
DELETE FROM parameter_recommendations
WHERE report_date = '2026-06-24'
  AND source_report_type = 'backtest_learning_review';
```

3. 重新生成：

```bash
.venv/bin/python - <<'PY'
from services.engine.backtest.learning import generate_backtest_learning_report
print({'changed': generate_backtest_learning_report('2026-06-24')})
PY
```

4. 再跑：

```bash
.venv/bin/python -m pytest -q
```

## 9. 后续优先级建议

### P0：先把回归学习落库修好

原因：

- 这是系统“会学习”的关键。
- 如果学习建议会串策略或重复落库，后续买入计划会被污染。

要保证：

- R007 在通信设备上的弱表现，只影响 R007，不影响 R002/R006。
- 个股级建议能按 `symbol` 命中。
- 板块级建议能按 `sector` 命中。
- 回归学习建议和纸面实盘学习建议可以共存，不互相覆盖。

### P1：把 R007 保留为 benchmark，而不是核心策略

R007 当前结论：

- 不适合作核心买入策略。
- 可以作为“趋势量能基准尺子”。
- 对 PCB/成长周期可能有价值。
- 对液冷/通信强题材目前不适配。

下一步应该：

- 给策略表现加按板块统计。
- 给前端展示：
  - 策略整体胜率
  - 策略在当前板块胜率
  - 策略在当前股票胜率
  - 为什么降权

### P2：继续强化 R002 / R005 / R006

目前更值得深挖：

- R002：强势板块缩量回踩
- R005：缩量蓄势突破确认
- R006：高强度趋势延续

要重点分析：

- 什么板块适合 R002
- 什么板块适合 R006
- R005 的高胜率是否来自样本少
- 每个策略失败时共同特征是什么：
  - 高位爆量
  - 上影线
  - 基本面弱
  - 开盘冲高回落
  - 板块退潮
  - 龙头断板

### P3：盘中真实模拟要更细

用户希望“明天/下午开盘后能自动选票模拟买入”。

当前已经有实时监控，但后续要增强：

- 每 30 秒或更短周期拉快照。
- 有信号时立即判断，而不是收盘后才知道。
- 盘中信号要写入数据库：
  - 买入触发
  - 被拦截原因
  - 延迟买入原因
  - 涨停触及
  - 跌停风险
  - 高开回落
  - 放量诱多
- 前端要能看到：
  - 当前是否有计划
  - 是否触发
  - 为什么没有买
  - 当前持仓浮盈
  - 当前止损/止盈线

### P4：前端控制面板

用户希望不要全靠命令。

后续做一个控制面板：

- 同步行情
- 生成计划
- 运行回归
- 生成复盘
- 运行盘中监控
- 查看任务状态
- 查看错误日志
- 调整动态参数

参数要能后期前端手动调整：

- 策略启停
- 板块参数
- 止损倍数
- 止盈倍数
- 最大高开限制
- 最大仓位
- 放量阈值
- 过热阈值
- 基本面过滤

### P5：手动止损/止盈学习

用户提过一个重要点：

- 模拟交易里要允许手动止损或止盈。
- 数据库记录下来。
- 后续系统学习人工判断。

这非常重要，因为人工止损/止盈往往包含：

- 盘感
- 新闻突发
- 板块退潮
- 龙头断板
- 情绪崩溃
- 利好兑现

建议设计：

- 新增人工操作记录表：
  - trade_id
  - action：manual_stop / manual_take_profit / manual_reduce / manual_add / manual_cancel
  - price
  - reason
  - confidence
  - created_at
- 复盘时对比：
  - 人工卖出后，后续 1/3/5 日走势
  - 人工是否提前规避回撤
  - 人工是否卖飞

## 10. 常用命令

### 跑测试

```bash
cd /Users/yaotianshun/stock
.venv/bin/python -m pytest -q
```

### 跑指定测试

```bash
.venv/bin/python -m pytest tests/test_daily_features.py tests/test_trade_plan_generator.py -q
.venv/bin/python -m pytest tests/test_backtest_learning.py tests/test_plan_learning_adjustments.py -q
```

### 计算股票特征

```bash
.venv/bin/python -m services.engine.features.run_compute --symbols 002837 603083 600183
```

### 计算板块特征

```bash
.venv/bin/python - <<'PY'
from services.engine.features.sync import compute_and_store_sector_features
print(compute_and_store_sector_features())
PY
```

### 跑策略回归

```bash
.venv/bin/python -m services.engine.backtest.run_backtest \
  --symbols 002837 603083 600183 \
  --rules R001 R002 R005 R006 R007 \
  --start-date 2024-01-01 \
  --end-date 2026-06-24 \
  --run-date 2026-06-24 \
  --persist
```

### 生成回归学习报告

当前这步有重复数据问题，先按第 8 节修复。

```bash
.venv/bin/python - <<'PY'
from services.engine.backtest.learning import generate_backtest_learning_report
print({'changed': generate_backtest_learning_report('2026-06-24')})
PY
```

### 前端

```bash
cd /Users/yaotianshun/stock/apps/web
npm run build
```

## 11. 给下一个 AI 的工作建议

请不要一上来重构整个系统。先按这个顺序做：

1. 读当前 git diff。
2. 修复 `upsert_parameter_recommendations` 的重复查询问题。
3. 清理 `2026-06-24 backtest_learning_review` 旧数据。
4. 重新生成回归学习报告。
5. 跑全量测试。
6. 确认计划生成时：
   - `source_rule_id=R007` 的建议只影响 R007。
   - `symbol=603083` 的 R007 降权能命中剑桥科技。
   - `sector=通信设备` 的 R007 降权不会影响 R006。
7. 再继续优化策略，不要先做前端美化。

当前最重要的方向：

- 少做展示，多做学习。
- 少凭感觉，多记录每一笔真实纸面交易。
- 少写万能策略，多做板块/题材/股票差异化参数。
- 每个买入计划都要回答：
  - 为什么买？
  - 为什么现在买？
  - 哪些条件会取消买入？
  - 止损在哪里？
  - 止盈怎么走？
  - 这个策略在当前股票/板块历史上表现如何？

## 12. 用户风格和沟通注意

用户希望你：

- 用中文。
- 直接、务实。
- 可以加入自己的交易和工程判断。
- 不要只机械执行。
- 不要做无用功。
- 不要把页面做得花但系统没学习能力。
- 要承认策略不可靠的地方。
- 不要把纸面模拟包装成实盘保证。

用户最在意的是：

- 真实数据
- 真实模拟交易
- 买入逻辑
- 卖出逻辑
- 止损止盈
- 回归学习
- 板块差异
- 规避诱多和高位接盘

## 13. 可以直接发给下一个 AI 的提示词

下面这段可以直接复制给下一个 AI：

```text
你现在接手一个本地 A 股辅助交易系统，项目路径是 /Users/yaotianshun/stock。

先阅读 /Users/yaotianshun/stock/docs/AI_HANDOFF_2026-06-24.md，不要从零设计。

当前目标不是做漂亮页面，而是把真实数据、纸面实盘、策略回归、回归学习、板块差异化参数打牢。用户要的是能提高胜率的辅助系统，不是玩具 dashboard。

请先处理当前未完成事项：
1. 查看 git diff。
2. 修复 services/engine/review/repository.py 里 upsert_parameter_recommendations 的重复查询问题，建议把 source_report_type 加入查重条件。
3. 清理本地 MySQL 里 2026-06-24 的 backtest_learning_review 旧数据。
4. 重新运行 generate_backtest_learning_report('2026-06-24')。
5. 跑 .venv/bin/python -m pytest -q。
6. 确认 R007 的回归学习建议只影响 R007，不串到 R002/R006。

注意：/Users/yaotianshun/Documents/stock 是空 git 壳，不要在那里开发。
数据库是本地 MySQL：root / yyy123 / 127.0.0.1:3306 / stock_research。
```

## 14. 当前 git 状态摘要

写本文档时，工作区还有未提交改动。大致是：

```text
M services/engine/features/daily.py
M services/engine/plans/learning_adjustments.py
M services/engine/plans/sync.py
M services/engine/risk/trade_parameters.py
M services/engine/rules/seed_rules.py
M services/jobs/pipeline.py
M tests/test_daily_features.py
M tests/test_jobs_pipeline.py
M tests/test_plan_learning_adjustments.py
M tests/test_trade_plan_generator.py
?? services/engine/backtest/learning.py
?? tests/test_backtest_learning.py
?? docs/AI_HANDOFF_2026-06-24.md
```

这些改动不是完全没验证：单元测试和 lint 已经过。但是回归学习真实落库时还有第 8 节说的重复数据问题，所以建议先不要急着提交，等修完重复数据问题后再统一提交。

## 15. 当前最值得保留的工程判断

这几个判断是今天推进后比较重要的结论：

1. R007 需要保留，但定位是 benchmark，不是核心策略。
2. R002 / R005 / R006 比 R007 更值得继续挖。
3. R007 对 `600183` 这种 PCB/成长周期样本表现好，但对 `002837`、`603083` 不好，说明策略必须按板块/题材分层。
4. 财务数据已经接入，不能再说系统完全没有基本面，但目前财务只是评分，还没有变成足够强的交易过滤器。
5. 实时交易层已经开始避免“触价就买”，这是正确方向，后续要继续加强盘中诱多识别。
6. 学习层要分两条线：
   - 纸面实盘学习：真实计划触发后的交易复盘。
   - 历史回归学习：策略在不同股票/板块上的适配性。
7. 学习建议必须有作用域隔离：
   - rule
   - sector
   - symbol
   - signal
   - source_rule_id
   否则一个策略的坏样本会污染另一个策略。

## 16. 下一步最小可交付版本

如果下一个 AI 时间也不多，建议只做这个最小闭环：

1. 修复 `upsert_parameter_recommendations` 重复查重。
2. 清理旧的 `backtest_learning_review` 数据。
3. 重新生成 `2026-06-24` 的回归学习报告。
4. 生成一次明日交易计划，确认学习调整进入 `entry_condition.learning_adjustments`。
5. 在前端或 API 返回里至少能看到：
   - 当前计划用了哪些策略。
   - 策略历史胜率。
   - 当前股票/板块是否被学习层降权。
   - 为什么买或为什么不买。

这个闭环做完，系统就从“会回归”进入“会把回归结果反向影响下一次计划”的阶段，这是非常关键的一步。
