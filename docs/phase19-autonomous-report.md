# Phase 19 — Autonomous Runtime Integration Report

## 目标
将 Autonomous 模块接入真实运行链路，从不执行的 stub/模拟 阶段升级为完整管线。

## 变更清单

### 1. Freshness Cede — `evaluate_context()`
**文件**: `backend/services/autonomous/cede_protocol.py`

新增 `evaluate_context(channel_id, message_id, teammate_id)` 方法：
- 从 DB 读取最近 channel messages
- 调用 `decide()` 做 peer-answered / duplicate / supplement 判断
- 自动记录决策到 in-memory records + memory items
- 返回 `(decision, record_id)`

内部依赖 `_fetch_channel_messages()` 和 `_load_teammate()` 两个私有方法，均在 try/except 中，DB 不可用时 graceful fallback。

### 2. Event Wakeup 真接入
**文件**: `backend/services/autonomous/event_wakeup.py`

`_on_task_created` 处理函数在 claim 成功后，新增实际执行阶段：
- 加载 `TaskModel` 从 DB
- 创建 `ExecutionRuntime` + `TaskOrchestrator`
- 调用 `orch.start_task()` 真实执行
- fire-and-forget，非阻塞

新增 `MESSAGE_EVENT` 事件类型（`WakeupEvent`），供 automation rules 订阅。

### 3. Automation 事件触发
**文件**:
- `backend/models.py` — `AutomationRuleModel.trigger_event` 列
- `backend/routes/automation.py` — schema + CRUD + polling loop 适配
- `backend/services/autonomous/event_wakeup.py` — `_trigger_automation_rules()` 桥接函数

`trigger_event` 为可空 VARCHAR，取值如 `"task_created"`、`"task_failed"`、`"review_rejected"`、`"message_event"`。  
事件触发时，`_trigger_automation_rules()` 查询所有匹配的 active rules 并创建+执行 task。

### 4. Teammate State 真实更新
**文件**: `backend/services/runtime/executor.py`

在 `_run_task()` 中 3 处注入 state 变更：
- 任务开始 → `set_working(teammate_id, task.id)`
- 任务完成 → `set_idle(teammate_id)`
- 任务失败 → `set_offline(teammate_id)`

使用 `asyncio.ensure_future` 避免阻塞执行管线。

### 5. 测试
**文件**: `backend/tests/test_autonomous_loop.py`

覆盖：
- `evaluate_context()` — channel 读取 + 决策 + 去重
- Event Wakeup — 订阅派发
- Teammate State — IDLE→WORKING→IDLE 完整轮回、失败→OFFLINE、历史记录
- Cede Protocol — 多 teammate 竞争去重

## 约束遵守
- ✅ 不新建 scheduler / runtime / FSM
- ✅ 复用 event_wakeup / TaskOrchestrator / ExecutionRuntime / BrainLoader / CedeProtocol
- ✅ 最简改动 — 所有新增代码 ≤ 10 行/处

## 架构图

```
Event (TASK_CREATED)
  │
  ▼
event_wakeup.publish()
  │
  ├──▶ find available teammates (state_manager)
  │     │
  │     ▼
  │   claim_manager.claim()
  │     │
  │     ▼
  │   ExecutionRuntime + TaskOrchestrator.start_task()
  │     │
  │     ▼
  │   _run_task() → set_working()
  │       │
  │       ├── complete → set_idle()
  │       └── fail → set_offline()
  │
  └──▶ _trigger_automation_rules(event_type)
        │
        ▼
      TaskManager.create_task() → ExecutionRuntime + TaskOrchestrator
```

## 状态
Phase 19 完成。所有改动同步到 `main` 分支。
