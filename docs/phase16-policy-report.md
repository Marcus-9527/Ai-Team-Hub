# Phase 16: Policy Engine — 实化报告

## Policy Score: 0/10 → 8/10

### 变更文件

| 文件 | 改动 |
|------|------|
| `backend/models.py` | +PolicyRuleModel, +PolicyEffect |
| `backend/services/task/task_policy.py` | +check_tool_action(), +init_default_policy_rules() |
| `backend/services/runtime/tool_runtime.py` | execute_tool()增加 subject 参数 + Policy 门控 + git_commit/git_merge 支持 |
| `backend/services/runtime/agent.py` | 传 subject="engineer" 给 execute_tool |
| `backend/services/runtime/reviewer.py` | 传 subject="reviewer" 给 execute_tool |
| `backend/tests/test_policy_tool_gate.py` | 7 个测试，新文件 |

### 架构

```
ToolCall → execute_tool(call, ws_id, subject) 
             ↓
         Policy.check(subject, action, resource)
             ↓
         DB: policy_rules (DENY rules)
             ↓
         allow → execute, deny → return error
```

- 所有危险动作（file_write, shell_exec, git_commit, git_merge, task_create, message_send）统一经过 `execute_tool()` 的 Policy Gate
- 门控只读 DENY 规则，DENY 为空则全部 allow（安全默认）
- DB 不可用时退化到 allow（不阻塞现有流程）

### 默认规则

| 主体 | 动作 | 资源 | 效果 | 理由 |
|------|------|------|------|------|
| engineer | git_merge | main | DENY | policy:no-main-merge |
| engineer | file_write | *production*secret* | DENY | policy:no-prod-secret |
| engineer | file_write | *delete*workspace* | DENY | policy:no-delete-workspace |
| engineer | shell_exec | *rm -rf /* | DENY | policy:no-force-delete |
| reviewer | file_write | * | DENY | policy:reviewer-readonly |

初始化调用 `init_default_policy_rules()` 幂等（检查重复再插入）。

### 测试覆盖

- ✅ Engineer merge main → deny
- ✅ Reviewer write file → deny
- ✅ Engineer normal write → allow
- ✅ Engineer rm -rf → deny
- ✅ file_read (非门控动作) → allow
- ✅ 未知动作 → allow
- ✅ 默认规则幂等插入

### 未做

- **Human approval for deploy production**：审批流需要定义「deploy production」action + TaskApprovalModel 集成。当前 TaskExecutor 已有 ApprovalRequiredError 机制，接入点在 task_executor 而非 tool_runtime。需要独立的 Phase 来定义 deploy action → 触发 approval → 执行 deploy 的完整管线。
- **Audit event log 持久化**：当前 policy check 用 logger.info 输出。完整的 audit trail 需要写入 event_log 表（现有 `TaskEventLogger.log_policy_blocked()` 可用，但需要 task 上下文）。tool_runtime 层无 task 上下文，不适合直接调用 TaskEventLogger。
- **task_create / message_send 实装**：这两个 action 已在 `_CHECKABLE_ACTIONS` 和 `_dangerous` 中注册，但 tool_runtime 不处理它们（需要各自的 handler）。门控已就位，等实际调用加入后自动生效。
