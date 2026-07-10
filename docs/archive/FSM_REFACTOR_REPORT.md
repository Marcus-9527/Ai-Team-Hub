# FSM 遗留代码审计报告

**审计范围**: `/home/liunx/workspace/ai-team-hub`
**审计时间**: 2026-07-08
**审计目标**: 确认旧 FSM（Finite State Machine）编排是否还存在

---

## 搜索关键字覆盖

| 关键字 | 匹配文件数 | 说明 |
|--------|-----------|------|
| `FSM` / `StateMachine` | ~15 个文件 | 部分为注释/文档引用 |
| `Orchestrator` | ~6 个文件 | 部分为纯工具类/路由名 |
| `Pipeline` | ~8 个文件 | 两种含义：LLM Pipeline / RAG Pipeline |
| `Worker` | ~60 次匹配 | 含 Cloudflare Workers 平台引用 |

---

## 详细审计清单

### 1. Backend Python — 需要保留

#### `backend/services/maeos.py`

| 项目 | 详情 |
|------|------|
| **类** | `FSMContext` (L65), `FSMWorker` (L405) |
| **调用链** | `MAEOS._scheduler_loop()` → 分配 Task 给 `FSMWorker.execute()` → `run_pipeline()` |
| **当前作用** | **核心运行时**。MAEOS 的 Worker 池 + 任务队列 + 执行引擎 |
| **是否废弃** | ❌ 否，**活跃**。`FSMWorker.execute()` 内联调 `run_pipeline()`，已替换旧 `FSMOrchestrator` |
| **FSM 残留** | 类名 `FSMContext` / `FSMWorker` 是历史命名残留（docstring + 注释），内部已无 FSM 逻辑 |
| **删除建议** | ⛔ 保留代码（核心运行时）。建议重命名：`FSMWorker` → `Worker` / `PipelineWorker`，`FSMContext` → `TaskContext` |

#### `backend/services/pipeline.py`

| 项目 | 详情 |
|------|------|
| **类** | `run_pipeline()` 函数 |
| **调用链** | `FSMWorker.execute()` → `run_pipeline()`；`routes/v1.py` → `run_pipeline()` |
| **当前作用** | **LLM 编排引擎**。三步串行：planner → executor → reviewer |
| **是否废弃** | ❌ 否，**活跃** |
| **FSM 残留** | 无。文件头部明确标注 "no FSM state machine" |
| **删除建议** | ⛔ 保留 |

#### `backend/services/rag_pipeline.py`

| 项目 | 详情 |
|------|------|
| **类** | `RAGPipeline` |
| **调用链** | 路由 / 直接调用 |
| **当前作用** | RAG 文档处理管道（chunking → embedding → D1 存储） |
| **是否废弃** | ❌ 否，**活跃** |
| **FSM 残留** | 无。`Pipeline` 指文档处理流程，非 FSM |
| **删除建议** | ⛔ 保留 |

#### `backend/services/orchestrator_routing.py`

| 项目 | 详情 |
|------|------|
| **类** | `ModelRouter`, `ExecutionBudget`, `CircuitBreaker`, `ComplexityClassifier` |
| **当前作用** | 模型路由、预算控制、熔断器、复杂度分类 |
| **是否废弃** | ❌ 否，**活跃** |
| **FSM 残留** | 类名 `GlobalBounds.max_fsm_transitions` 字段 (L239) — 已无实际作用 |
| **删除建议** | ⛔ 保留代码。`max_fsm_transitions` 字段可删除（无引用） |

#### `backend/services/orchestrator_diversity.py`

| 项目 | 详情 |
|------|------|
| **类** | `DiversityReport`, `analyze_diversity()` |
| **当前作用** | 认知多样性检测（防同一化） |
| **是否废弃** | ❌ 否，**活跃**，被 `maeos.py` 导入 |
| **删除建议** | ⛔ 保留 |

#### `backend/services/orchestrator_prompts.py`

| 项目 | 详情 |
|------|------|
| **类** | 纯 prompt 常量 |
| **当前作用** | `SYSTEM_PROMPT`, `PLANNER_PROMPT`, `REVIEWER_PROMPT` |
| **是否废弃** | ❌ 否，**活跃**，被 `pipeline.py` 导入 |
| **删除建议** | ⛔ 保留 |

#### `backend/services/orchestrator_observability.py`

