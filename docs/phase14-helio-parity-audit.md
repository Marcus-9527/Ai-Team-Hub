# Helio Parity Audit — AI Team Hub

> 审计日期: 2026-07-13
> 方法: 源码审查（routes, services, models, frontend components）
> 范围: 8 个 Helio 核心能力维度

---

## 1. Teammate Identity

| 项目 | 状态 | 证据 |
|------|------|------|
| 持久实体 | ✅ 是 | `Teammate` SQLAlchemy model, `teammates` 表, UUID PK |
| user_id 唯一锚点 | ✅ 是 | `teammate.id = gen_uuid()` 全局唯一 |
| brain 绑定 teammate | ❌ 未绑定 | BrainLoader 实现但 chat/task execution 均未调用 `build_prompt()` |
| 重启后人格恢复 | ⚠️ 部分 | Teammate 基础属性恢复；brain fragments 存于 DB 但运行时未加载 |
| task/chat 同一身份 | ✅ 是 | 两者均用 `_load_teammate()` 加载同一条 DB 记录 |

**Identity Score: 7/10**

**Missing**: BrainLoader 未集成到 `team_collaboration.py` 或 `executor.py._run_task()` 的 prompt 构建路径。chat 用 `build_turn_prompt()`（TeammateRunner），task 用直接拼接 system_prompt，两者都不加载 brain fragments（identity/personality/principles/lessons）。

---

## 2. Brain System

| 项目 | 状态 | 证据 |
|------|------|------|
| base | ✅ 存在 | `fragment_store.py` — BrainFragment 复用 MemoryItem, 版本历史 |
| soul | ❌ 未启用 | 不加载 identity/personality/principles 到 LLM prompt |
| act | ❌ 不加载 | 行为/技能提示不在 prompt 中 |
| agents | ⚠️ API 存在 | `GET /api/brain/fragments/{tm_id}` 可用但 UI 未暴露真实执行集成 |
| memory | ⚠️ 部分 | Memory 通过 TaskHook 写入，但 teammate-level isolation 不存在 |
| wiki | ❌ 不存在 | 无 teammate 级知识库/文档 |
| reflection | ⚠️ 注册但薄弱 | BrainTaskHook 注册于 main.py，但只 hook task 生命周期，不参与 chat |

**Brain Score: 4/10**

**核心发现："聊天有brain，执行没有brain" — 成立。**

BrainLoader 已实现（`services/brain/brain_loader.py`）且 `build_prompt()` 支持按顺序拼接 IDENTITY→PERSONALITY→PRINCIPLES→SKILLS→LESSONS 等。但：

- `team_collaboration.py` 调 `build_turn_prompt()` → 走 **TeammateRunner** → 用 `system_prompt + role_context`，不经过 BrainLoader
- `executor.py._run_task()` → `_load_teammate()` 返回 dict，直接用 `teammate_dict.get("system_prompt", "")`，不加载 brain fragments
- BrainTaskHook 只 hook EXECUTION_COMPLETED/TASK_COMPLETED 做 fire-and-forget reflection，不影响 prompt 构建

**根本原因**: BrainLoader 是独立模块，有 API 路由，但没有任何消费方（chat/task executor）调用它。Brain 系统是"可查看但不可使用"的 shelfware。

---

## 3. Autonomous Teammate

| 项目 | 状态 | 证据 |
|------|------|------|
| cede protocol | ⚠️ 实现但未集成 | `cede_protocol.py` (301行) + test + API route, 但 `generate_team_response()` 不调 |
| event wakeup | ⚠️ 实现但未集成 | `event_wakeup.py` (332行) + test, 但没有任何代码 fire/consume 事件 |
| task claim | ⚠️ 实现但未集成 | `task_claim.py` (223行) + test, task_orchestrator 不调 |
| teammate state | ⚠️ 实现但未集成 | `teammate_state.py` (218行) + test, 无运行时消费方 |
| Human→event→claim→执行 | ❌ 未实现 | 真实链路不存在 |

**Autonomous Score: 3/10**

**核心发现：这是 API 模拟，不是真实自主协作。**

所有 autonomous 模块（cede/event_wakeup/task_claim/teammate_state/brain_proposal）都实现了功能代码且有独立测试。它们通过 `routes/autonomous.py` 暴露为 API（`GET /api/autonomous/states`, `POST /api/autonomous/cede`, `POST /api/autonomous/claim`, `POST /api/autonomous/event`），路由已注册到 `main.py`。

但是：

- `grep -r 'from backend.services.autonomous' backend/` → **零匹配**（除了 autonomous.py 自身）
- `team_collaboration.py` 不导入 autonomous 任何模块
- `task_orchestrator.py` 不导入 autonomous 任何模块
- `messages.py` 不导入 autonomous 任何模块
- `executor.py` 不导入 autonomous 任何模块

