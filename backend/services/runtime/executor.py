"""
runtime/executor.py — Unified Execution Runtime (v3.1)

Single entry point for all AI execution:
  - Task mode:  execute()      → pipeline.run_pipeline()
  - Chat mode:  stream_execute() → TeammateRunner streaming
  - Status:     get_status()
  - Observability: execution_store (token/cost tracking + SSE)

Every execute/submit generates an execution_id tracked in ExecutionStore
with start/end time, status, token_usage, cost, and SSE event stream.
"""
import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from typing import AsyncGenerator, Optional

from backend.services.pipeline import run_pipeline
from backend.services.runtime.retry_policy import RetryPolicy, BackoffStrategy
from backend.services.runtime.trace import TraceLogger
from backend.services.runtime.execution_store import (
    ExecutionStore,
    get_execution_store,
    get_sse_broadcaster,
    estimate_cost_from_tokens,
)
from backend.services.evaluation import EvaluationService
from backend.services.runtime.teammate_runner import (
    resolve_api_key,
    build_turn_prompt,
    detect_role,
)
from backend.services.runtime.agent import run_engineer_workflow
from backend.services.runtime.reviewer import run_reviewer_workflow
from backend.services.runtime.tool_runtime import workspace_root
from backend.services.runtime.runtime_context import TeammateRuntimeContext

logger = logging.getLogger("runtime.executor")

# ── Auto-evaluation (Phase 6) ──

_eval_service = EvaluationService()


# ── Teammate identity loader ──

async def _load_teammate(teammate_id: str) -> Optional[dict]:
    """Load a teammate as a plain dict (same shape the chat path uses)."""
    if not teammate_id:
        return None
    try:
        from backend.database import async_session
        from sqlalchemy import select
        from backend.models import Teammate
        async with async_session() as sess:
            res = await sess.execute(select(Teammate).where(Teammate.id == teammate_id))
            obj = res.scalar_one_or_none()
            if obj is None:
                return None
            d = obj.to_dict()
            # Build chat-path shape (subsets of fields used by resolve_api_key/build_turn_prompt).
            d.setdefault("model_provider", obj.model_provider)
            d.setdefault("model_name", obj.model_name)
            d.setdefault("api_key_ref", obj.api_key_ref)
            d.setdefault("system_prompt", obj.system_prompt)
            d.setdefault("role", obj.role)
            d.setdefault("name", obj.name)
            d.setdefault("id", obj.id)
            return d
    except Exception as e:
        logger.warning(f"[Runtime] teammate load failed for {teammate_id}: {e}")
        return None


def _anon_workspace(teammate_id: str) -> str:
    """Fallback workspace id when a task carries none."""
    return f"anon_{teammate_id}" if teammate_id else "anon_default"


def _auto_evaluate(execution_id: str, execution) -> None:
    """Fire-and-forget evaluation after execution completes/fails."""
    try:
        import asyncio
        asyncio.ensure_future(_eval_service.evaluate(execution_id, execution.to_dict()))
    except Exception:
        logger.debug("[EVAL] auto-evaluation skipped (non-fatal)")


# ── Execution Status ──

class ExecStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class TaskPriority:
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


# ── Runtime Task ──

class RuntimeTask:
    """A task submitted to the ExecutionRuntime."""
    def __init__(self, description: str, priority: int = TaskPriority.NORMAL,
                 provider: str = "openrouter", model: str = "openrouter/auto",
                 api_key: str = "", base_url: str = None,
                 intent: str = "", teammate: str = "", workspace_id: str = "",
                 git_commit: str = ""):
        self.id = f"exec_{uuid.uuid4().hex[:12]}"
        self.description = description
        self.priority = priority
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.intent = intent
        self.teammate = teammate or ""
        self.workspace_id = workspace_id or ""
        self.git_commit = git_commit
        self.review_status = "pending"  # pending | approved | rejected
        self.status = ExecStatus.PENDING
        self.result = ""
        self.error = ""
        self.created_at = time.time()
        self.started_at = 0.0
        self.completed_at = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description[:200],
            "priority": self.priority,
            "status": self.status,
            "result_length": len(self.result),
            "error": self.error[:200] if self.error else "",
            "created_at": self.created_at,
        }


# ── Priority Queue ──

