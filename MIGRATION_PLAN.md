"""
Migration Diff Plan: Conversational Orchestration → Deterministic FSM
======================================================================

## Summary

Replace the current conversational multi-agent orchestration with a
deterministic finite-state machine (FSM) execution model.

## What Changes

### NEW FILES (3)

1. backend/services/orchestrator_fsm.py
   - FSMOrchestrator class with deterministic state transitions
   - States: INIT → PLAN → EXECUTE → REVIEW → DONE → FAIL_RETRY
   - Transition table enforced at runtime
   - Only orchestrator controls state transitions
   - Error handling at orchestrator layer only

2. backend/services/agent_functions.py
   - Pure function agents: planner_fn, executor_fn, reviewer_fn
   - Each agent: input JSON → output JSON only
   - No role explanation, no conversation, no meta commentary
   - No agent decides next step

3. backend/services/validation_gate.py
   - Mandatory validation after every agent execution
   - Checks: schema, non-empty, structural, role compliance
   - On failure: triggers FAIL_RETRY (never passes to next state)

### MODIFIED FILES (1)

4. backend/routes/orchestrator.py
   - Replace Orchestrator v2 import with FSMOrchestrator
   - Remove pause/resume/abort endpoints (not needed in FSM)
   - Each run creates fresh FSMOrchestrator (no singleton)
   - Simplified response format

### DEPRECATED FILES (keep for reference, not imported)

5. backend/services/orchestrator_v2.py  → replaced by orchestrator_fsm.py
6. backend/services/agent_runtime.py    → replaced by agent_functions.py
7. backend/services/coordinator.py      → replaced by orchestrator_fsm.py
8. backend/services/dag_engine.py       → replaced by orchestrator_fsm.py
9. backend/services/agent_context.py    → replaced by agent_functions.py
10. backend/services/agent_registry.py  → replaced by agent_functions.py

## Detailed Diff

### orchestrator_v2.py → orchestrator_fsm.py

REMOVED:
- Orchestrator class with _step_init, _step_plan, _step_execute, _step_review, _step_repair
- _build_dag() method (DAG engine replaced by linear FSM)
- _parse_review() method (moved to orchestrator_fsm as _parse_review_pass)
- pause/resume/abort methods (not needed — FSM is synchronous per-run)
- Memory system integration (stateless agents don't need memory)
- Tool gateway integration (stateless agents don't need tools)
- DAGBuilder usage
- AgentRuntime usage
- get_orchestrator() singleton (each run is independent)

ADDED:
- FSMOrchestrator class with explicit TRANSITIONS table
- _transition() with runtime validation of allowed transitions
- _step_plan(), _step_execute(), _step_review() — each returns bool
- FAIL_RETRY state with retry counting
- Validation gate integration after every agent call
- Pure function agent calls (planner_fn, executor_fn, reviewer_fn)

KEPT:
- FSMContext dataclass (simplified from OrchestratorContext)
- TraceEvent dataclass (simplified)
- Trace recording
- Intent classification (_classify_intent)

### agent_runtime.py → agent_functions.py

REMOVED:
- AgentRuntime class (sandbox, memory, tools, retry logic)
- RuntimeConfig dataclass
- _build_context() method (no context building — pure function)
- _call_llm() retry logic (retry is orchestrator's responsibility)
- _parse_output() with fallback to raw text (strict JSON only)
- Memory read/write (stateless)
- Tool gateway integration
- Cache prefix builder integration
- create_agent_runtime() factory

ADDED:
- planner_fn() — pure function
- executor_fn() — pure function
- reviewer_fn() — pure function
- _call_llm() — simple LLM call, errors raised to orchestrator
- _parse_json_output() — strict JSON parse, no fallback to raw text
- AgentOutput dataclass (simplified: status, result, reasoning only)

KEPT:
- OUTPUT_SCHEMA constant
- JSON parsing logic (simplified)

### coordinator.py → orchestrator_fsm.py

REMOVED:
- Coordinator class (routing only, but still conversational)
- _dispatch_agent() with retry logic (orchestrator handles retry)
- _merge_outputs() with confidence scoring (not needed)
- _estimate_confidence() heuristic (not needed)
- _combine_outputs() (not needed)
- AGENT_PROVIDER / AGENT_MODEL config (all agents use same provider now)
- get_coordinator() singleton

ADDED:
- Deterministic routing via FSM states (not agent selection)
- Single provider/model for all agents (simplified)

### dag_engine.py → orchestrator_fsm.py

REMOVED:
- DAGEngine class (topological sort, parallel execution)
- TaskNode dataclass
- TaskResult dataclass
- DAGBuilder class
- _default_executor() (calls AgentRuntime)
- _evaluate_condition() (conditional branching)
- get_execution_report()

ADDED:
- Linear FSM execution (no DAG needed — states define execution order)
- Retry via FAIL_RETRY state (not per-node retry)
- Validation gate between states

### routes/orchestrator.py

REMOVED:
- Import of orchestrator_v2
- Import of OrchestratorState
- _get_orchestrator() singleton factory
- /api/orchestrator/pause endpoint
- /api/orchestrator/resume endpoint
- /api/orchestrator/abort endpoint
- Global _orchestrator_instance

ADDED:
- Import of orchestrator_fsm
- Import of FSMOrchestrator
- Fresh FSMOrchestrator per run (no singleton)
- Simplified response format

KEPT:
- POST /api/orchestrator/run
- GET /api/orchestrator/state
- GET /api/orchestrator/trace/{trace_id}
- _get_api_key() helper

## Migration Steps

1. Deploy new files (orchestrator_fsm.py, agent_functions.py, validation_gate.py)
2. Update routes/orchestrator.py to use FSMOrchestrator
3. Run tests against /api/orchestrator/run
4. Verify FSM state transitions in trace output
5. Verify validation gate catches invalid outputs
6. Verify FAIL_RETRY loop works on errors
7. Remove old files (orchestrator_v2.py, agent_runtime.py, coordinator.py, dag_engine.py)

## Backward Compatibility

BREAKING: API response format changes:
- Removed: plan (nested object), dag_results, turn_count, repair_result
- Added: execution_result, retry_count
- Kept: task_id, trace_id, state, intent, final_result, trace_report

BREAKING: Removed endpoints:
- POST /api/orchestrator/pause
- POST /api/orchestrator/resume
- POST /api/orchestrator/abort

## Testing Checklist

- [ ] FSM transitions: INIT → PLAN → EXECUTE → REVIEW → DONE
- [ ] FSM transitions: PLAN → FAIL_RETRY → EXECUTE (on validation failure)
- [ ] FSM transitions: REVIEW → EXECUTE (on review failure, retry < max)
- [ ] FSM transitions: FAIL_RETRY → DONE (on max retries exceeded)
- [ ] Validation gate: catches empty result
- [ ] Validation gate: catches invalid JSON
- [ ] Validation gate: catches missing fields
- [ ] Validation gate: catches role compliance failures
- [ ] Agent functions: planner_fn returns valid plan JSON
- [ ] Agent functions: executor_fn returns valid result JSON
- [ ] Agent functions: reviewer_fn returns valid review JSON
- [ ] Error handling: tool errors caught at orchestrator layer
- [ ] Error handling: agent errors trigger FAIL_RETRY
- [ ] Trace: all steps recorded with validation results
"""
