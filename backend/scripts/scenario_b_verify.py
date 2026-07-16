"""Scenario B end-to-end verification (minimal, real-LLM closure).

Reproduces the EXECUTION layer that automation_v2._execute_job drives:
  - a Task with one Step pre-assigned to teammate TestAI
    (ws=a6d3a8f8, ref=b1f4434c -> the real active key for that workspace)
  - a fresh ExecutionRuntime that is STARTED (the hang fix)
  - TaskExecutor.execute_task drives the step through the runtime
  - the correct workspace key is resolved, the LLM is really called,
    and a meaningful result is produced.

We pre-assign the teammate (skipping the planner's teammate-recommendation
step, which needs teammate.skills populated in test data) so the test pins
exactly the two things under review: the hang fix and the key-scoping fix.

Acceptance (same bar as Scenario A):
  - task reaches COMPLETED
  - step output is non-empty and looks like real LLM text (not an error/timeout)
  - the key used belongs to the teammate's own workspace (no cross-ws borrow)
"""
import asyncio
import sys
import os

# scripts/ lives inside backend/, so add the PROJECT ROOT (parent of backend/)
# to sys.path so that `import backend.xxx` resolves.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

from backend.database import async_session
from backend.models import Teammate
from sqlalchemy import select

from backend.services.task.task_manager import TaskManager
from backend.services.task.task_state import TaskStepStatus
from backend.services.task.task_executor import TaskExecutor
from backend.services.runtime.executor import ExecutionRuntime, _load_teammate
from backend.services.runtime.teammate_runner import resolve_api_key
from backend.services.task.task_orchestrator import TaskStatus


async def main():
    async with async_session() as db:
        tm = (await db.execute(
            select(Teammate).where(Teammate.name == "TestAI")
        )).scalar_one_or_none()
        assert tm, "TestAI teammate not found"
        print(f"[verify] teammate={tm.name} ws={tm.workspace_id[:20]} ref={tm.api_key_ref[:12] if tm.api_key_ref else None}")

        # Resolve key the SAME way task_steps does; assert ws-scoped (no borrow).
        d = await _load_teammate(tm.id)
        api_key, base_url, provider, fallback_model = await resolve_api_key(d)
        assert api_key, "resolve_api_key returned no key"
        print(f"[verify] resolved key len={len(api_key)} provider={provider} fallback={fallback_model is not None}")
        from backend.models import APIKey
        ak = (await db.execute(
            select(APIKey).where(APIKey.id == tm.api_key_ref)
        )).scalar_one_or_none()
        assert ak and ak.workspace_id == tm.workspace_id, "KEY CROSS-WS BORROW DETECTED"
        print("[verify] key workspace matches teammate workspace: OK")

        # Build a real task + one pre-assigned step (bypass planner's
        # teammate-recommendation, which needs teammate.skills in test data).
        mgr = TaskManager()
        task = await mgr.create_task(
            db, title="[Auto][Verify] Scenario B",
            description="用一句话解释什么是 API key，并给出一个 Python 调用 OpenAI 的代码示例。",
            channel_id="", workspace_id=tm.workspace_id,
            intent="verify scenario B",
        )
        await mgr.state.create_step(
            db, task_id=task.id, order=1,
            objective="解释 API key 并给出 Python 调用 OpenAI 的代码示例",
            teammate_id=tm.id,
        )
        # Move task to RUNNING (PENDING -> RUNNING is not a valid transition
        # via the validator; set it directly for this exec-layer test).
        task.status = TaskStatus.RUNNING
        await db.flush()
        await db.commit()
        print(f"[verify] created task {task.id[:12]} ws={task.workspace_id[:20]} status={task.status}")

        # Run through TaskExecutor with a STARTED runtime (the fix).
        runtime = ExecutionRuntime(max_workers=4)
        assert not runtime._started, "runtime should start fresh"
        await runtime.start()
        assert runtime._started and runtime._dispatch_task is not None, "FIX FAILED: runtime not started"
        print("[verify] runtime.start() called — dispatch loop + workers alive")

        executor = TaskExecutor(runtime=runtime)
        result = await executor.execute_task(db, task)
        await db.commit()

        # Reload to inspect real output.
        fresh = await mgr.get_task(db, task.id)
        steps = await mgr.state.list_steps(db, task.id)
        print("\n================ SCENARIO B RESULT ================")
        print(f"task status : {fresh.status}")
        for s in steps:
            print(f"  step {s.order} [{s.status}] teammate={s.teammate_id[:12] if s.teammate_id else '-'}")
            out = (s.output or "").strip()
            print(f"  output chars: {len(out)}")
            print(f"  --- AI OUTPUT (first 1200 chars) ---")
            print(out[:1200])
            print(f"  ---------------------------------------")
        print("==================================================")

        assert fresh.status == "COMPLETED", f"task not COMPLETED: {fresh.status}"
        total_out = sum(len((s.output or "")) for s in steps)
        assert total_out > 50, f"output too small / empty: {total_out} chars"
        joined = " ".join((s.output or "") for s in steps).lower()
        assert "timeout" not in joined and "executionerror" not in joined, "output looks like an error"
        print("\n[verify] ACCEPTANCE PASSED: real key -> real LLM call -> meaningful output")


if __name__ == "__main__":
    asyncio.run(main())
