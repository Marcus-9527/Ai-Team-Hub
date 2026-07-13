# Phase 17 — Enterprise Governance Layer

## 变更清单

| 文件 | 变更 |
|------|------|
| `backend/models.py` | +`PolicyDecisionModel`；`PolicyEffect` 增加 `APPROVAL_REQUIRED` |
| `backend/database.py` | 注册 `PolicyDecisionModel` 到 `init_db` |
| `backend/services/task/task_policy.py` | `check_tool_action` 写入审计 + 增加审批门控；`check_message_policy` 增加 `db` 参数并写入审计；新增 `_APPROVAL_REQUIRED_PATTERNS`、`_resource_glob_match`、`_write_decision`、`list_policy_events` |
| `backend/services/runtime/tool_runtime.py` | `execute_tool` 增加 `task_id`/`channel_id` 参数；审批结果返回 `requires_approval: True` |
| `backend/routes/messages.py` | `check_message_policy` 调用传入 `db` |
| `backend/routes/policy.py` | **新文件** — `GET /api/policy/events` |
| `backend/main.py` | 注册 `policy_router` |
| `backend/tests/test_policy_audit.py` | **新文件** — 5 个审计测试 |
| `backend/tests/test_policy_message_gate.py` | 更新 `check_message_policy` 调用签名 |

## 1. Policy Audit Persistence

新增 `policy_decisions` 表，所有 `ALLOW`/`DENY`/`APPROVAL_REQUIRED` 决策写入数据库，替换原有 `logger.info`。

**PolicyDecisionModel 字段：** `id`, `teammate_id`, `action`, `resource`, `effect`, `reason`, `task_id`, `workspace_id`, `channel_id`, `context_json`, `created_at`

## 2. Tool Context 注入

`execute_tool()` 新增可选参数 `task_id`、`channel_id`（默认空字符串，向后兼容）。传递到 `check_tool_action()` 写入审计记录，实现「谁、在哪个任务、哪个 workspace、做什么」的追踪。

## 3. Human Approval Gate

高风险操作触发审批：

| 模式 | 触发条件 |
|------|----------|
| `shell_exec *deploy*` | 任何含 `deploy` 的命令 |
| `shell_exec *production*` | 任何含 `production` 的命令 |
| `shell_exec *database_delete*` | 数据库删除操作 |
| `shell_exec *credential_rotate*` | 凭据轮换操作 |
| `file_write *production*` | 写 production 相关文件 |
| `file_write *credential*rotate*` | 凭据文件操作 |

`check_tool_action` 返回 `allowed=False, reason="APPROVAL_REQUIRED: …"`；`execute_tool` 识别前缀并在结果中设置 `requires_approval: True`。实际审批流（创建 `TaskApprovalModel`）由上层任务系统处理。

## 4. Message Policy

`check_message_policy` 默认 allow，写入审计记录。为 bot 反垃圾/外部频道限制预留接口。

## 5. Policy Dashboard API

```
GET /api/policy/events?limit=50&effect=deny
```

返回最近政策决策记录，支持按 `effect` 过滤（allow/deny/approval_required）。

## 6. 测试覆盖

```
backend/tests/test_policy_audit.py — 5 tests
  ✓ deny 产生审计记录
  ✓ allow 产生审计记录
  ✓ approval 阻断执行
  ✓ 非匹配操作通过
  ✓ list_policy_events 查询

backend/tests/test_policy_tool_gate.py — 7 tests（未改动，全部通过）
backend/tests/test_policy_message_gate.py — 1 test（更新签名，通过）
```

## 设计决策（Ponytail）

- **审批门控用硬编码模式匹配而非策略表**：当前模式数量<10，硬编码足够。升级为 `PolicyRuleModel(APPROVAL_REQUIRED)` 时只需在 `_APPROVAL_REQUIRED_PATTERNS` 位置切到数据库查询。
- **`execute_tool` 不直接创建 TaskApprovalModel**：tool_runtime 是底层组件，没有 task/step 上下文。返回 `requires_approval` 信号，由任务执行器处理完整的审批生命周期。
- **审计写入同步（同一 DB 会话）**：单 SQLite 实例下开销可忽略。需要扩展时改为后台队列写入。
- **无前端 Policy Activity 页面**：API 已提供数据，前端页面属于独立 UI 工作。
