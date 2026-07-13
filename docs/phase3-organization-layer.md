# Phase 3 — AI Team Organization Layer

升级目标：从单 Agent 执行系统 → 多 Teammate 协作系统。
约束：不新建 scheduler / FSM / engine；复用 TaskOrchestrator + ExecutionRuntime + Runtime Tools。

---

## 一、架构变化

### 1. DAG ready-batch 并发（方案 A）
- `TaskExecutor.execute_task` 串行 `for step` → **ready-batch 循环**：
  1. `resolver.get_ready_nodes(completed)` 取当前可运行节点（复用 `services/dag/core.py`）
  2. 每个 ready step：`_submit_one`（policy gate + transition RUNNING + `runtime.submit`，串行快路径）
  3. `asyncio.gather(_wait_parallel)`：**并行只发生在慢的 LLM wait**（`runtime.wait`，无 DB 写）
  4. 串行 `_finalize_step`：**所有 DB 写回到单一 AsyncSession**（record_execution / handle_step_success / closure / trace）
  5. 标记完成 → 下一波
- **关键约束**：AsyncSession 不支持并发写。并发只放 `runtime.wait`（网络 IO），DB 落库串行化。这与 ExecutionRuntime 已有的 4-worker 并发**互补**（runtime 内部真正并行跑 LLM，DB 零竞争）。
- retry / policy / approval / closure / review-relay **原样保留**，未改动语义。

### 2. TaskStep deps
- `TaskStepModel` 新增 `deps = Column(JSON, default=list)`（DAG 边持久化）。
- `orchestrator._create_steps`：DAG node deps → step deps 映射落库。
- 执行时 `resolver` 用 step 的 `deps` 判定 ready，不再依赖 `order` 顺序。

### 3. TechLead role（不写实现代码）
- `detect_role` 新增 `techlead` 分支（`tech lead` / `技术负责人` / `techlead` 关键词）。
- `ROLE_AXIS_PROMPTS["techlead"]`：只做需求分析 / 建 DAG / 分配 Engineer / 汇总 Reviewer，明确 "NEVER write implementation code"。
- `executor._run_task` 新增 techlead 分支：`build_turn_prompt` + 分解指令，返回 DAG 计划 JSON（无代码）。
- planner 团队默认属性改为 `techlead`（`planning_engine`），让规划由 TechLead 驱动。

### 4. Teammate Memory 基础层
- `MemoryService.query_teammate_memory(teammate_id, scope=None)`：按 `metadata.teammate_id` + `scope` 过滤。
- scope 三档：`private`（teammate 私有经验）/ `workspace`（workspace 摘要）/ `review`（reviewer 裁决）。
- 写点：
  - engineer 执行记忆 → `scope=private`（memory_event_handler）
  - workspace 完成摘要 → `scope=workspace`
  - reviewer 裁决 → `scope=review`（`_review_relay` 写入，fire-and-forget）

---

## 二、数据流

```
用户 Goal
  │
  ▼
TaskOrchestrator.start_task
  ├─ _plan() → PlanningEngine（techlead 属性驱动）→ DAG（含 deps + selected_teammate_id）
  ├─ _create_steps() → TaskStep[id, deps, teammate_id]  ← deps 持久化
  ▼
TaskExecutor.execute_task（ready-batch）
  ├─ ready = resolver.get_ready_nodes(completed)   ← DAG 并发原语
  ├─ for s in ready: _submit_one → runtime.submit()  （串行，快）
  ├─ asyncio.gather(_wait_parallel)                 （并行 LLM wait，无 DB）
  ├─ for s in ready: _finalize_step → DB 写（串行）  ← AsyncSession 安全
  ├─ completed |= ready
  └─ loop until done
  ▼
review/fix loop（保留）：Reviewer 裁决 → 不通过则 _create_fix_task → 下一波
  ▼
Memory 落库：private / workspace / review（teammate_id 维度隔离）
```

---

## 三、并发测试（backend/tests/test_dag_concurrency_memory.py）

| 用例 | 验证点 | 结果 |
|---|---|---|
| `test_dag_ready_batch_concurrency` | 3 节点（2 根 + 1 依赖），child deps=2，全部 COMPLETED | ✅ |
| `test_parallel_wait_overlap` | 两个独立根：所有 submit 先于任何 wait_start → 证明 gather 并行而非串行 wait | ✅ |
| `test_serial_steps_still_work` | 3 顺序 step 仍 COMPLETED（串行回归） | ✅ |
| `test_techlead_role_detection` | techlead 识别 + engineer fallback | ✅ |
| `test_teammate_memory_scopes` | private/review/workspace 隔离 + teammate_id 不串 | ✅ |

运行：`PYTHONPATH=backend .venv/bin/python -m pytest backend/tests/test_orchestrator_integration.py backend/tests/test_dag_concurrency_memory.py -v`

**踩坑实测**：第一版把 `record_execution`（db.add）放在并发 wait 内 → "Session is already flushing" / UNIQUE 冲突。
修复：并行只放 `runtime.wait`，DB 写全部串行化到 `_finalize_step`。这正是方案 A 的核心取舍。

---

## 四、Memory 设计

```
memory_items (已有表)
  ├─ memory_type: EXECUTION / DECISION / GLOBAL / ...
  └─ metadata(JSON)
       ├─ teammate_id: "<id>"   ← 新增检索维度
       └─ scope: "private" | "workspace" | "review"  ← 新增

query_teammate_memory(teammate_id, scope?)
  → query(limit=2000) 后按 metadata 过滤（SQLite 无 JSON 索引，ponytail 上限 2000；
    超阈值再加 teammate_id 列 + 索引）
```

- 私有经验：`scope=private`，仅该 teammate 可见
- workspace 经验：`scope=workspace`，同 workspace 共享
- review 经验：`scope=review`，reviewer 裁决沉淀，供后续 TechLead/Engineer 参考

---

## 五、与 Helio 差距

| 维度 | 当前 Phase 3 | Helio（参考） | 差距 |
|---|---|---|---|
| 并发模型 | ready-batch + ExecutionRuntime 4-worker | per-teammate 隔离 runtime + 消息总线 | 缺独立 teammate 隔离运行时、事件总线 |
| 角色 | techlead/engineer/reviewer（detect_role 启发式） | 显式 Team 拓扑 + 角色契约 | 缺显式 Team 定义、角色 SLA |
| Memory | teammate_id + scope 三层 | 长期记忆 + 跨任务迁移 + 检索增强 | 缺 Embedding 检索（MemoryService 已有 embedding 字段但未在 query 用）、跨 task 迁移 |
| 编排 | DAG deps + review/fix loop | 可嵌套子 DAG + 动态重规划 | 缺子 DAG 嵌套、运行时重规划 |
| 可观测 | execution_store + trace（已有） | 全链路 span + 成本归因 | 基本对齐，缺 cost 归因到 teammate |

**结论**：Phase 3 已补齐 Helio 的"多 teammate 协作 + DAG 并发 + 角色分工 + 记忆隔离"骨架，
且零新增引擎/调度器/FSM。下一步若要逼近 Helio：① teammate 隔离运行时 ② embedding 检索式 memory ③ 嵌套子 DAG。

---

## 六、未改动（保留）
- ExecutionRuntime / TaskOrchestrator / Runtime Tools 接口不变
- retry / policy / approval / closure / _review_relay 语义不变
- 数据库其余表结构不变（仅 `task_steps` 加 `deps`）
