# Legacy FSM Final Cleanup Plan

## 审计结论：状态机引用全景

### 搜索统计

| 模式 | 代码引用 | 注释/文档引用 | 备注 |
|------|---------|-------------|------|
| `FSMWorker` | 3 个文件 (maeos.py, test_maeos.py, test_stress.py) | 4 个 docs | 活跃类，需重命名 |
| `FSMContext` | 1 个文件 (maeos.py) | 2 个 docs | 活跃类，需重命名 |
| `FSMOrchestrator` | 0 个文件（已删除） | 4 个 docs/注释 | 已清理 |
| `\bfsm\b` (小写) | 4 个文件 | — | 见下 |
| `max_fsm_transitions` | 1 字段 (orchestrator_routing.py) | — | 无引用，可删 |

### 小写 fsm 在生产代码中的引用

| 文件 | 行 | 内容 | 性质 |
|------|---|------|------|
| `routes/v1_observability.py` | 207 | `if "fsm" in step_lower or "complete" in step_lower` | **纯字符串匹配**。observability 过滤 trace step 名称，非 FSM 逻辑 |
| `collaboration/event_bus.py` | 52 | `source: str  # "user:123", "teammate:strategy", "system:fsm"` | **类型提示注释**。event source 标签枚举值之一 |
| `tests/test_stress.py` | 208 | `tid = await os.submit(f"fsm task {i}")` | 测试数据字符串，非 FSM 逻辑 |
| `sdk/python/client.py` | 232 | `return self._get(f"/v1/fsm-transitions/{task_id}")` | **SDK 死方法**。路由已删除，此调用会 404 |

---

## 可以立即删除

### 1. 备份文件（3 个）

| 文件 | 大小 | 说明 | 风险 |
|------|------|------|------|
| `worker/index.ts.bak` | 85 KB | 旧版本 TypeScript 备用 | 无。`index.ts` 为唯一源 |
| `worker/index.js.bak` | 40 KB | 旧版本 JavaScript 备用 | 无。`index.mjs` 为编译产物 |
| `worker/index.js.archived` | 40 KB | 已归档旧版 | 无。同 .bak |

### 2. `worker/index.mjs` — 旧 FSM 状态机

**目标函数**：`runOrchestrator()` (L960-~L1150)

**生产调用链**：
```
POST /api/orchestrator/run
  → data.adaptive !== false (default: true)
    → true:  runAdaptiveOrchestrator()  ← 默认路径
    → false: runOrchestrator()          ← 旧 FSM 路径
```

**调用者审计**：
- 前端 (`frontend/`): ❌ 无任何 `orchestrator` 或 `adaptive` 引用
- SDK (`sdk/`): ❌ 无 `adaptive` 或 `orchestrator` 引用
- 测试 (`tests/`): ❌ 无引用
- 脚本 (`scripts/`): ❌ `shadow_verify.py` 引用 `orchestrator_fsm` 模块（该模块已删除）

**结论**: `runOrchestrator()` 是死代码。没有任何客户端传 `{"adaptive": false}`。

**删除范围**：
1. `runOrchestrator()` 函数 (L960-~L1150，约为 ~190 行)
2. `POST /api/orchestrator/run` 路由中 `else` 分支 (L1737-1753)
3. `GET /api/orchestrator/state` 路由 (L1760-1762) — 仅返回占位字符串

### 3. `worker/index.ts` — 旧 FSM 状态机

**目标函数**：`runTeamEngine()` (L1105+)

**生产调用链**：
```
POST /api/team/chat
  → data.adaptive !== false (default: true)
    → true:  runAdaptiveTeamEngine()  ← 默认路径
    → false: runTeamEngine()          ← 旧状态机
```

**调用者审计**：同上，无任何客户端传 `adaptive=false`。

**结论**: `runTeamEngine()` 是死代码。

**删除范围**：
1. `runTeamEngine()` 函数 (L1105+)
2. `OrchState`、`OrchContext`、`TraceEvent`、`REVIEW_SCHEMA`、`ReviewResult` 类型声明 (L1059-1103)
3. `POST /api/team/chat` 路由中 `else` 分支 (L1712-1728)
4. `GET /api/team/status` 路由 (L1735-1737) — 占位

### 4. `orchestrator_routing.py` — 废弃字段

**目标**：`GlobalBounds.max_fsm_transitions` (L239)