Human message → event → teammate 判断 → claim → 执行 这个流程**只存在于代码逻辑中，从未被连接**。这些模块是孤立的功能岛。

---

## 4. Execution Runtime

| 项目 | 状态 | 证据 |
|------|------|------|
| read file | ✅ 是 | `tool_runtime.py::file_read()` |
| write file | ✅ 是 | `tool_runtime.py::file_write()` |
| shell | ⚠️ 受限 | 仅 allowlist 命令 (pytest, npm, git*) |
| git | ✅ 是 | `tool_runtime.py` 含 git add/commit/status/diff/log |
| test | ✅ 是 | `reviewer.py` 调 `execute_tool(pytest)` |
| commit | ✅ 是 | `agent.py::run_engineer_workflow()` 含 git commit |
| review | ✅ 是 | `reviewer.py::run_reviewer_workflow()` 读真实 git diff + pytest |

**Runtime Score: 7/10**

**核心发现：Runtime 是真实的，但角色能力不对等。**

- Engineer 有完整的工具集（file_read/file_write/shell_exec/git workflow）
- Reviewer 有 read-only 工具（读 diff、跑 pytest）
- 但 **QA 角色不存在**：无独立 QA workflow，`run_reviewer_workflow()` 兼有 test-run 能力但无 QA 专用逻辑
- 所有角色共享同一个 `ExecutionRuntime` 但通过 `detect_role()` 分配不同 workflow（正确设计）
- Tool runtime 的 shell allowlist 是 `ponytail:` 级别——无任意命令执行

---

## 5. Task DAG

| 项目 | 状态 | 证据 |
|------|------|------|
| parent task | ✅ 是 | `TaskModel.parent_task_id` 字段 |
| child task | ✅ 是 | `TaskModel.child_task_ids` JSON 字段 |
| dependency | ✅ 是 | `TaskModel.dependency` JSON 字段 |
| ready node | ✅ 是 | `dag/core.py::get_ready_nodes()` 拓扑排序 |
| parallel execution | ⚠️ 代码存在 | `DagExecutor.execute_dag()` 用 `asyncio.gather()`，但端到端未验证 |

**DAG Score: 6/10**

**核心发现：DAG 系统结构完整，但 parallel execution 未经真实负载验证。**

- `services/dag/core.py` — 核心：Node, DAGDefinition, topological_sort, get_ready_nodes
- `services/planner/dag_executor.py` — 执行引擎：DB store, retry loop, approval gate, auto-assignment via TeammateSelector
- `services/task/task_orchestrator.py` — 高级编排：plan→assign→DAG→execute 管线
- Task orchestrator 在 review rejection 时自动 spawn 子 Task（parent/child/dependency）✅

**确认的复杂任务路径**：
```
需求 → TechLead plan → DAG → Engineer(A) + Engineer(B) 并行 → Reviewer → QA
```
但实际只有 Engineer → Reviewer 链路的真实端到端测试通过。Engineer A/B 并行执行**未**在真实场景验证。

---

## 6. Memory

| 项目 | 状态 | 证据 |
|------|------|------|
| Private Memory | ❌ 不存在 | memory_items 无 `teammate_id` 字段隔离 |
| Workspace Memory | ⚠️ 结构有 | MemoryType.WORKSPACE 定义，但 isolation 仅靠 source_id |
| Channel Memory | ✅ 是 | MemoryType.CHANNEL + `source_id=channel_id` |
| Teammate isolation | ❌ 不存在 | Engineer 和 Reviewer 共享 channel memory |
| Embedding | ✅ 是 | char-bigram hash 256-dim 向量 |
| Insight | ✅ 是 | rule-based insight engine + store |

**Memory Score: 6/10**

**核心发现：三层记忆框架在定义中存在，但 teammate 级隔离不存在。**

- `memory_items` 表 schema: `source_id` 用于 scope（channel_id/workspace_id/task_id），**无 teammate_id 字段**
- `MemoryType` 枚举: CHANNEL/WORKSPACE/TASK/EXECUTION/DECISION/GLOBAL — 但 TEAMMATE 级别只定义未使用
- `build_chat_context()` 按 `source_id`=channel_id 检索，共享给 channel 内所有 teammate
- "Engineer 学到的经验 Engineer 下次能看到，Reviewer 看不到" → **无法实现**，因为没有 teammate 级隔离

---

## 7. Policy / Safety

| 项目 | 状态 | 证据 |
|------|------|------|
| tool permission | ❌ chat 无检查 | `policy/__init__.py` 只被 `dag_executor.py` 使用 |
| workspace isolation | ✅ 有 | `tool_runtime.py` path containment (.. blocked, / replaced) |
| destructive protection | ❌ 无 | chat 中 shell_exec 无确认/保护 |
| human approval | ⚠️ DAG 层有 | `ApprovalService` + DAG node `require_approval` 标志位 |
| backend enforcement | ❌ chat 无 | chat message flow 绕开所有 policy |

