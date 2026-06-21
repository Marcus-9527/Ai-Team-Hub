"""
FSM Execution Flow Diagram
=========================

## State Machine

                    ┌─────────────────────────────────────────┐
                    │                                         │
                    ▼                                         │
    ┌──────┐   ┌──────┐   ┌──────────┐   ┌───────┐   ┌─────┴────┐
    │ INIT │──▶│ PLAN │──▶│ EXECUTE  │──▶│ REVIEW │──▶│   DONE   │
    └──────┘   └──────┘   └──────────┘   └───────┘   └──────────┘
                  │            │              │
                  │            │              │ (fail, retry<max)
                  │            │              └──────┐
                  │            │                     │
                  │            ▼                     │
                  │     ┌────────────┐               │
                  └────▶│ FAIL_RETRY │◀──────────────┘
                        └────────────┘
                               │
                               │ (retry < max)
                               ▼
                          EXECUTE

## Transition Table

| Current    | Next         | Condition                          |
|------------|--------------|------------------------------------|
| INIT       | PLAN         | Always                             |
| PLAN       | EXECUTE      | Plan validation passed             |
| PLAN       | FAIL_RETRY   | Plan validation failed             |
| EXECUTE    | REVIEW       | Execution validation passed        |
| EXECUTE    | FAIL_RETRY   | Execution validation failed        |
| REVIEW     | DONE         | Review passes                      |
| REVIEW     | EXECUTE      | Review fails AND retry_count < max |
| FAIL_RETRY | EXECUTE      | retry_count < max                  |
| FAIL_RETRY | DONE         | retry_count >= max                 |

## Execution Flow (Happy Path)

    User Request
         │
         ▼
    ┌─────────┐
    │  INIT   │  Create FSMContext, classify intent
    └────┬────┘
         │
         ▼
    ┌─────────┐     ┌──────────────┐     ┌───────────────┐
    │  PLAN   │────▶│ planner_fn() │────▶│ Validate Gate │
    └────┬────┘     └──────────────┘     └───────┬───────┘
         │                                        │
         │◀── FAIL_RETRY (if invalid)              │ (valid)
         ▼                                        ▼
    ┌──────────┐     ┌───────────────┐     ┌───────────────┐
    │ EXECUTE  │────▶│ executor_fn() │────▶│ Validate Gate │
    └────┬─────┘     └───────────────┘     └───────┬───────┘
         │                                          │
         │◀── FAIL_RETRY (if invalid)                │ (valid)
         ▼                                          ▼
    ┌──────────┐     ┌───────────────┐     ┌───────────────┐
    │  REVIEW  │────▶│ reviewer_fn() │────▶│ Validate Gate │
    └────┬─────┘     └───────────────┘     └───────┬───────┘
         │                                          │
         │◀── EXECUTE (if fail & retry<max)         │ (pass)
         ▼                                          ▼
    ┌─────────┐
    │  DONE   │  Return FSMContext with final_result
    └─────────┘

## Agent I/O Contract

    planner_fn:
      INPUT:  { task: string }
      OUTPUT: { status: "success"|"error", result: plan_json, reasoning: string }

    executor_fn:
      INPUT:  { plan: dict, original_task: string }
      OUTPUT: { status: "success"|"error", result: execution_output, reasoning: string }

    reviewer_fn:
      INPUT:  { result: string, original_task: string }
      OUTPUT: { status: "success"|"error", result: review_json, reasoning: string }

## Validation Gate Checks

    1. Schema:     status, result, reasoning fields present and correct types
    2. Structural: status ∈ {"success", "error"}
    3. Non-empty:  result.length >= min_length (role-specific) when status=success
    4. Role compliance:
       - planner:  result contains valid plan structure (JSON array or object)
       - executor: result does not start with "Error:"
       - reviewer: result contains pass/fail decision

## Error Handling

    - Tool errors: caught at orchestrator layer, never passed to LLM
    - Agent errors: AgentOutput.status="error", orchestrator triggers FAIL_RETRY
    - Validation failures: orchestrator triggers FAIL_RETRY
    - Max retries exceeded: transition to DONE with error in context.error
"""

# Mermaid diagram for documentation
MERMAID_DIAGRAM = """
```mermaid
stateDiagram-v2
    [*] --> INIT
    INIT --> PLAN: always
    PLAN --> EXECUTE: validation passed
    PLAN --> FAIL_RETRY: validation failed
    EXECUTE --> REVIEW: validation passed
    EXECUTE --> FAIL_RETRY: validation failed
    REVIEW --> DONE: review passes
    REVIEW --> EXECUTE: review fails, retry < max
    FAIL_RETRY --> EXECUTE: retry < max
    FAIL_RETRY --> DONE: retry >= max
    DONE --> [*]

    note right of PLAN: planner_fn(task) → plan JSON
    note right of EXECUTE: executor_fn(plan) → result JSON
    note right of REVIEW: reviewer_fn(result) → validation JSON
    note right of FAIL_RETRY: Error handled at orchestrator layer only
```
"""

# ASCII flow for console output
ASCII_FLOW = """
FSM Orchestrator v3 — Execution Flow
=====================================

  User Request
       │
       ▼
  ┌─────────┐
  │  INIT   │  • Create FSMContext
  └────┬────┘  • Classify intent (deterministic)
       │
       ▼
  ┌─────────┐     ┌──────────────┐
  │  PLAN   │────▶│ planner_fn() │  Pure function: task → plan JSON
  └────┬────┘     └──────┬───────┘
       │                  │
       │           ┌──────▼───────┐
       │           │ Validate Gate │  Schema + non-empty + role compliance
       │           └──────┬───────┘
       │                  │
       │◀── FAIL_RETRY    │ valid
       ▼                  ▼
  ┌──────────┐     ┌───────────────┐
  │ EXECUTE  │────▶│ executor_fn() │  Pure function: plan → result JSON
  └────┬─────┘     └───────┬───────┘
       │                    │
       │             ┌──────▼───────┐
       │             │ Validate Gate │
       │             └──────┬───────┘
       │                    │
       │◀── FAIL_RETRY      │ valid
       ▼                    ▼
  ┌──────────┐     ┌───────────────┐
  │  REVIEW  │────▶│ reviewer_fn() │  Pure function: result → validation JSON
  └────┬─────┘     └───────┬───────┘
       │                    │
       │             ┌──────▼───────┐
       │             │ Validate Gate │
       │             └──────┬───────┘
       │                    │
       │◀── EXECUTE (retry) │ pass
       ▼                    ▼
  ┌─────────┐
  │  DONE   │  Return final_result
  └─────────┘

  Error path (any state):
  ┌────────────┐
  │ FAIL_RETRY │  retry_count < max → EXECUTE
  └─────┬──────┘  retry_count >= max → DONE (with error)
        │
        ▼
    EXECUTE (retry)
"""
