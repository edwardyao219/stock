# Startup Lifecycle Runtime Rollout Design

## 目标

让已合并到 `main` 的启动生命周期代码进入本地 API 与 Celery worker 运行态，并在不生成测试信号、不发送通知、不调整策略阈值的前提下验证运行路径。

## 当前状态

- `main` 已包含 lifecycle 与候选淘汰原因按日期过滤代码，测试已通过。
- API 仍由旧的 `stock-api-funnel` screen 进程提供服务，响应缺少新字段。
- Celery worker 在线且无活动任务，可安全重启。
- Celery beat 在线；现有 09:35、10:30、14:50 计划不需要为本次代码加载而变更。
- 2026-07-22 盘后状态失败源于 `cyq_perf` 缺失触发的数据证据门禁，不属于启动生命周期发布问题。

## 范围

1. 优雅停止并重新创建现有 `stock-api-funnel` screen 中的 Uvicorn API 进程。
2. 仅在 Celery `inspect active` 为空时，用 launchd 重启既有 worker。
3. 保持 beat 运行，不增加 worker、screen、定时任务或测试任务。
4. 使用只读 HTTP、Celery inspect 和账本查询验证新代码已加载。

## 执行顺序

1. 再次确认 API 健康、worker 在线且无活动任务；如存在活动任务，停止并等待下次空闲窗口。
2. 向 `stock-api-funnel` 发送终止信号，等待其释放 8000 端口，再以相同名称和 Uvicorn 命令启动新 screen。
3. 通过 `launchctl kickstart -k` 重启 `com.stock-research.celery-worker`；beat 不重启。
4. 轮询 API 健康端点与 OpenAPI，确认服务恢复。
5. 查询收盘状态和启动追踪端点，确认 API 返回生命周期/淘汰原因字段；使用 `celery inspect ping` 与 `inspect registered` 确认新 worker 应答并注册生命周期相关任务。

## 验收与停止条件

- API 健康端点成功，端口 8000 上只有新的 Uvicorn 进程。
- worker 只有一个 launchd 管理的实例，`inspect active` 为空且 `inspect ping` 成功。
- 生命周期端点可读，且旧 API 缺失的字段已出现；空数据允许，不要求人为制造信号。
- 不手动调用盘中/盘后任务，不调用钉钉，不修改任何阈值。
- 若 API 未在有限重试内恢复、worker 出现活动任务或失败重启，停止后续动作并保留现状与诊断输出。

## 后续观察

在真实交易日记录 09:35、10:30、14:50 任务结果和 `ResearchSignalLedger(source="startup_state")`：预热/试探不通知，确认/失效各仅通知一次，失效只取消 `planned` 计划。样本不足时只展示统计，不进行策略参数优化。