**Policy Score: 3/10**

**核心发现：policy 系统仅作用于 DAG 执行路径，chat 消息流完全无安全约束。**

- PolicyService (`services/policy/__init__.py`) 实现了 teammate/tool/task-type 三档检查
- 但仅 `dag_executor.py` 在使用 → 只有通过 DAG 执行的任务受 policy 约束
- TeamCollaboration chat 流直接调 `TeammateRunner.stream_teammate()` → 无 policy 门控
- 无 destructive operation 保护：chat 中如果 teammate 被 prompt 诱导写文件，没有后端阻止
- Approval gate 仅作用于 DAG 节点，与 chat 无关

---

## 8. UI

| 项目 | 状态 | 证据 |
|------|------|------|
| teammate | ✅ 是 | `ChannelView` 队友气泡 + `Sidebar` 队友列表 |
| brain | ✅ 是 | `BrainPage.jsx` 展示 fragments/types/versions/rollback |
| task graph | ⚠️ 有但未验证 | `DAGViewer.jsx` 展示 DAG 节点/依赖 |
| execution过程 | ⚠️ 部分 | `ExecutionTimeline.jsx` / `TaskProgressPanel.jsx` |
| files changed | ⚠️ 有 | `ExecutionResultCard.jsx` 展示 files_changed |
| review结果 | ✅ 是 | TaskDetailView 含 review_status/comments |
| memory | ✅ 是 | `MemoryPanel.jsx` 四级视图 + timeline |

**UI Score: 6/10**

**核心发现：UI 覆盖较全，但后端数据不足时大量显示 "Coming Soon"。**

- brain、memory、task 视图都已实现且非空
- DAGViewer/ExecutionTimeline 依赖后端真实数据 — 如果 DAG 未被执行过则显示空状态
- `DeveloperCenter` 对所有 `/api/*` 调用的失败容错为 `.catch(() => false)` → 后端路由缺失时优雅降级到 "Coming Soon"
- 无 brain prompt 预览的实际影响可视化：用户看不到 "当前 brain 片段如何影响 AI 回复"

---

## 最终评分汇总

| 维度 | 分数 | 核心问题 |
|------|------|---------|
| 1. Teammate Identity | **7/10** | Brain 未绑定到运行时 prompt |
| 2. Brain System | **4/10** | 模块完整但零集成到 chat/execution |
| 3. Autonomous Teammate | **3/10** | API 模拟，无真实链路 |
| 4. Execution Runtime | **7/10** | QA 角色缺位，shell 受限 |
| 5. Task DAG | **6/10** | 结构完整，并行未验证 |
| 6. Memory | **6/10** | 无 teammate 级隔离 |
| 7. Policy / Safety | **3/10** | 仅覆盖 DAG 路径 |
| 8. UI | **6/10** | 覆盖广但后端空数据时无效 |
| **总计** | **42/80** | — |

---

## 修复优先级

### P0 — Parity 阻塞（不修则 Helio 等价不成立）

1. **BrainLoader 集成到 chat + task execution** — `team_collaboration.py` 的 `generate_team_response()` 和 `executor.py._run_task()` 应调 `BrainLoader.build_prompt()` 加载 identity/personality/lessons。这是"聊天有brain，执行没有brain"的根因。（影响维度 1, 2）
2. **Cede Protocol 集成到 chat 流** — `generate_team_response()` 在调 `TeammateRunner.stream_teammate()` 之前先跑 cede 判断。这是 autonomous teammate 的入口门闩。（影响维度 3）
3. **Chat 流加入 policy 门控** — `messages.py` 调 `generate_team_response()` 之前做 tool permission 和 teammate permission 检查。现有 PolicyService 可直接复用。（影响维度 7）

### P1 — 功能缺口

4. **Memory 加 teammate_id 隔离** — `memory_items` 表加 `teammate_id` 列 + `MemoryType.TEAMMATE` 真正使用。Engineer 和 Reviewer 的 memory 不互相污染。（影响维度 6）
5. **QA 独立 workflow** — `executor.py.detect_role()` 增加 `qa` 分支，类似 reviewer 但专注 test 执行 + 报告。（影响维度 4）
6. **TaskClaim 集成到 TaskOrchestrator** — `start_task()` 的 assign 阶段使用 `TaskClaimManager` 做竞争分配，替代当前直接指定。（影响维度 3, 5）

### P2 — 商业增强

7. **并行 DAG 端到端验证** — 用两个 Engineer 节点 + asyncio.gather 的真实 e2e 测试。（影响维度 5）
8. **Autonomous 事件总线接入 TaskHook** — `event_wakeup.py` 从 TaskHook 系统接收 TASK_CREATED/FAILED 事件，触发 claim/retry。（影响维度 3）
9. **Human approval UI** — ApprovalPanel 用于 DAG 节点的 require_approval，打通 human-in-the-loop。（影响维度 7, 8）
