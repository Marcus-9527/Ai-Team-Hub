# Phase 27.5 — Dynamic Organization Upgrade 报告

## 目标

TechLead 从 retry-only manager 升级为多动作 planner。

## 改动总览

| # | 改动 | 文件 | 行数 |
|---|------|------|------|
| 1 | 提取 `_apply_replan` — 统一 retry/skip/reassign 处理 | `task_executor.py` | +105 / -40 |
| 2 | 新增 `_store_replan_brain` — 写入 DECISIONS BrainFragment | `task_executor.py` | +20 |
| 3 | 提前触发 replan — SYSTEM_FAIL 时绕过无意义重试 | `task_executor.py` | +5 |
| 4 | 更新 TechLead prompt — 增加 skip/reassign JSON 示例 | `task_executor.py` | +3 |
| 5 | 测试覆盖 skip, reassign, retry 路径 | `test_dynamic_replan.py` | +84 |

总变动：约 **130 行净增**（含测试）。

## 详细改动

### 1. `_apply_replan` — 统一动作处理器

原代码将 retry 逻辑内联在 `_finalize_step` 中。现提取为独立方法，处理三种 action：

- **retry** — 更新 objective/teammate → 重新 submit + wait（与原行为一致）
- **skip** — 将步骤标记为 SKIPPED（已有状态），下游依赖解析为该步骤"成功"
- **reassign** — 经 retry 路径重新提交，但受 TechLead 指定的 teammate 驱动

### 2. `_store_replan_brain` — 记忆持久化

每次 replan 执行后，fire-and-forget 写入 BrainFragment（类型 `brain:decisions`）：

```json
{
  "event": "replan",
  "task_id": "...",
  "step_id": "...",
  "action": "retry|skip|reassign",
  "failure_reason": "...",
  "adaptation": { "new_objective": "...", "reassign": "..." },
  "result": "applied"
}
```

未来 TechLead planning recall 可直接查询 `brain:decisions` 历史。

### 3. 提前触发条件

`_finalize_step` 中第一个重试回合（attempt=1）检测到 `FailureType.SYSTEM_FAIL`（timeout/connection/502 等工具级错误）时，**先调 replan 再决定是否重试**，而不是无意义消耗重试次数。

已有触发路径（retry exhausted → replan）不变。

### 4. Prompt 更新

包含三种 action 的 JSON 格式示例，TechLead 可选择具体动作：

- `retry` + optional `new_objective` + optional `reassign`
- `skip` + `reasoning`
- `reassign` + `reassign` (teammate_id)
- `abort`

## Ponytail 标记

| 简化 | 理由 |
|------|------|
| ❌ 未实现 `add_step` | YAGNI。动态加步骤需要 DAG 重排 + dep 维护 + 步骤编号重建，当前无真实需求。需要时从 `_apply_replan` 扩展。 |
| ❌ 未实现独立 DAG 修改组件 | DAG 只用于可视化 + 创建时 persist；runtime 状态在 TaskSteps 上，修改 steps 足够。 |
| ❌ 未做前端 Adaptation Timeline | 后端能力已具备；前端渲染推迟到下一轮。 |
| ✅ `reassign` 复用 retry 重执行路径 | 减少代码重复。reassign = "用新 teammate 重试"。 |
| ✅ BrainFragment fire-and-forget | 非关键路径，失败不阻塞执行。 |

## 测试覆盖

| 测试 | 状态 | 说明 |
|------|------|------|
| `test_replan_retry_on_failure` | ✅ 已有 | 通过 `_apply_replan` 走 retry 路径 |
| `test_skip_step_via_replan` | ✅ 新增 | action=skip → step SKIPPED |
| `test_reassign_step_via_replan` | ✅ 新增 | action=reassign → teammate 更新 + 重执行 |
| `test_replan_abort_without_techlead` | ✅ 已有 | 无 TechLead 时正常失败 |

## 完整流程

```
Step FAILS after retry (or SYSTEM_FAIL attempt=1)
  → _trigger_replan (prompt TechLead)
    → _apply_replan:
       ├─ retry   → update objective/teammate → re-submit → success ✓
       ├─ skip    → mark step SKIPPED → continue ✓
       ├─ reassign → update teammate → re-submit → success ✓
       └─ abort/None → task FAILED ✗
  → _store_replan_brain (fire-and-forget DECISIONS)
```
