#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# start-backend.sh — AI Team Hub 后端启动脚本
#
# 为什么是 1 个 worker（重要，必读）：
#
# 当前后端依赖进程内内存状态来调度 AI 任务执行：
#   - ExecutionRuntime（内存 PriorityQueue + asyncio.Event）
#   - _dispatch_loop（asyncio.create_task 后台协程）
#   - _completed_events（dict[str, asyncio.Event]，跨协程信号）
#   这些机制全部绑定在单个 Python 进程的事件循环内。
#
# 如果用 uvicorn --workers N（N > 1）启动，N 个进程各自有独立的
# ExecutionRuntime 单例、独立的队列、独立的事件循环。请求可能被
# 路由到任意 worker，但后台 dispatch loop 只活在其中一个 worker 里。
# 这会导致：
#   (a) 任务提交到 worker A 的队列，但 dispatch loop 在 worker B
#       → 任务永远不被调度，asyncio.Event 永不触发
#   (b) 卡死的 worker 持有未提交的 SQLite 事务 → 整个数据库被写锁
#       锁死，其他 worker 无法写入任何状态（包括 cancel/fail）
#   (c) 没有外部 watchdog 能检测 worker 内部调度循环已死
#
# 这不是"偶尔出现的竞态"而是架构级的不安全——多 worker 下的内存态
# 调度器不可靠。短期止血方案就是将 worker 数固定为 1，代价是并发
# 请求排队处理（单人/实验场景完全够用）。
#
# 何时可以改回多 worker：
#   当 ExecutionRuntime 不再依赖进程内 asyncio.Event 做任务同步，
#   改用跨进程任务队列（Redis RQ / ARQ / Celery）以后，才能安全
#   地增加 worker 数。在那之前，任何"觉得 1 个 worker 性能不够"
#   的直觉都应该先压测验证是否真的遇到了吞吐瓶颈，而不是盲目调高。
# ──────────────────────────────────────────────────────────────────────────────

cd "$(dirname "$0")"
PYTHONPATH=backend exec /home/liunx/.hermes/hermes-agent/venv/bin/python3 \
  -m uvicorn backend.main:app \
  --host 0.0.0.0 --port 8910 \
  --log-level info \
  --workers 1 \
  > /tmp/backend.log 2>&1
