# Phase 26.5 — TechLead Manager 升级报告

## 目标

把 TechLead 从纯分析角色升级为能影响 teammate 分配的 AI Team Manager。

## 改动总览

| # | 改动 | 文件 | 行数 |
|---|------|------|------|
| 1 | 离线守卫：TL 推荐离线 teammate 时跳过 override | `task_orchestrator.py:_assign_and_save` | +6 |
| 2 | Pydantic 暴露 `techlead_decision` | `routes/tasks.py:TaskResponse` | +1 |
| 3 | 前端 Decision 卡片 | `TaskDetailView.jsx` renderOverview | +70 |
| 4 | 测试：offline fallback | `test_techlead_authority.py` | +38 |

## 已有功能（Phase 25/26）

- ✅ TechLead 在 plan → assign 之间执行 review，产生 JSON 决策
- ✅ 决策存入 `task.techlead_decision`（JSON column）
- ✅ `_assign_and_save` 解析 `teammate_recommendations`→ 作为 `techlead_override` 传入 Selector
- ✅ TeammateSelector 对推荐 teammate 做 score boost
- ✅ TaskModel.to_dict() 暴露 techlead_decision

## 本次新增

### 1. 离线守卫（`_assign_and_save`）

当 TechLead 推荐了一个 OFFLINE 状态的 teammate 时，跳过 override，让 Selector 自然选择：

```python
_st = await get_state_manager().get(tm.id)
if _st and _st.state.value == "offline":
    continue  # → selector fallback
```

不阻断任务，不抛异常。

### 2. Pydantic Schema

`TaskResponse` 新增字段：
```python
techlead_decision: Optional[dict] = None
```

使得 GET `/api/tasks/{id}` 返回 techlead_decision 数据。

### 3. 前端 TechLead Decision Card

Overview tab 中展示：
- 🧠 标题 + BrainCircuit 图标
- Risk 等级（颜色标签：HIGH=红，MEDIUM=黄，LOW=绿）
- Confidence 百分比
- 计划步骤数
- Analysis 文本
- Assignments：每步 #step → teammate + reasoning + confidence
- Risk Factors：红色标签列表

### 4. 测试覆盖

`test_techlead_authority.py` 5 个场景全通过：

| 测试 | 状态 |
|------|------|
| TL recommendation 生效 | ✅ |
| 非法推荐（不存在 teammate）→ fallback | ✅ |
| HIGH risk → policy approval_required | ✅ |
| 无 TL decision → 正常 selector | ✅ |
| **TL 推荐 offline teammate → fallback** | **✅ 新增** |

## 完整流程

```
Task
→ PlanningEngine → DAG
→ TechLead Review → techlead_decision JSON  (Phase 25)
→ Assign & Save:
    ├─ TL 推荐存在 + 在线 → 作为 override 传入 Selector
    ├─ TL 推荐离线 → skip override → Selector 自然选择
    └─ 无 TL 推荐 → Selector 自然选择  (Phase 24)
→ Claim → Assign → Execute
```

## ponytail 标记

- 离线检查用 `get_state_manager().get()` 同步查内存状态，无 DB 开销
- skill 不匹配检查没加——Selector 的 scoring 已有保护（低 skill_match → base score 低 → bonus 不够逆袭）
- TechLeadAssignment 数据格式复用已有 `teammate_recommendations`，不新增 model
- 测试只加了一个关键场景，其余由已有测试覆盖
