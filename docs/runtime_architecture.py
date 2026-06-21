"""
runtime/architecture.py — Runtime Architecture Diagram + Migration Diff

## Production Runtime Architecture (v4)

    ┌─────────────────────────────────────────────────────────────────┐
    │                        API Layer                                 │
    │  POST /api/orchestrator/run                                     │
    └──────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                   FSM Orchestrator (v4)                          │
    │                                                                  │
    │  States: INIT → PLAN → EXECUTE → REVIEW → DONE                 │
    │          (FAIL_RETRY on errors)                                  │
    │                                                                  │
    │  Responsibilities:                                               │
    │  - State transitions (only orchestrator controls)                │
    │  - Context isolation before dispatch                             │
    │  - Flow control enforcement after execution                     │
    │  - Validation gate after execution                               │
    │  - NEVER calls agents directly                                   │
    └──────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                      Scheduler                                   │
    │                                                                  │
    │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
    │  │  Exec Queue   │  │  Semaphore   │  │  Concurrency Control │  │
    │  │  (FIFO)       │  │  (max=N)     │  │  (asyncio)           │  │
    │  └──────────────┘  └──────────────┘  └──────────────────────┘  │
    │                                                                  │
    │  submit() → execute() → execute_with_retry()                     │
    └───────┬──────────────────────────────────────────────────────────┘
            │
            │  execute_with_retry()
            │  ┌─────────────────────────────┐
            ├──│      Retry Policy Engine     │
            │  │                              │
            │  │  Failure Classification:     │
            │  │  • VALIDATION_FAIL → retry   │
            │  │  • LOGIC_FAIL → fallback     │
            │  │  • SYSTEM_FAIL → abort       │
            │  │                              │
            │  │  Backoff Strategies:         │
            │  │  • fixed                      │
            │  │  • linear (base * attempt)    │
            │  │  • exponential (base * 2^n)   │
            │  └─────────────────────────────┘
            │
            ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                   Agent Functions (Pure)                         │
    │                                                                  │
    │  ┌──────────┐    ┌──────────┐    ┌──────────┐                  │
    │  │ planner  │    │ executor │    │ reviewer │                  │
    │  │ _fn()    │    │ _fn()    │    │ _fn()    │                  │
    │  └──────────┘    └──────────┘    └──────────┘                  │
    │                                                                  │
    │  Input: isolated context (minimal)                               │
    │  Output: AgentOutput {status, result, reasoning}                 │
    └──────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────────┐
    │                Cross-Cutting Concerns                            │
    │                                                                  │
    │  ┌──────────────────┐  ┌──────────────────┐                    │
    │  │ Context Isolation │  │ Flow Control     │                    │
    │  │ (Anti-Leak)       │  │ Enforcer         │                    │
    │  │                    │  │                    │                    │
    │  │ • Contract-based   │  │ • Pattern match  │                    │
    │  │ • Deep copy        │  │ • Strict mode    │                    │
    │  │ • Frozen output    │  │ • Reject/allow   │                    │
    │  └──────────────────┘  └──────────────────┘                    │
    │                                                                  │
    │  ┌──────────────────┐  ┌──────────────────┐                    │
    │  │ Validation Gate   │  │ Trace Logger     │                    │
    │  │                    │  │ (Observability)  │                    │
    │  │ • Schema check     │  │                    │                    │
    │  │ • Non-empty check  │  │ • JSON lines     │                    │
    │  │ • Role compliance  │  │ • State trans.   │                    │
    │  │ • Structural       │  │ • I/O snapshots  │                    │
    │  └──────────────────┘  │  • Retry tracking │                    │
    │                          └──────────────────┘                    │
    └──────────────────────────────────────────────────────────────────┘

## Execution Flow (Happy Path)

    Request
      │
      ▼
    INIT ──→ Create FSMContext + TraceLogger
      │
      ▼
    PLAN ──→ ContextIsolation.isolate("planner", {task})
      │     → Scheduler.submit(planner_fn, kwargs)
      │     → Scheduler.execute_with_retry(unit, retry_policy)
      │     → FlowControlEnforcer.check(output)
      │     → ValidationGate.validate(output, "planner")
      │     → ContextIsolation.validate_no_leak(output)
      │     → TraceLogger.log_*()
      │
      ▼
    EXECUTE → ContextIsolation.isolate("executor", {plan, original_task})
      │     → Scheduler.submit(executor_fn, kwargs)
      │     → Scheduler.execute_with_retry(unit, retry_policy)
      │     → FlowControlEnforcer.check(output)
      │     → ValidationGate.validate(output, "executor")
      │     → TraceLogger.log_*()
      │
      ▼
    REVIEW → ContextIsolation.isolate("reviewer", {result, original_task})
      │     → Scheduler.submit(reviewer_fn, kwargs)
      │     → Scheduler.execute_with_retry(unit, retry_policy)
      │     → FlowControlEnforcer.check(output)
      │     → ValidationGate.validate(output, "reviewer")
      │     → Parse review decision (pass/fail)
      │     → TraceLogger.log_*()
      │
      ▼
    DONE ──→ TraceLogger.log_workflow_complete()
      │     → Return FSMContext
      ▼
    Response

## Error Flow (Any Step)

    Step Fails
      │
      ├─→ Scheduler.execute_with_retry()
      │     │
      │     ├─→ RetryPolicy.classify(error)
      │     │     ├─ VALIDATION_FAIL → RETRY (same agent)
      │     │     ├─ LOGIC_FAIL → FALLBACK (different approach)
      │     │     └─ SYSTEM_FAIL → ABORT (infrastructure error)
      │     │
      │     ├─→ RetryPolicy.decide() → delay computed by backoff
      │     │
      │     └─→ Sleep(delay) → Retry execute()
      │
      ├─→ Max retries exhausted → FAIL_RETRY state
      │
      └─→ Orchestrator decides: retry EXECUTE or DONE with error

## Migration Diff: v3 (FSM) → v4 (Production Runtime)

### REMOVED from orchestrator:
  - Direct agent function calls (planner_fn, executor_fn, reviewer_fn)
  - Inline retry logic (while loop + sleep)
  - Simple TraceEvent dataclass (replaced by TraceLogger)
  - Pause/resume/abort (not needed — each run is independent)

### ADDED to orchestrator:
  - Scheduler integration (all execution via scheduler)
  - RetryPolicy integration (failure classification + backoff)
  - TraceLogger integration (structured JSON observations)
  - ContextIsolation integration (anti-leak)
  - FlowControlEnforcer integration (hard rules)
  - Per-step flow control checks
  - Per-step context leak validation

### NEW modules:
  + runtime/scheduler.py        — Execution queue, dispatch, concurrency
  + runtime/retry_policy.py    — Failure classification + backoff
  + runtime/trace.py           — Structured JSON trace logging
  + runtime/context_isolation.py — Anti-leak context isolation
  + runtime/flow_control.py    — Flow control hard rules
  + runtime/__init__.py        — Package exports

### KEPT unchanged:
  ~ agent_functions.py         — Pure function agents (unchanged)
  ~ validation_gate.py         — Validation gate (unchanged)
  ~ routes/orchestrator.py     — Route handler (orchestrator_fsm import unchanged)

### Configuration changes:
  + max_concurrency (default 1)
  + backoff_strategy (fixed/linear/exponential)
  + base_delay_ms (default 1000)
  + flow_control_mode (strict/log)
"""

