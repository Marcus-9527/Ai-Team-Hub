# MAEOS — Multi-Agent Execution Operating System

## Architecture Design Document

---

## 1. System Overview

MAEOS 是一个多 Agent 执行操作系统，将 FSM 状态机 + Anti-Role-Drift 内核升级为完整执行 OS，包含调度器、工作池、执行记忆层。

**核心流水线：**

```
Task → Scheduler → Worker → FSM Kernel → Agents → Validation → Memory Store
```

---

## 2. Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                         MAEOS Kernel                             │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Priority Task Queue                      │ │
│  │  ┌────────┐ ┌───────┐ ┌────────┐ ┌─────┐ ┌───────────┐   │ │
│  │  │CRITICAL│→│ HIGH  │→│NORMAL  │→│ LOW │→│BACKGROUND │   │ │
│  │  └────────┘ └───────┘ └────────┘ └─────┘ └───────────┘   │ │
│  └─────────────────────────┬───────────────────────────────────┘ │
│                            │                                     │
│                            ▼                                     │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Scheduler Loop                           │ │
│  │  • pop highest priority task                                │ │
│  │  • find available worker                                    │ │
│  │  • assign task → asyncio.create_task                        │ │
│  └─────────────────────────┬───────────────────────────────────┘ │
│                            │                                     │
│              ┌─────────────┼─────────────┐                       │
│              ▼             ▼             ▼                       │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────┐ │
│  │  Worker 001  │ │  Worker 002  │ │  Worker 003  │ │Worker04│ │
│  │ ┌──────────┐ │ │ ┌──────────┐ │ │ ┌──────────┐ │ │        │ │
│  │ │FSM Orch  │ │ │ │FSM Orch  │ │ │ │FSM Orch  │ │ │  ...   │ │
│  │ │Scheduler │ │ │ │Scheduler │ │ │ │Scheduler │ │ │        │ │
│  │ │RetryPol  │ │ │ │RetryPol  │ │ │ │RetryPol  │ │ │        │ │
│  │ │CtxIsol   │ │ │ │CtxIsol   │ │ │ │CtxIsol   │ │ │        │ │
│  │ │FlowCtrl  │ │ │ │FlowCtrl  │ │ │ │FlowCtrl  │ │ │        │ │
│  │ └──────────┘ │ │ └──────────┘ │ │ └──────────┘ │ │        │ │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └───┬────┘ │
│         │                │                │              │      │
│         └────────────────┴────────────────┴──────────────┘      │
│                            │                                     │
│                            ▼                                     │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                  Execution Memory Layer                     │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │ │
│  │  │FSM State │ │Agent     │ │Validation│ │Retry History │  │ │
│  │  │Snapshots │ │Outputs   │ │Logs      │ │              │  │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │ │
│  │  • Replay support   • Debug endpoints   • Eviction policy  │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────┐
│                  Anti-Role-Drift Kernel (ENFORCED)               │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐  │
│  │ Context Isolation│  │ Flow Control     │  │Diversity Check│  │
│  │ • Per-agent      │  │ • No next_action │  │ • Jaccard     │  │
│  │   input contract │  │ • No handoff     │  │ • Structure   │  │
│  │ • Frozen (deep   │  │ • No state       │  │ • Anti-       │  │
│  │   copy)          │  │   manipulation   │  │   consensus   │  │
│  │ • Strip secrets  │  │ • Regex patterns │  │ • Penalty     │  │
│  └──────────────────┘  └──────────────────┘  └───────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. FSM Kernel (Per Worker)

每个 Worker 运行独立的 FSM 状态机实例：

```
INIT → CLASSIFY ──┬── SIMPLE_EXEC ────────────────────────→ DONE
                  ├── STD_EXEC ───────────────────────────→ DONE
                  └── PLAN → EXECUTE → REVIEW → DIVERSITY_CHECK → DONE
                                ↑          │           │
                                └──────────┘           │
                                   (retry)         (homogenization
                                                    → re-execute)
```

