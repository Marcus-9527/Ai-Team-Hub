# Phase 12 — Teammate Auto Assignment

## 概述

DAG Node 执行前，根据 `required_skills` 自动从数据库中选择最佳 Teammate。

## 数据流

```
DAGNode (required_skills)
        │
        ▼
TeammateSelector.recommend_by_skills()
        │
        ├── skill_match    × 0.6
        ├── experience     × 0.3  (average_score)
        └── availability   × 0.1  (1 - exec_count/200)
        │
        ▼
selected → node.teammate / node.selected_teammate_id / node.assigned_at
        │
        ▼
ExecutionRuntime.execute(teammate=...)
        │
        ▼
ExecutionRecord.teammate ← 持久化
        │
        ▼
EvaluationService.evaluate() → ExperienceStore.update_from_evaluation()
        │
        ▼
Teammate.success_rate / average_score / execution_count ← 更新
```

## 改动文件

| 文件 | 改动 |
|------|------|
| `services/teammate_intelligence/__init__.py` | 新增 `recommend_by_skills()`，评分 skill(0.6) + experience(0.3) + availability(0.1) |
| `services/dag/core.py` | `DAGNode` 新增 `selected_teammate_id` / `assigned_at` 字段 |
| `services/planner/dag_executor.py` | `DagExecutor._run_node()` 执行前自动选人；`DAGStore` 持久化新字段 |
| `services/runtime/executor.py` | `RuntimeTask` 新增 `teammate` 字段；`execute()`/`submit()` 透传；`_run_task()` 写入 `ExecutionRecord` |
| `models.py` | `DAGNodeModel` 新增 `selected_teammate_id` / `assigned_at` 列 |

## 评分模型

```
final = skill_match * 0.6 + experience_score * 0.3 + availability * 0.1

skill_match    :  teammate技能与required_skills的交集比例
experience_score : teammate.average_score (0-1)
availability    :  max(0.1, 1.0 - execution_count / 200)
```

## 触发条件

- `node.required_skills` 非空 **且** `node.teammate` 为空时触发
- 已有 teammate 的节点跳过
- DB 无 Teammate 时静默失败，teammate 保持空

## API

通过 `GET /api/dags/{dag_id}` 查看节点分配结果：

```json
{
  "nodes": {
    "node_xxx": {
      "teammate": "Engineer A",
      "selected_teammate_id": "tm-uuid",
      "assigned_at": 1712345678.0,
      "required_skills": ["python", "coding"]
    }
  }
}
```

## 边界

- `ExperienceStore.update_from_evaluation()` 已在 Phase 7 接入 `EvaluationService.evaluate()`，Evaluation 完成后自动更新 Teammate 经验数据。无需额外改动。
- `availability` 当前用 execution_count 的简单衰减函数估算，未追踪并发负载。
- 评分策略不可配置（YAGNI），后续可提取为 `ScoringStrategy`。

## 测试覆盖

| 测试 | 文件 |
|------|------|
| recommend_by_skills 精确匹配 | `test_teammate_assignment.py::TestRecommendBySkills::test_exact_skill_match` |
| 多候选排序 | `test_teammate_assignment.py::TestRecommendBySkills::test_multi_candidate_ranking` |
| 无匹配 fallback | `test_teammate_assignment.py::TestRecommendBySkills::test_no_match_fallback` |
| 评分权重合法性 | `test_teammate_assignment.py::TestRecommendBySkills::test_scoring_weights` |
| DAG 执行自动分配 | `test_teammate_assignment.py::TestDagAutoAssignment::test_auto_assigns_teammate` |
| 已有 teammate 跳过 | `test_teammate_assignment.py::TestDagAutoAssignment::test_skips_assignment_when_teammate_set` |
| 无 skills 跳过 | `test_teammate_assignment.py::TestDagAutoAssignment::test_skips_when_no_required_skills` |
| 空 DB fallback | `test_teammate_assignment.py::TestDagAutoAssignment::test_fallback_when_no_teammates` |
| 序列化 | `test_teammate_assignment.py::TestDAGNodeNewFields` |
| 存量回归（DAG 核心、Intelligence、Approval） | `test_dag.py`, `test_teammate_intelligence.py`, `test_dag_approval.py` |