| 项目 | 详情 |
|------|------|
| **类** | `Observability` (request logging) |
| **当前作用** | 基础请求日志 |
| **是否废弃** | ❌ 否，**活跃**，被 `maeos.py` 导入 |
| **FSM 残留** | 文件头部注释 "FSM trace recording has been removed" |
| **删除建议** | ⛔ 保留 |

---

### 2. Worker JavaScript/TypeScript — 可删除

#### `worker/index.mjs` — `runOrchestrator()` (L960-~1150)

| 项目 | 详情 |
|------|------|
| **类型** | 旧 FSM 编排函数 |
| **调用链** | `POST /api/orchestrator/run` 路由 → `adaptive=false` 分支 → `runOrchestrator()` |
| **当前作用** | v2 legacy 全量 FSM 状态机：INIT → PLAN → EXECUTE (DAG) → REVIEW |
| **是否废弃** | ⚠️ **半废弃**。仅在客户端显式传 `adaptive=false` 时走，默认走 `runAdaptiveOrchestrator()` |
| **删除建议** | ✅ **建议删除**整个 `runOrchestrator()` 函数 + 路由的 `else` 分支。删除后只需确认无客户端传 `adaptive=false` 即可 |

#### `worker/index.ts` — `runTeamEngine()` (L1105+)

| 项目 | 详情 |
|------|------|
| **类型** | 旧 FSM 状态机（TypeScript 源码） |
| **调用链** | `POST /api/team/chat` → `adaptive=false` → `runTeamEngine()` |
| **状态机** | `INIT → PLAN → EXECUTE → REVIEW → REPAIR → DONE | FAILED` |
| **是否废弃** | ⚠️ **半废弃**。同上，仅 `adaptive=false` 时走 |
| **删除建议** | ✅ **建议删除** `runTeamEngine()` 函数 + 路由的 `else` 分支。`runAdaptiveTeamEngine()` 是默认路径且覆盖所有模式 |

#### `worker/index.ts` — `runAdaptiveTeamEngine()` (L933)

| 项目 | 详情 |
|------|------|
| **类型** | 自适应编排（默认路径） |
| **模式** | SIMPLE: 仅 executor / STANDARD: executor + validation / COMPLEX: plan → execute → review |
| **是否废弃** | ❌ 否，**活跃** |
| **FSM 残留** | 虽然是状态驱动（CLASSIFY → PLAN → EXEC → REVIEW → DONE），但这是自适应编排的正常流程，**不是旧 FSM 遗留** |
| **删除建议** | ⛔ 保留 |

#### `worker/index.mjs` — `runAdaptiveOrchestrator()` (L804)

| 项目 | 详情 |
|------|------|
| **类型** | 自适应编排（编译产物的默认路径） |
| **是否废弃** | ❌ 否，**活跃** |
| **删除建议** | ⛔ 保留 |

---

### 3. Worker 备份文件 — 可删除

| 文件 | 大小 | 说明 | 删除建议 |
|------|------|------|----------|
| `worker/index.ts.bak` | 85KB | 旧版本 TypeScript 备份，含完整 `runOrchestrator` | ✅ 可删除 |
| `worker/index.js.bak` | 40KB | 旧版本 JavaScript 备份，含完整 `runOrchestrator` | ✅ 可删除 |
| `worker/index.js.archived` | 40KB | 已归档旧版本，内容同 .bak | ✅ 可删除 |

---

### 4. 已有 Route — `/api/orchestrator/state`

| 项目 | 详情 |
|------|------|
| **位置** | `worker/index.mjs` L1760 |
| **内容** | 仅返回 `{ state: 'idle', message: 'Orchestrator is stateless on Workers.' }` |
| **是否废弃** | 无实际功能，仅占位 |
| **删除建议** | ✅ 可删除（如果无前端依赖） |

---

### 5. 测试文件

#### `backend/tests/test_maeos.py` — `TestFSMWorker` 类

| 项目 | 详情 |
|------|------|
| **作用** | 测试 `FSMWorker.execute()` 的行为（mocked LLM） |
| **是否废弃** | ❌ 否，代码仍活跃 |
| **删除建议** | ⛔ 保留。如果重命名 `FSMWorker`，同步修改 |

#### `backend/tests/test_stress.py`