**状态说明：**

| State | 功能 | LLM调用 |
|-------|------|---------|
| INIT | 创建上下文 | 0 |
| CLASSIFY | 任务复杂度分类 | 0 (规则) |
| SIMPLE_EXEC | 单 executor | 1 |
| STD_EXEC | executor + validation | 1 |
| PLAN | planner agent | 1 |
| EXECUTE | executor agent | 1 |
| REVIEW | reviewer agent (对抗性) | 1 |
| DIVERSITY_CHECK | 同质化检测 | 0 |
| FAIL_RETRY | 重试决策 | 0 |

---

## 4. Scheduler Layer

### 4.1 Priority Task Queue

5 级优先级（0-4），同优先级 FIFO：

```python
class TaskPriority(int, Enum):
    CRITICAL = 0    # 系统级紧急
    HIGH = 1        # 用户高优先级
    NORMAL = 2      # 默认
    LOW = 3         # 批量/后台
    BACKGROUND = 4  # 清理/统计
```

### 4.2 Scheduler Loop

```python
while not shutdown:
    available = [w for w in workers if not w.is_busy]
    if available and not queue.is_empty:
        task = queue.pop()          # 最高优先级
        worker = available[0]       # 第一个空闲 worker
        asyncio.create_task(execute_on_worker(worker, task))
    await asyncio.sleep(0.05)
```

### 4.3 Retry Queue

内置于 Scheduler — 失败任务通过 RetryPolicy 决策：
- `VALIDATION_FAIL` → retry same agent
- `LOGIC_FAIL` → fallback (change approach)
- `SYSTEM_FAIL` → abort workflow

---

## 5. Worker Pool Model

### 5.1 Worker 设计

```python
class FSMWorker:
    worker_id: str              # worker_001, worker_002, ...
    scheduler: Scheduler        # per-worker 执行调度
    retry_policy: RetryPolicy   # per-worker 重试策略
    context_isolation: ContextIsolation  # per-worker 上下文隔离
    flow_control: FlowControlEnforcer    # per-worker 流控
    _running: Optional[Task]    # 当前任务
```

### 5.2 并发模型

- 每个 Worker 同时只执行 1 个任务
- N 个 Worker 可同时执行 N 个任务
- 使用 asyncio 协程，无需线程锁
- Worker 调度器内含 Semaphore 控制并发

### 5.3 任务生命周期

```
PENDING → SCHEDULED → RUNNING → COMPLETED/FAILED/ABORTED
                ↑                    │
                └──── RETRYING ──────┘
```

---

## 6. Execution Memory Schema

### 6.1 存储结构

```json
{
  "task_id": "task_abc123",
  "description": "Design auth system",
  "priority": 1,
  "status": "COMPLETED",
  "intent": "complex",
  "worker_id": "worker_002",

  "result": "...",
  "error": "",

  "context": {
    "task_id": "ddfad3df",
    "user_input": "Design auth system",
    "complexity": "COMPLEX",
    "execution_mode": "COMPLEX",
    "state": "DONE",
    "plan": {...},
    "execution_result": {...},
    "review_result": {...},
    "final_result": "...",
    "diversity_report": {...},
    "retry_count": 0,
    "llm_calls": 3,
    "skipped_stages": []
  },

  "trace_report": {
    "trace_id": "05bb4b7d",
    "total_events": 21,
    "events": [
      {"event_type": "STATE_TRANSITION", "data": {...}},
      {"event_type": "AGENT_DISPATCH", "data": {...}},
      {"event_type": "AGENT_RESULT", "data": {...}},
      ...
    ]
  },

  "timing": {
    "created_at": 1782467127.3,
    "scheduled_at": 1782467127.4,
    "started_at": 1782467127.5,
    "completed_at": 1782467130.2,
    "wait_time": 0.2,
    "execution_time": 2.7,
    "total_latency": 2.9
  },

  "retry_count": 0,
  "saved_at": 1782467130.3
}
```