**引用审计**：无任何代码读或写此字段。纯声明。

### 5. 死 SDK 方法

**目标**：`sdk/python/ai_team_hub/client.py::get_fsm_transitions()` (L230-232)

**说明**：路由 `/v1/fsm-transitions/{task_id}` 已在后端删除。当前调用返回 404。属 SDK 清理范畴。

### 6. 死脚本

**目标**：`scripts/debug/shadow_verify.py`

**说明**：
- L1 注释说比较 FSM vs Coordinator
- L19 `from backend.services.orchestrator_fsm import create_fsm_orchestrator` — **该模块已不存在**
- 脚本已不可运行

### 7. 可清理的注释

| 文件 | 行 | 当前内容 | 建议 |
|------|---|----------|------|
| `backend/services/maeos.py` | 16 | `FSM Kernel (per worker)` | 改为 `Execution Kernel` |
| `backend/services/maeos.py` | 292 | `FSM state snapshots` | 改为 `Execution state snapshots` |
| `backend/services/maeos.py` | 402 | `# FSM Worker` | 改为 `# Worker` |
| `backend/services/maeos.py` | 410 | `- Runs its own FSMOrchestrator instance` | 更新注释 |
| `backend/services/ai_service.py` | 2 | `ai_service.py — LLM Runtime (v5 — FSM-compatible)` | 改为 `v5 — Pipeline-compatible` |
| `backend/services/orchestrator_observability.py` | 4 | `FSM trace recording has been removed` | 已正确，保留 |
| `backend/services/memory_*.py` | 多行 | `not wired into the FSM pipeline` | 改为 `not wired into the pipeline` |
| `backend/services/tool_gateway.py` | 12 | `Tool execution gateway (stub for FSM orchestrator)` | 更新注释 |

---

## 需要重命名

### `maeos.py` — 类重命名（2 个类）

#### `FSMWorker` → `PipelineWorker`

**影响范围**：

| 文件 | 引用量 | 性质 |
|------|--------|------|
| `backend/services/maeos.py` | 7 处 | 定义 + 实例化 + 类型注解 |
| `backend/tests/test_maeos.py` | 4 处 | 导入 + 实例化 |
| `backend/tests/test_stress.py` | 3 处 | 导入 + 实例化 |
| `backend/services/task/task_planner_driver.py` | 1 处 | 仅注释提及 |

**重命名步骤**（未来执行）：
1. `maeos.py`: `class FSMWorker → class PipelineWorker`
2. 同上: `FSMWorker._worker_counter → PipelineWorker._worker_counter`
3. 同上: `self.worker_id = f"worker_{FSMWorker._worker_counter:03d}"` 同步
4. 同上: `self._workers: list[PipelineWorker]`
5. 同上: `worker = PipelineWorker(...)`
6. 同上: `_execute_on_worker(self, worker: PipelineWorker, ...)`
7. `test_maeos.py`: import + 实例化 更新
8. `test_stress.py`: import + 实例化 更新
9. `task_planner_driver.py`: 注释更新

**风险**：低。纯改名，无行为变更。注意 `tests/__init__.py` 确保无额外导入。

#### `FSMContext` → `TaskContext`

**影响范围**：

| 文件 | 引用量 | 性质 |
|------|--------|------|
| `backend/services/maeos.py` | 4 处 | 定义 + 类型注解 + 实例化 |

**重命名步骤**：
1. `maeos.py`: `class FSMContext → class TaskContext`
2. 同上: `Task.__init__` 中 `context: Optional[TaskContext]`
3. 同上: `ctx = TaskContext(...)`
4. 同上: docstring 更新

**风险**：极低。仅在 `maeos.py` 内部使用。

---

## 必须保留

| 代码 | 理由 |
|------|------|
| `TaskStateManager.transition_step_status()`<br>`TaskStateManager.transition_task_status()` | **业务状态机**。Task/Step 生命周期核心逻辑。不是 FSM 编排遗留 |
| `pipeline.py` / `run_pipeline()` | LLM 编排引擎，活跃路由和 Worker 调用 |
| `rag_pipeline.py` | RAG 文档处理管道 |
| `orchestrator_routing.py`（除 max_fsm_transitions） | 模型路由、预算控制、熔断器、复杂度分类 |
| `orchestrator_diversity.py` | 认知多样性检测 |
| `orchestrator_prompts.py` | Prompt 模板 |
| `orchestrator_observability.py` | 请求日志 |
| `worker/index.mjs` `runAdaptiveOrchestrator()` | 自适应编排，活跃默认路径 |
| `worker/index.ts` `runAdaptiveTeamEngine()` | 自适应编排，活跃默认路径 |
| `MAEOS` / `PriorityTaskQueue` / `ExecutionMemory` | MAEOS 核心运行时 |
| `FSMWorker` (maeos.py) — 类本身 | 代码活跃，仅需重命名 |