| 项目 | 详情 |
|------|------|
| **作用** | 并发压力/状态机完整性测试 |
| **是否废弃** | ❌ 否 |
| **FSM 残留** | 测试名称和注释使用 "FSM" 描述状态序列 |
| **删除建议** | ⛔ 保留 |

---

### 6. 文档注释 — 仅文字引用

以下文件包含 FSM 的历史引用，**可清理注释但无代码影响**：
- `docs/PUBLIC_API_SPEC.md` — API 文档描述 FSM trace
- `docs/ARCHITECTURE.md` — 架构图含 FSM
- `docs/V2.5_TASK_EXECUTION_ARCHITECTURE.md` — 历史架构描述
- `docs/V2.6_*` 系列文档 — Phase 设计文档含 FSM 引用
- `V2.4_ARCHITECTURE_FINAL_REPORT.md` — 已确认旧 FSM 删除的总结文档
- `backend/services/memory_*.py` — 注释 "not wired into the FSM pipeline"
- `backend/services/ai_service.py` — 文件头 "FSM-compatible"
- `backend/services/task/task_planner_driver.py` — 提及 FSMWorker system_prompt

---

### 7. 状态机 — 必须保留

#### Task/Step 状态转换 (`backend/services/task/task_state.py`)

| 项目 | 详情 |
|------|------|
| **类** | `TaskStateManager` — `transition_step_status()`, `transition_task_status()` |
| **作用** | **产品核心逻辑**。验证状态转换合法性（如 PENDING→RUNNING→COMPLETED/FAILED） |
| **是否废弃** | ❌ 否，**活跃** |
| **说明** | 这是业务状态机（Task/Step 生命周期），**不是"旧 FSM 编排"**。必须保留 |

---

## 总结

### 可以直接删除的

| 文件/函数 | 原因 | 影响 |
|-----------|------|------|
| `worker/index.mjs` 中 `runOrchestrator()` (L960-~1150) | 旧 FSM 状态机，仅 `adaptive=false` 时走 | 删除后需确认无客户端传 `adaptive=false` |
| `worker/index.ts` 中 `runTeamEngine()` (L1105+) | 同上，TypeScript 源码 | 同上 |
| `worker/index.ts.bak` | 旧备份 | 无影响 |
| `worker/index.js.bak` | 旧备份 | 无影响 |
| `worker/index.js.archived` | 旧备份 | 无影响 |
| `orchestrator_routing.py` `GlobalBounds.max_fsm_transitions` 字段 | 已无引用 | 极小 |

### 可重命名（降低认知负担）

| 当前名称 | 建议名称 | 理由 |
|----------|----------|------|
| `FSMWorker` (maeos.py) | `Worker` / `PipelineWorker` | 内部已无 FSM 逻辑，调 `run_pipeline()` |
| `FSMContext` (maeos.py) | `TaskContext` / `ExecutionContext` | 纯数据容器，非 FSM |

### 必须保留（不是 FSM 遗留）

| 代码 | 理由 |
|------|------|
| `TaskStateManager.transition_step_status()` / `transition_task_status()` | Task/Step 业务生命周期，产品核心 |
| `pipeline.py` / `run_pipeline()` | LLM 编排引擎，活跃 |
| `rag_pipeline.py` | RAG 文档处理管道 |
| `orchestrator_routing.py` (除 max_fsm_transitions) | 模型路由、预算、熔断器 |
| `orchestrator_diversity.py` | 认知多样性检测 |
| `orchestrator_prompts.py` | Prompt 模板 |
| `orchestrator_observability.py` | 请求日志 |
| `worker/index.mjs` `runAdaptiveOrchestrator()` | 自适应编排，默认路径 |
| `worker/index.ts` `runAdaptiveTeamEngine()` | 自适应编排，默认路径 |

### 当前 FSM 残留文件数统计

| 分类 | 文件数 | 代码行数估算 |
|------|--------|-------------|
| **可直接删除** | 1 个函数（分处 .mjs + .ts）+ 3 个备份文件 | ~200 行 |
| **可重命名** | 2 个类（FSMWorker, FSMContext） | ~120 行 |
| **可清理字段** | `GlobalBounds.max_fsm_transitions` | 1 行 |
| **文档注释引用** | ~12 个文件 | 仅注释 |

**结论**: 旧 `FSMOrchestrator` 核心已在 Phase 2 删除。剩余 FSM 遗留主要是命名残留和备份文件，无隐蔽的 FSM 编排逻辑在生产路径上运行。