### 6.2 Memory Operations

| Operation | Method | 用途 |
|-----------|--------|------|
| Save | `memory.save(task)` | 执行完成后保存 |
| Load | `memory.load(task_id)` | 按ID查询 |
| Replay | `memory.replay(task_id)` | 调试回放（含元数据） |
| Filter | `memory.load_by_status(status)` | 按状态过滤 |
| Stats | `memory.stats()` | 内存统计 |
| Evict | LRU (max_entries=1000) | 自动淘汰 |

---

## 7. Anti-Role-Drift Isolation

### 7.1 Context Isolation（上下文隔离）

| Agent | 接收字段 | 隔离效果 |
|-------|---------|---------|
| Planner | `task` only | 不知道实现细节 |
| Executor | `plan` + `original_task` | 不知道分解逻辑 |
| Reviewer | `result` + `original_task` | 不知道规划过程 |

- Deep copy 防止 mutation
- Frozen dataclass 不可变
- Strip 敏感字段 (api_key, password, token)

### 7.2 Flow Control（流控硬规则）

禁止的 Agent 输出模式：
- `next_action` / `next_step` → 拒绝
- `handoff_to` / `delegate_to` → 拒绝
- `set_state` / `update_state` → 拒绝
- Prompt-based flow control → 拒绝

### 7.3 Cognitive Diversity（认知多样性）

- Planner: 逆向工程思维
- Executor: 测试驱动思维
- Reviewer: 红队对抗思维（假设输出有错）
- Jaccard 相似度 > 0.75 → HOMOGENIZATION_ERROR
- 最多 2 次多样性重试

---

## 8. API Endpoints

| Endpoint | Method | 功能 |
|----------|--------|------|
| `/api/maeos/submit` | POST | 提交任务 |
| `/api/maeos/status/{id}` | GET | 任务状态 |
| `/api/maeos/debug/{id}` | GET | 完整调试信息 |
| `/api/maeos/tasks` | GET | 任务列表 |
| `/api/maeos/stats` | GET | 系统统计 |
| `/api/maeos/memory/stats` | GET | 内存统计 |
| `/api/maeos/wait/{id}` | GET | 阻塞等待完成 |

---

## 9. Test Coverage

| Suite | Tests | Status |
|-------|-------|--------|
| PriorityTaskQueue | 8 | ✅ |
| ExecutionMemory | 6 | ✅ |
| Scheduler | 4 | ✅ |
| ContextIsolation | 5 | ✅ |
| FlowControl | 5 | ✅ |
| FSMWorker | 2 | ✅ |
| MAEOSKernel | 5 | ✅ |
| **Total** | **35** | **35/35 passed** |

---

## 10. File Structure

```
backend/
├── services/
│   ├── maeos.py                    # MAEOS Kernel + PriorityTaskQueue + ExecutionMemory + FSMWorker
│   ├── orchestrator_fsm.py         # FSM State Machine (v6 — Cognitive Diversity)
│   ├── agent_functions.py          # Agent Functions (planner/executor/reviewer)
│   ├── cognitive_diversity.py      # Diversity Analysis + Homogenization Detection
│   ├── validation_gate.py          # Output Validation
│   ├── adaptive_router.py          # Execution Mode Router
│   ├── complexity_classifier.py    # Task Complexity Classification
│   └── runtime/
│       ├── __init__.py             # Package exports
│       ├── scheduler.py            # Execution Scheduler
│       ├── retry_policy.py         # Retry + Failure Policy
│       ├── trace.py                # Execution Trace (Observability)
│       ├── context_isolation.py    # Anti-Leak Context Isolation
│       └── flow_control.py         # Flow Control Hard Rules
├── routes/
│   └── maeos.py                    # MAEOS API Routes
└── tests/
    └── test_maeos.py               # 35 Unit + Integration Tests
```
