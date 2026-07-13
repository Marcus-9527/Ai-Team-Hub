# Phase 10 — Human Approval & Policy Engine

## 架构概览

Phase 10 在 DAG Runtime 执行流程中插入 **策略检查（Policy）** 和 **人工审批（Approval）** 两堵门。所有 DAG Node 在进入执行之前必须经过这两道关卡。

```
Node Ready (deps satisfied)
    │
    ▼
┌─────────────────────────┐
│   PolicyService         │  ← 检查 teammate / tool / task-type 权限
│  evaluate_node()        │
└─────────┬───────────────┘
          │
     ┌────┴────┐
     │ allowed │ 否 → FAILED (POLICY_BLOCKED)
     └────┬────┘
          │ 是
          ▼
┌─────────────────────────┐
│   require_approval?     │  ← 检查 DAGNode.require_approval
└─────────┬───────────────┘
          │
     ┌────┴────┐
     │ 需要审批 │ → ApprovalService.create() → asyncio.Event.wait()
     └────┬────┘            ▲
          │ 不需             │ 用户调用 POST /approve | /reject
          ▼                  │
     ┌──────────┐       ┌───┴────┐
     │  Approved │──────→ 继续执行
     └──────────┘
          │
     ┌────┴────┐
     │ Rejected│ → FAILED (REJECTED)
     └─────────┘
          │
          ▼
    Execution retry loop
```

## 新增文件

| 文件 | 说明 |
|------|------|
| `services/approval/__init__.py` | `ApprovalRecord` + `ApprovalService`（in-memory 审批注册表） |
| `services/policy/__init__.py` | `PolicyService` + 独立检查函数（teammate/tool/task-type） |
| `routes/approvals.py` | API 路由：GET /api/approvals, POST approve/reject |
| `tests/test_dag_approval.py` | 全路径测试（审批暂停恢复、策略拒绝、自动执行） |
| `docs/phase10-architecture.md` | 本文档 |

## 修改文件

| 文件 | 变更 |
|------|------|
| `services/dag/core.py` | DAGNode 新增 `require_approval` 字段 + to_dict 序列化 |
| `models.py` | DAGNodeModel 新增 `require_approval` 列（String "0"/"1"） |
| `services/planner/dag_executor.py` | DAGStore 保存/加载 `require_approval`；DagExecutor._run_node 嵌入 policy check + approval gate |
| `routes/dags.py` | NodeDef 新增 `require_approval` 参数 |
| `main.py` | 注册 approvals 路由 |
| `database.py` | 无需改动（DAGNodeModel 已在 init_db 导入） |

## Approval Model

```python
class ApprovalRecord:
    id: str            # apr_<uuid>
    execution_id: str  # DAG execution ID
    dag_node_id: str   # DAG node ID
    status: ApprovalStatus  # PENDING | APPROVED | REJECTED
    requested_by: str       # who triggered the approval
    approved_by: str        # who resolved it
    created_at: float       # unix timestamp
    resolved_at: float      # unix timestamp
```

- 使用 **asyncio.Event** 实现阻塞等待（不占用 worker 线程）
- 提供 `wait(timeout)` 方法，超时自动标记 REJECTED
- in-memory 存储；如需要多进程/持久化可替换为 DB 实现

## Policy 检查

```python
check_teammate_permission(teammate, allowed_teammates)  # 空列表=允许所有
check_tool_permission(tool, allowed_tools)
check_task_type(task_type, allowed_types)
```

PolicyService.evaluate_node() 聚合检查，任一失败返回 `PolicyResult(allowed=False, reason=...)`。

## API

| Method | Path | 说明 |
|--------|------|------|
| GET | /api/approvals | 列出 PENDING 审批（?all=1 列出全部） |
| POST | /api/approvals/{id}/approve | 批准（body: {by: "username"}） |
| POST | /api/approvals/{id}/reject | 拒绝（body: {by: "username"}） |

## 边界与约束

- **审批超时**：`ApprovalRecord.wait()` 默认 24h 超时，超时自动标记 REJECTED
- **幂等保护**：对已非 PENDING 的记录 approve/reject 抛出 ValueError
- **策略执行位置**：Policy check 在 approval gate **之前**执行
- **持久化限制**：当前 ApprovalRecord 是 in-memory；进程重启后丢失未完成审批。生产环境应替换为 DB 或 Redis 实现
