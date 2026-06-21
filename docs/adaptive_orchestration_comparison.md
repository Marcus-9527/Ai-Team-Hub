# Adaptive Orchestration — Before/After Comparison

## Execution Flow Comparison

### BEFORE (v4 — Always Full FSM)

```
Task → INIT → PLAN → EXECUTE → REVIEW → DONE
         ↓       ↓        ↓         ↓
      planner  executor  reviewer  (always)
      (LLM)    (LLM)     (LLM)

ALL tasks use 3 LLM calls minimum, regardless of complexity.
"What time is it" → planner → executor → reviewer (3 LLM calls)
"Fix this typo"   → planner → executor → reviewer (3 LLM calls)
```

### AFTER (v5 — Adaptive Orchestration)

```
Task → CLASSIFY → Mode Router → Pipeline → DONE
         ↓            ↓
    heuristic    SIMPLE   → executor only           (1 LLM call)
    (0 LLM)      STANDARD → executor + validation   (1 LLM call)
                 COMPLEX  → planner → executor → reviewer (3 LLM calls)

"What time is it" → SIMPLE → executor (1 call)
"Fix this typo"   → SIMPLE → executor (1 call)
"Write a function" → STANDARD → executor + validation (1 call)
"Build full app"  → COMPLEX → planner → executor → reviewer (3 calls)
```

## Cost/Latency Comparison

| Task Type | v4 LLM Calls | v5 LLM Calls | Savings |
|-----------|-------------|-------------|---------|
| Simple (factual) | 3 | 1 | **67%** |
| Standard (code) | 3 | 1 | **67%** |
| Complex (multi-step) | 3 | 3 | 0% |

## Agent Invocation Policy

### BEFORE
```
planner_fn    → ALWAYS called
executor_fn   → ALWAYS called
reviewer_fn   → ALWAYS called
```

### AFTER
```
planner_fn    → ONLY for COMPLEX tasks
executor_fn   → ALWAYS called (all modes need execution)
reviewer_fn   → ONLY for COMPLEX tasks
```

## Transition Table

### BEFORE
```
INIT → PLAN → EXECUTE → REVIEW → DONE
       ↓        ↓         ↓
    FAIL_RETRY (on any failure)
```

### AFTER
```
INIT → CLASSIFY → SIMPLE_EXEC → DONE
                 → STD_EXEC    → DONE
                 → PLAN → EXECUTE → REVIEW → DONE
                          ↓         ↓
                       FAIL_RETRY (mode-aware retry)
```

## New API Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `adaptive` | bool | `true` | Enable adaptive orchestration |
| `force_mode` | string | `null` | Force `SIMPLE`/`STANDARD`/`COMPLEX` |

## Files Changed

| File | Change |
|------|--------|
| `complexity_classifier.py` | **NEW** — zero-LLM-call heuristic classifier |
| `adaptive_router.py` | **NEW** — mode router + adaptive execution pipeline |
| `orchestrator_fsm.py` | **MODIFIED** — v5 adaptive FSM with CLASSIFY state |
| `routes/orchestrator.py` | **MODIFIED** — new API parameters |