---

## 分阶段执行方案

### Phase A — 安全删除（无风险，立即执行）

```
1.  删除 worker/index.ts.bak
2.  删除 worker/index.js.bak
3.  删除 worker/index.js.archived
4.  删除 orchestrator_routing.py:239  max_fsm_transitions: int = 10
5.  （可选）删除 scripts/debug/shadow_verify.py
6.  （可选）删除 SDK client.get_fsm_transitions()
```

**验证**：`pytest backend/tests/` 全绿。

### Phase B — 删除 Worker 旧 FSM 函数（需确认无外部调用）

```
1.  worker/index.mjs:
    - 删除 runOrchestrator() 函数
    - 删除 POST /api/orchestrator/run 路由的 else 分支（legacy FSM）
    - 删除 GET /api/orchestrator/state 路由

2.  worker/index.ts:
    - 删除 runTeamEngine() 函数
    - 删除 OrchState / OrchContext / TraceEvent / REVIEW_SCHEMA 等类型
    - 删除 POST /api/team/chat 路由的 else 分支
    - 删除 GET /api/team/status 路由
```

**验证**：部署 Worker 后，测试 `/api/team/chat` 默认行为正常（`adaptive=true` 为默认）。

### Phase C — 重命名（不影响功能，可在迭代中执行）

```
1.  maeos.py: FSMContext → TaskContext
2.  maeos.py: FSMWorker → PipelineWorker
3.  同步更新 test_maeos.py、test_stress.py
4.  同步更新注释
```

**验证**：`pytest backend/tests/` 全绿。

### Phase D — 文档与注释清理（低优先级，可随迭代清理）

```
清理 docs/ 中 FSM 历史引用，逐步替换为当前架构描述。
```

---

## 附录：引用完整清单

### 可删除项引用

| 目标 | 声明位置 | 调用位置 |
|------|---------|---------|
| `runOrchestrator()` | `worker/index.mjs:960` | `index.mjs:1739`（else 分支） |
| `runTeamEngine()` | `worker/index.ts:1105` | `index.ts:1714`（else 分支） |
| `max_fsm_transitions` | `orchestrator_routing.py:239` | **无引用** |
| `get_fsm_transitions()` | `sdk/python/client.py:230` | **路由已删除** |
| `shadow_verify.py` | `scripts/debug/` | **导入模块已不存在** |

### 需重命名项引用

| 目标 | 文件 | 行号 | 引用次数 |
|------|------|------|---------|
| `FSMWorker` | `maeos.py` | 405, 426, 427, 563, 582, 770 | 6 次 |
| `FSMWorker` | `test_maeos.py` | 22, 368, 371, 400, 427 | 5 次 |
| `FSMWorker` | `test_stress.py` | 24, 589, 684 | 3 次 |
| `FSMWorker` | `task_planner_driver.py` | 64 | 1 次（注释） |
| `FSMContext` | `maeos.py` | 65, 66, 146, 476 | 4 次 |

### 必须保留项引用

| 目标 | 文件 | 原因 |
|------|------|------|
| `TaskStateManager.transition_step_status` | `task_state.py` | 业务状态机 |
| `run_pipeline()` | `pipeline.py` | LLM 编排引擎 |
| `runAdaptiveTeamEngine()` | `worker/index.ts:933` | 默认编排路径 |
| `runAdaptiveOrchestrator()` | `worker/index.mjs:804` | 默认编排路径 |
| `orchestrator_diversity.py` | `backend/services/` | 多样性检测 |
| `orchestrator_routing.py`（主体） | `backend/services/` | 路由/预算/熔断 |
| `orchestrator_observability.py` | `backend/services/` | 请求日志 |
| `orchestrator_prompts.py` | `backend/services/` | 对话 Prompt |