class _PriorityQueue:
    """Priority-ordered task queue (FIFO within same priority)."""
    def __init__(self):
        self._queues: dict[int, list[RuntimeTask]] = defaultdict(list)
        self._task_map: dict[str, RuntimeTask] = {}
        self._total = 0

    def push(self, task: RuntimeTask) -> None:
        self._queues[task.priority].append(task)
        self._task_map[task.id] = task
        self._total += 1

    def pop(self) -> Optional[RuntimeTask]:
        for priority in sorted(self._queues.keys()):
            if self._queues[priority]:
                task = self._queues[priority].pop(0)
                self._total -= 1
                return task
        return None

    def get(self, task_id: str) -> Optional[RuntimeTask]:
        return self._task_map.get(task_id)

    @property
    def is_empty(self) -> bool:
        return self._total == 0

    @property
    def total(self) -> int:
        return self._total


# ── ExecutionRuntime ──

class ExecutionRuntime:
    """
    Unified execution runtime.

    Task mode:
        task = await runtime.execute(description="...", ...)

    Chat mode (SSE):
        async for chunk in runtime.stream_execute(...): yield chunk

    Status:
        status = runtime.get_status(task_id)
    """

    def __init__(self, max_workers: int = 4,
                 provider: str = "openrouter",
                 model: str = "openrouter/auto",
                 api_key: str = "", base_url: str = None):
        self.max_workers = max_workers
        self.default_provider = provider
        self.default_model = model
        self.default_api_key = api_key
        self.default_base_url = base_url

        self._queue = _PriorityQueue()
        self._completed_events: dict[str, asyncio.Event] = {}
        self._started = False
        self._shutdown = False
        self._dispatch_task: Optional[asyncio.Task] = None

        # Worker pool
        self._workers: list[dict] = []  # each is {"id": str, "busy": bool}

        # Observability
        self._execution_store = get_execution_store()
        self._broadcaster = get_sse_broadcaster()

    async def start(self) -> None:
        """Start dispatch loop."""
        if self._started:
            return
        self._workers = [
            {"id": f"worker_{i:03d}", "busy": False}
            for i in range(self.max_workers)
        ]
        self._started = True
        self._shutdown = False
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info(f"[Runtime] started, {len(self._workers)} workers ready")

    async def shutdown(self) -> None:
        self._shutdown = True
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        self._started = False

    # ── Public API ──

    async def execute(
        self,
        description: str,
        priority: int = TaskPriority.NORMAL,
        intent: str = "",
        provider: str = None,
        model: str = None,
        api_key: str = None,
        base_url: str = None,
        teammate: str = None,
        workspace_id: str = None,
        git_commit: str = "",
        wait: bool = False,
    ) -> RuntimeTask:
        """
        Execute a task synchronously (non-streaming).

        If wait=True, blocks until complete.
        Returns the RuntimeTask (with result filled if wait=True).
        """
        task = RuntimeTask(
            description=description,
            priority=priority,
            provider=provider or self.default_provider,
            model=model or self.default_model,
            api_key=api_key or self.default_api_key,
            base_url=base_url or self.default_base_url,
            intent=intent,
            teammate=teammate or "",
            workspace_id=workspace_id or "",
            git_commit=git_commit,
        )

        if not self._started:
            await self.start()

        event = asyncio.Event()
        self._completed_events[task.id] = event
        self._queue.push(task)

        if wait:
            await event.wait()
            self._completed_events.pop(task.id, None)

        return task

    async def submit(
        self,
        description: str,
        priority: int = TaskPriority.NORMAL,
        intent: str = "",
        provider: str = None,
        model: str = None,
        api_key: str = None,
        teammate: str = None,
        workspace_id: str = None,
        git_commit: str = "",
        wait: bool = False,
    ) -> str:
        """
        Submit a task and return its ID immediately (non-blocking).

        Like execute(), but always returns immediately with the task_id.
        Call wait(task_id) to block on completion.

        Returns task_id string.
        """
        task = await self.execute(
            description=description,
            priority=priority,
            intent=intent,
            provider=provider or self.default_provider,
            model=model or self.default_model,
            api_key=api_key or self.default_api_key,
            base_url=self.default_base_url,
            teammate=teammate or "",
            workspace_id=workspace_id or "",
            git_commit=git_commit,
            wait=False,
        )
        if wait:
            event = self._completed_events.get(task.id)
            if event:
                await event.wait()
                self._completed_events.pop(task.id, None)
        return task.id

    async def wait(self, task_id: str, timeout: float = 300.0) -> Optional[RuntimeTask]:
        """
        Wait for a submitted task to complete.

        Returns the completed RuntimeTask, or None on timeout.
        """
        event = self._completed_events.get(task_id)
        if not event:
            task = self._queue.get(task_id)
            if task and task.status in (
                ExecStatus.COMPLETED, ExecStatus.FAILED, ExecStatus.ABORTED
            ):
                return task
            return None

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"[Runtime] wait timeout for task {task_id}")
            return None

        self._completed_events.pop(task_id, None)
        return self._queue.get(task_id)

    async def stream_execute(
        self,
        user_message: str,
        system_prompt: str = None,
        provider: str = None,
        model: str = None,
        api_key: str = None,
        base_url: str = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming execution — wraps pipeline run with SSE output.

        Yields SSE-formatted chunks for real-time display.
        """
        from backend.services.team_collaboration import _run_single_teammate
        raise NotImplementedError(
            "stream_execute is for chat-mode. Use TeammateRunner directly."
        )

    def get_status(self, task_id: str) -> Optional[dict]:
        """Get execution status."""
        task = self._queue.get(task_id)
        if task:
            return task.to_dict()
        return None

    async def get_execution(self, execution_id: str) -> Optional[dict]:
        """
        Get full execution record (from observability store).

        Returns the full ExecutionRecord.to_dict() including:
          - token_usage, cost_micro_usd, events timeline
        """
        rec = await self._execution_store.aget(execution_id)
        if rec:
            return rec.to_dict()
        return None

    def list_executions(
        self,
        status: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """List execution records."""
        return [
            r.to_summary()
            for r in self._execution_store.list(status=status, limit=limit, offset=offset)
        ]

    # ── Execution Loop ──

    async def _dispatch_loop(self) -> None:
        """Continuously dispatch queued tasks to workers."""
        while not self._shutdown:
            try:
                available = [w for w in self._workers if not w["busy"]]
                if available and not self._queue.is_empty:
                    task = self._queue.pop()
                    if task:
                        worker = available[0]
                        worker["busy"] = True
                        asyncio.create_task(self._run_task(worker, task))

                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Runtime] dispatch error: {e}")
                await asyncio.sleep(1.0)

    async def _run_task(self, worker: dict, task: RuntimeTask) -> None:
        """Run a single task and signal completion — with observability tracking."""
        execution = self._execution_store.create(
            execution_id=task.id,
            task_id=task.id,
            teammate=task.teammate or "",
            model=task.model,
        )
        execution.set_running()

        await self._broadcaster.publish(
            task.id, "runtime_start",
            {"task_id": task.id, "description": task.description[:100]},
        )

        try:
            task.status = ExecStatus.RUNNING
            task.started_at = time.time()

            teammate_id = task.teammate

            # Phase 19: mark teammate WORKING on task start
            if teammate_id:
                from backend.services.autonomous.teammate_state import get_state_manager as _get_sm
                asyncio.ensure_future(_get_sm().set_working(teammate_id, task.id))

            # Load real teammate identity so task execution == chat identity.
            teammate = await _load_teammate(teammate_id) if teammate_id else None

            # Inject Brain context into teammate identity (one source of truth).
            if teammate:
                from backend.services.brain.brain_loader import get_brain_loader
                # ponytail: pass task.description as semantic query for relevant memory
                brain = await get_brain_loader().build_prompt(
                    teammate.get("id", ""),
                    query=task.description or "",
                )
                if brain:
                    teammate["system_prompt"] = brain + "\n\n" + (teammate.get("system_prompt", "") or "")

            # Build unified TeammateRuntimeContext from loaded identity.
            ws_id = task.workspace_id or (
                workspace_root(_anon_workspace(teammate_id))
                if teammate_id else ""
            )
            ctx = TeammateRuntimeContext()
            if teammate is not None:
                api_key, base_url = await resolve_api_key(teammate)
                ctx = TeammateRuntimeContext.from_teammate(
                    teammate,
                    workspace_id=ws_id,
                    api_key=api_key or task.api_key,
                    base_url=base_url or task.base_url,
                )

            if ctx.is_loaded and detect_role(teammate) == "engineer":
                # Real digital-employee loop: tools, workspace, structured output.
                output = await run_engineer_workflow(
                    teammate=teammate,
                    task_description=task.description,
                    workspace_id=ctx.workspace_id,
                    api_key=ctx.api_key,
                    base_url=ctx.base_url,
                    provider=ctx.model_provider or task.provider,
                    model=ctx.model_name or task.model,
                )
                try:
                    result = json.dumps(output, ensure_ascii=False)
                except Exception:
                    result = str(output)
                model_used = ctx.model_name or task.model
            elif ctx.is_loaded and detect_role(teammate) == "reviewer":
                # Reviewer: reads the Engineer's real git diff + runs tests.
                # Same execution chain — no second pipeline.
                review = await run_reviewer_workflow(
                    teammate=teammate,
                    task_description=task.description,
                    workspace_id=ctx.workspace_id,
                    git_commit=task.git_commit or "",
                    api_key=ctx.api_key,
                    base_url=ctx.base_url,
                    provider=ctx.model_provider or task.provider,
                    model=ctx.model_name or task.model,
                )
                task.review_status = "approved" if review["verdict"] == "approve" else "rejected"
                try:
                    result = json.dumps(review, ensure_ascii=False)
                except Exception:
                    result = str(review)
                model_used = ctx.model_name or task.model
            elif ctx.is_loaded and detect_role(teammate) == "techlead":
                # TechLead: decomposes the goal into a DAG plan. Never implements.
                # Reuses build_turn_prompt (techlead axis) + one LLM call — same chain.
                system_prompt = build_turn_prompt(
                    teammate, task.description, [], 0
                ) + (
                    "\n\nYou are coordinating. Decompose the goal into a DAG plan. "
                    "Reply ONLY with JSON: {\"analysis\": str, "
                    "\"nodes\": [{\"objective\": str, \"assign_role\": str, "
                    "\"depends_on\": [int]}], \"summary\": str}. "
                    "Do NOT write implementation code."
                )
                provider = ctx.model_provider or task.provider
                model_used = ctx.model_name or task.model
                result = await run_pipeline(
                    channel_id=task.id,
                    user_message=task.description,
                    system_prompt=system_prompt,
                    provider=provider,
                    model=model_used,
                    api_key=ctx.api_key or task.api_key,
                    base_url=ctx.base_url or task.base_url,
                )
            else:
                # Non-engineer or generic task: chat-path prompt (no identity loss).
                if ctx.is_loaded:
                    system_prompt = build_turn_prompt(
                        teammate, task.description, [], 0
                    )
                    api_key = ctx.api_key
                    base_url = ctx.base_url
                    provider = ctx.model_provider or task.provider
                    model_used = ctx.model_name or task.model
                else:
                    api_key, base_url = task.api_key, task.base_url
                    system_prompt = "You are a helpful AI assistant."
                    provider, model_used = task.provider, task.model

                result = await run_pipeline(
                    channel_id=task.id,
                    user_message=task.description,
                    system_prompt=system_prompt,
                    provider=provider,
                    model=model_used,
                    api_key=api_key,
                    base_url=base_url,
                )

            task.result = result
            task.status = ExecStatus.COMPLETED

            # Estimate tokens from output length (fallback when no API returns token counts)
            prompt_tokens = max(1, len(task.description) // 4)
            completion_tokens = max(1, len(result) // 4)

            execution.set_completed(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

            # Auto-evaluation (Phase 6)
            _auto_evaluate(task.id, execution)

            # Phase 19: mark teammate IDLE on completion
            if teammate_id:
                asyncio.ensure_future(_get_sm().set_idle(teammate_id))

            await self._broadcaster.publish(
                task.id, "runtime_complete",
                {
                    "status": "COMPLETED",
                    "duration_ms": execution.duration_ms,
                    "total_tokens": execution.total_tokens,
                    "cost_micro_usd": execution.cost_micro_usd,
                },
            )

        except Exception as e:
            task.status = ExecStatus.FAILED
            task.error = f"{type(e).__name__}: {e}"
            execution.set_failed(str(e))
            _auto_evaluate(task.id, execution)
            logger.error(f"[Runtime] task {task.id} failed: {e}")

            # Phase 19: mark teammate OFFLINE on failure
            if teammate_id:
                from backend.services.autonomous.teammate_state import get_state_manager as _get_sm_fail
                asyncio.ensure_future(_get_sm_fail().set_offline(teammate_id))

            await self._broadcaster.publish(
                task.id, "runtime_complete",
                {
                    "status": "FAILED",
                    "error": str(e)[:200],
                    "duration_ms": execution.duration_ms,
                },
            )

        task.completed_at = time.time()
        worker["busy"] = False

        event = self._completed_events.get(task.id)
        if event:
            event.set()

    # ── Stats ──

    async def stats(self) -> dict:
        """Get aggregate execution statistics (async)."""
        base = await self._execution_store.astats()
        base.update({
            "started": self._started,
            "total_workers": len(self._workers),
            "busy_workers": sum(1 for w in self._workers if w["busy"]),
            "queue_size": self._queue.total,
        })
        return base