MERMAID_DIAGRAM = """
```mermaid
flowchart TD
    A[API Request] --> B[FSM Orchestrator v4]
    B --> C{State}
    
    C -->|INIT| D[Create Context + Trace]
    D --> E[PLAN]
    
    E --> F[ContextIsolation.isolate]
    F --> G[Scheduler.submit planner_fn]
    G --> H[Scheduler.execute_with_retry]
    H --> I{RetryPolicy}
    I -->|SUCCESS| J[FlowControlEnforcer.check]
    I -->|FAILED| K{Retry?}
    K -->|yes| H
    K -->|no| L[FAIL_RETRY]
    
    J --> M[ValidationGate.validate]
    M --> N[ContextIsolation.validate_no_leak]
    N --> O[TraceLogger.log]
    O --> P[EXECUTE]
    
    P --> F2[ContextIsolation.isolate]
    F2 --> G2[Scheduler.submit executor_fn]
    G2 --> H2[Scheduler.execute_with_retry]
    H2 --> I2{RetryPolicy}
    I2 -->|SUCCESS| J2[FlowControlEnforcer.check]
    J2 --> M2[ValidationGate.validate]
    M2 --> O2[TraceLogger.log]
    O2 --> Q[REVIEW]
    
    Q --> F3[ContextIsolation.isolate]
    F3 --> G3[Scheduler.submit reviewer_fn]
    G3 --> H3[Scheduler.execute_with_retry]
    H3 --> I3{RetryPolicy}
    I3 -->|SUCCESS| J3[FlowControlEnforcer.check]
    J3 --> M3[ValidationGate.validate]
    M3 --> R{Review Pass?}
    R -->|yes| S[DONE]
    R -->|no, retry<max| P
    R -->|no, max retries| S
    
    S --> T[TraceLogger.build_report]
    T --> U[API Response]
    
    L --> V{Retry Count}
    V -->|< max| P
    V -->|>= max| S
    
    style B fill:#000,color:#fff,stroke:#fc1c46
    style S fill:#000,color:#fff,stroke:#fc1c46
    style I fill:#fc1c46,color:#fff
    style K fill:#fc1c46,color:#fff
    style R fill:#fc1c46,color:#fff
```
"""
