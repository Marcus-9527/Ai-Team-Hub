"""QA-2 repro: create task + run background orchestration, capture break point."""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="%(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

sys.path.insert(0, "/home/liunx/workspace/ai-team-hub/backend")

from backend.database import init_db, async_session
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_orchestrator import TaskOrchestrator
from backend.services.runtime.executor import ExecutionRuntime
from backend.models import (
    TaskModel, TaskStatus, TaskStepModel, TaskPlanModel,
    DAGDefinitionModel, DAGNodeModel, ExecutionRecordModel, ArtifactModel,
)


async def main():
    await init_db()
    async with async_session() as db:
        mgr = TaskManager()
        task = await mgr.create_task(
            db, title="电商网站", intent="设计一个电商网站", created_by="qa",
        )
        await db.commit()
        task_id = task.id
        print(f"\n=== CREATED TASK {task_id} status={task.status}")

        try:
            orch = TaskOrchestrator(runtime=ExecutionRuntime(max_workers=4))
            import backend.services.runtime.executor as rex
            _orig_wait = rex.ExecutionRuntime.wait
            async def _fast_wait(self, task_id, timeout=300.0):
                return await _orig_wait(self, task_id, timeout=8.0)
            rex.ExecutionRuntime.wait = _fast_wait
            _orig_run = rex.ExecutionRuntime._run_task
            async def _traced_run(self, worker, task):
                print(f"[TRACE] _run_task START {task.id}", flush=True)
                try:
                    return await _orig_run(self, worker, task)
                finally:
                    print(f"[TRACE] _run_task END {task.id} status={task.status}", flush=True)
            rex.ExecutionRuntime._run_task = _traced_run
            await orch.start_task(db, task_id, "设计一个电商网站")
            await db.commit()
        except Exception as e:
            print(f"\n!!! start_task raised: {type(e).__name__}: {e}")

        # verify DB state
        await db.commit()
        task = await mgr.get_task(db, task_id)
        print(f"\n=== FINAL TASK status={task.status} error={getattr(task,'error','')}")

        res = await db.execute(__import__("sqlalchemy").select(DAGDefinitionModel).where(DAGDefinitionModel.id.like(f"%{task_id[:8]}%")))
        dags = res.scalars().all()
        for d in dags:
            nodes = (await db.execute(__import__("sqlalchemy").select(DAGNodeModel).where(DAGNodeModel.dag_id == d.id))).scalars().all()
            print(f"  DAG {d.id}: {len(nodes)} nodes")
            for n in nodes:
                print(f"    node {n.id}: desc={n.description!r} sel_team={n.selected_teammate_id!r}")

        steps = await mgr.state.list_steps(db, task_id)
        print(f"  STEPS: {len(steps)}")
        execs = (await db.execute(__import__("sqlalchemy").select(ExecutionRecordModel).where(ExecutionRecordModel.task_id == task_id))).scalars().all()
        print(f"  EXEC RECORDS: {len(execs)}")
        arts = (await db.execute(__import__("sqlalchemy").select(ArtifactModel).where(ArtifactModel.task_id == task_id))).scalars().all()
        print(f"  ARTIFACTS: {len(arts)}")


asyncio.run(main())
