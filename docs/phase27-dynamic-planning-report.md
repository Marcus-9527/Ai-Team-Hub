# Phase 27 — Dynamic Replanning Report

## 概述

Phase 27 为 AI Team Hub 增加了 TechLead 动态重规划能力：当 TaskExecutor 中某一步骤在耗尽所有重试后仍然失败时，自动触发 TechLead 重新规划，提供新的执行策略（修改目标/重新分配队友），然后重新提交执行。

## 设计原则

- **不新增调度器/FSM/执行引擎** — 完全复用 TaskExecutor + ExecutionRuntime
- **增量修改** — 只修改失败的步骤，已完成步骤不受影响
- **TechLead 驱动** — 只触发条件满足时（步骤执行失败 + 重试耗尽）才调用
- **非侵入** — TechLead 不可用时自动降级为原失败路径

## 架构变更

### 1. 数据模型 (`models.py`)

在 `TaskModel` 上新增两个字段：

```python
replan_decisions = Column(JSON, default=list)   # 每次 replan 的历史记录
replan_count = Column(Integer, default=0)       # replan 计数器
```

迁移：`database.py` 的 `_migrate_columns()` 已包含这两个字段的自动 ALTER TABLE。

### 2. 执行器 (`task_executor.py`)

**`_finalize_step()` 改动**：在步骤重试耗尽后、抛出 `RuntimeError` 之前，插入 TechLead replan 钩子。

流程：
1. 步骤 ABORTED（重试耗尽）
2. 调用 `_trigger_replan()` → 异步调用 TechLead LLM
3. TechLead 返回 JSON 决策：
   - `{"action": "retry", "new_objective": "...", "reassign": "...", "reasoning": "..."}` → 更新步骤，重新提交
   - `{"action": "abort", "reasoning": "..."}` → 按原路径失败
4. 如果 retry 成功：步骤标记 COMPLETED
5. 如果 retry 失败：步骤标记 FAILED

**新增方法**：
- `_find_techlead(db)` — 按 role='techlead' 查找队友
- `_trigger_replan(db, task, step, error_msg)` — 调用 TechLead 获取重规划决策

### 3. 事件流 (`task_orchestrator.py`)

执行完成后检查 `task.replan_decisions`，发送 `replan_decision` SSE 事件（包含 step_id、reasoning、total_replans）。

### 4. 触发条件

当前触发条件：
- 步骤执行失败（Tool/MAEOS 错误）
- 所有重试耗尽（`max_retries` 次）
- TechLead 队友存在且可用

未实现（可后续添加）：
- Review 连续 rejection 触发
- 队友离线触发

## 文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/models.py` | +3 行 | 新增 `replan_decisions`、`replan_count` 字段 + to_dict |
| `backend/database.py` | +2 行 | 迁移项 |
| `backend/services/task/task_executor.py` | +70 行 | replan 钩子 + `_find_techlead` + `_trigger_replan` |
| `backend/services/task/task_orchestrator.py` | +12 行 | SSE 事件 |
| `backend/tests/test_dynamic_replan.py` | 新文件 | 2 个测试用例 |

## 测试覆盖

- ✅ `test_replan_retry_on_failure` — 步骤失败 → TechLead retry → 重提交 → 成功，验证 step.objective 更新、replan_count、replan_decisions
- ✅ `test_replan_abort_without_techlead` — TechLead 不可用 → 正常失败路径，replan_count=0
- ✅ 全部 13 个原有 executor 测试无回归

## 限制（Ponytail）

- 每个步骤最多一次 replan 尝试（无递归重规划）
- 只支持 `retry`（修改目标+重新分配），不支持 `add_steps`/`remove_steps`
- TechLead LLM 调用超时 60 秒
- 重规划不修改 DAGNodeModel（只改 TaskStepModel）
- 无前端 TechLead Adaptations 面板（只有后端 SSE 事件）
