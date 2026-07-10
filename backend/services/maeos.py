"""
maeos.py — Multi-Agent Execution Operating System (MAEOS)

Full execution operating system for multi-teammate team pipelines.

Architecture:
  ┌─────────────────────────────────────────────────────────�
  │                    MAEOS Kernel                          │
  │  ┌──────────┐  ┌──────────┐  ┌────────────────────�    │
  │  │ Task Queue│  │Worker Pool│  │ Execution Memory   │    │
  │  │(priority) │→ │(N workers)│→ │ (persist/replay)   │    │
  │  └──────────┘  └──────────┘  └────────────────────�    │
  │       ↓              ↓              ↓                    │
  │  �──────────────────────────────────────────────┐       │
  │  │           FSM Kernel (per worker)             │       │
  │  │  INIT → CLASSIFY → PLAN → EXEC → REVIEW → DONE│      │
  │  └──────────────────────────────────────────────┘       │
  │       ↓                                                  │
  │  ┌──────────────────────────────────────────────�       │
  │  │     Agent Functions (isolated, pure)          │       │
  │  │  planner_fn / executor_fn / reviewer_fn       │       │
  │  └──────────────────────────────────────────────┘       │
  │       ↓                                                  │
  │  ┌──────────────────────────────────────────────┐       │
  │  │     Validation Gate + Diversity Check         │       │
  │  └──────────────────────────────────────────────┘       │
  └─────────────────────────────────────────────────────────�

Usage:
    os = MAEOS(max_workers=4)
    task_id = await os.submit("Design auth system", priority=TaskPriority.HIGH)
    result = await os.wait(task_id)
    os.shutdown()
"""

import asyncio
import time
import uuid
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, Any, Callable, Awaitable
from enum import Enum
from collections import defaultdict

from backend.services.orchestrator_diversity import analyze_diversity, DiversityReport
from backend.services.orchestrator_observability import get_observability
from backend.services.pipeline import run_pipeline
from backend.services.runtime import (
    Scheduler,
    RetryPolicy,
    TraceLogger,
    ContextIsolation,
    FlowControlEnforcer,
    BackoffStrategy,
)

logger = logging.getLogger("maeos")


# ═══════════════════════════════════════════════════════════
# In-memory data classes (formerly in orchestrator_core.py)
# ═══════════════════════════════════════════════════════════

class FSMContext:
    """Simple execution context — replaces old FSMContext stub."""
    def __init__(self, task_id: str = "", intent: str = "", plan: str = "",
                 execution_result: str = "", review_result: str = "",
                 final_result: str = "", error: str = "", retry_count: int = 0,
                 state: str = "", diversity_report: dict = None):
        self.task_id = task_id
        self.intent = intent
        self.plan = plan
        self.execution_result = execution_result
        self.review_result = review_result
        self.final_result = final_result or execution_result
        self.error = error
        self.retry_count = retry_count
        self.state = state
        self.diversity_report = diversity_report or {}

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "intent": self.intent,
            "plan": self.plan,
            "execution_result": self.execution_result,
            "review_result": self.review_result,
            "final_result": self.final_result,
            "error": self.error,
            "retry_count": self.retry_count,
            "state": self.state,
        }


class AgentOutput:
    """Simple agent output — replaces old AgentOutput stub."""
    def __init__(self, teammate_id: str = "", result: str = "",
                 status: str = "success", reasoning: str = "",
                 confidence: float = 0.0, metadata: dict = None):
        self.teammate_id = teammate_id
        self.result = result
        self.status = status
        self.reasoning = reasoning
        self.confidence = confidence
        self.metadata = metadata or {}


# ═══════════════════════════════════════════════════════════
# Task Model
# ═══════════════════════════════════════════════════════════

class TaskPriority(int, Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    ABORTED = "ABORTED"


@dataclass
class Task:
    """A unit of work submitted to MAEOS."""
    id: str
    description: str
    priority: int = TaskPriority.NORMAL
    status: str = TaskStatus.PENDING
    intent: str = ""
    provider: str = "openrouter"
    model: str = "openrouter/auto"
    api_key: str = ""
    base_url: str = None
    
    # Runtime fields
    worker_id: Optional[str] = None
    context: Optional[FSMContext] = None
    trace_report: dict = field(default_factory=dict)
    diversity_report: dict = field(default_factory=dict)
    result: str = ""
    error: str = ""
    
    # Timing
    created_at: float = 0.0
    scheduled_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    
    # Retry tracking
    retry_count: int = 0
    max_retries: int = 3
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
    
    @property
    def wait_time(self) -> float:
        """Time spent waiting in queue."""
        if self.started_at and self.created_at:
            return self.started_at - self.created_at
        return 0.0
    
    @property
    def execution_time(self) -> float:
        """Time spent executing."""
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return 0.0
    
    @property
    def total_latency(self) -> float:
        """Total time from submit to complete."""
        if self.completed_at and self.created_at:
            return self.completed_at - self.created_at
        return 0.0
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description[:200],
            "priority": self.priority,
            "status": self.status,
            "worker_id": self.worker_id,
            "result_length": len(self.result),
            "error": self.error[:200],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "total_latency": self.total_latency,
            "retry_count": self.retry_count,
            "diversity_score": self.diversity_report.get("overall_diversity_score"),
        }


# ═══════════════════════════════════════════════════════════
# Priority Task Queue
# ═══════════════════════════════════════════════════════════

class PriorityTaskQueue:
    """
    Priority-ordered task queue with FIFO within same priority.
    
    Uses a dict of lists keyed by priority level.
    Tasks are dequeued in priority order (CRITICAL first).
    """
    
    def __init__(self):
        self._queues: dict[int, list[Task]] = defaultdict(list)
        self._task_map: dict[str, Task] = {}
        self._total = 0
    
    def push(self, task: Task) -> None:
        """Add task to queue. Lower priority number = higher priority."""
        self._queues[task.priority].append(task)
        self._task_map[task.id] = task
        self._total += 1
        logger.debug(f"[QUEUE] push task {task.id} priority={task.priority} total={self._total}")
    
    def pop(self) -> Optional[Task]:
        """Get highest priority task (FIFO within same priority)."""
        for priority in sorted(self._queues.keys()):
            if self._queues[priority]:
                task = self._queues[priority].pop(0)
                self._total -= 1
                logger.debug(f"[QUEUE] pop task {task.id} priority={priority} remaining={self._total}")
                return task
        return None
    
    def peek(self) -> Optional[Task]:
        """Look at next task without removing."""
        for priority in sorted(self._queues.keys()):
            if self._queues[priority]:
                return self._queues[priority][0]
        return None
    
    def remove(self, task_id: str) -> bool:
        """Remove a task by ID."""
        if task_id in self._task_map:
            task = self._task_map[task_id]
            self._queues[task.priority] = [
                t for t in self._queues[task.priority] if t.id != task_id
            ]
            del self._task_map[task_id]
            self._total -= 1
            return True
        return False
    
    def get(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        return self._task_map.get(task_id)
    
    @property
    def is_empty(self) -> bool:
        return self._total == 0
    
    @property
    def total(self) -> int:
        return self._total
    
    def count_by_status(self, status: str) -> int:
        """Count tasks with given status."""
        return sum(
            1 for t in self._task_map.values() if t.status == status
        )
    
    def list_all(self) -> list[Task]:
        """List all tasks in priority order."""
        result = []
        for priority in sorted(self._queues.keys()):
            result.extend(self._queues[priority])
        return result


# ═══════════════════════════════════════════════════════════
# Execution Memory Layer
# ═══════════════════════════════════════════════════════════

class ExecutionMemory:
    """
    Persistent execution state storage.
    
    Stores:
      - FSM state snapshots
      - Teammate outputs (per teammate)
      - Validation logs
      - Retry history
      - Diversity reports
    
    Supports replay and debug.
    """
    
    def __init__(self, max_entries: int = 1000):
        self._store: dict[str, dict] = {}
        self._order: list[str] = []
        self._max = max_entries
    
    def save(self, task: Task) -> str:
        """
        Save full task execution state.
        Returns the task_id.
        """
        state = {
            "task_id": task.id,
            "description": task.description,
            "priority": task.priority,
            "status": task.status,
            "intent": task.intent,
            "worker_id": task.worker_id,
            "result": task.result,
            "error": task.error,
            "context": task.context.to_dict() if task.context else {},
            "trace_report": task.trace_report,
            "diversity_report": task.diversity_report,
            "timing": {
                "created_at": task.created_at,
                "scheduled_at": task.scheduled_at,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "wait_time": task.wait_time,
                "execution_time": task.execution_time,
                "total_latency": task.total_latency,
            },
            "retry_count": task.retry_count,
            "saved_at": time.time(),
        }
        
        self._store[task.id] = state
        self._order.append(task.id)
        
        # Evict oldest if over limit
        if len(self._order) > self._max:
            oldest = self._order.pop(0)
            self._store.pop(oldest, None)
        
        logger.debug(f"[MEMORY] saved task {task.id} total={len(self._store)}")
        return task.id
    
    def load(self, task_id: str) -> Optional[dict]:
        """Load execution state by task ID."""
        return self._store.get(task_id)
    
    def load_all(self) -> list[dict]:
        """Load all execution states in insertion order."""
        return [self._store[tid] for tid in self._order if tid in self._store]
    
    def load_by_status(self, status: str) -> list[dict]:
        """Load executions by status."""
        return [s for s in self._store.values() if s.get("status") == status]
    
    def replay(self, task_id: str) -> Optional[dict]:
        """
        Replay a task execution for debug.
        Returns full execution state with all intermediate data.
        """
        state = self._store.get(task_id)
        if not state:
            return None
        
        # Add replay metadata
        state["_replay"] = {
            "replayed_at": time.time(),
            "events_count": len(state.get("trace_report", {}).get("events", [])),
        }
        return state
    
    def stats(self) -> dict:
        """Get memory statistics."""
        statuses = defaultdict(int)
        for s in self._store.values():
            statuses[s.get("status", "UNKNOWN")] += 1
        
        total_retries = sum(s.get("retry_count", 0) for s in self._store.values())
        avg_latency = 0.0
        latencies = [s.get("timing", {}).get("total_latency", 0) for s in self._store.values()]
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
        
        return {
            "total_entries": len(self._store),
            "max_entries": self._max,
            "status_breakdown": dict(statuses),
            "total_retries": total_retries,
            "avg_latency": round(avg_latency, 3),
        }
    
    def clear(self):
        """Clear all stored executions."""
        self._store.clear()
        self._order.clear()


# ═══════════════════════════════════════════════════════════
# FSM Worker
# ═══════════════════════════════════════════════════════════

class FSMWorker:
    """
    An independent FSM execution worker.
    
    Each worker:
      - Runs its own FSMOrchestrator instance
      - Has its own Scheduler, RetryPolicy, ContextIsolation
      - Can execute tasks concurrently with other workers
      - Reports results back to MAEOS memory
    """
    
    _worker_counter = 0
    
    def __init__(
        self,
        provider: str = "openrouter",
        model: str = "openrouter/auto",
        api_key: str = "",
        base_url: str = None,
        max_concurrency: int = 1,
    ):
        FSMWorker._worker_counter += 1
        self.worker_id = f"worker_{FSMWorker._worker_counter:03d}"
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_concurrency = max_concurrency
        
        # Per-worker runtime subsystems
        self.scheduler = Scheduler(max_concurrency=max_concurrency)
        self.retry_policy = RetryPolicy(
            max_retries=3,
            backoff_strategy=BackoffStrategy.LINEAR,
            base_delay_ms=1000,
        )
        self.context_isolation = ContextIsolation()
        self.flow_control = FlowControlEnforcer(mode="strict")
        
        # Worker state
        self._running: Optional[Task] = None
        self._total_executed = 0
        self._total_failed = 0
    
    async def execute(self, task: Task) -> Task:
        """
        Execute a task through the pipeline.

        Replaced FSMOrchestrator with pipeline.run_pipeline().
        Returns the task with result/context filled in.
        """
        self._running = task
        task.status = TaskStatus.RUNNING
        task.worker_id = self.worker_id
        task.started_at = time.time()

        logger.info(f"[{self.worker_id}] executing task {task.id}: {task.description[:80]}")

        try:
            # Execute via simple pipeline
            result = await run_pipeline(
                channel_id=task.id,
                user_message=task.description,
                system_prompt="You are a helpful AI assistant.",
                provider=task.provider or self.provider,
                model=task.model or self.model,
                api_key=task.api_key or self.api_key,
                base_url=task.base_url or self.base_url,
            )

            # Build lightweight context from result
            ctx = FSMContext(
                task_id=task.id,
                intent=task.intent,
                execution_result=result,
                final_result=result,
                state=TaskStatus.COMPLETED,
            )

            task.context = ctx
            task.result = result

            task.status = TaskStatus.COMPLETED
            self._total_executed += 1

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = f"{type(e).__name__}: {e}"
            self._total_failed += 1
            logger.error(f"[{self.worker_id}] task {task.id} failed: {e}")

        task.completed_at = time.time()
        self._running = None

        logger.info(
            f"[{self.worker_id}] task {task.id} {task.status} "
            f"in {task.execution_time:.1f}s (retries={task.retry_count})"
        )
        return task
    
    @property
    def is_busy(self) -> bool:
        return self._running is not None
    
    @property
    def stats(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "is_busy": self.is_busy,
            "total_executed": self._total_executed,
            "total_failed": self._total_failed,
            "current_task": self._running.id if self._running else None,
        }


# ═══════════════════════════════════════════════════════════
# MAEOS Kernel
# ═══════════════════════════════════════════════════════════

class MAEOS:
    """
    Multi-Agent Execution Operating System.
    
    Full execution OS for multi-teammate team pipelines.
    
    Usage:
        os = MAEOS(max_workers=4)
        await os.start()
        
        task_id = await os.submit("Design auth system", priority=TaskPriority.HIGH)
        result = await os.wait(task_id)
        
        # Or fire-and-forget
        task_id = await os.submit("Quick fix")
        
        # Debug
        os.debug_task(task_id)
        os.shutdown()
    """
    
    def __init__(
        self,
        max_workers: int = 4,
        provider: str = "openrouter",
        model: str = "openrouter/auto",
        api_key: str = "",
        base_url: str = None,
        memory_size: int = 1000,
    ):
        self.max_workers = max_workers
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        
        # Subsystems
        self.queue = PriorityTaskQueue()
        self.memory = ExecutionMemory(max_entries=memory_size)
        self._workers: list[FSMWorker] = []
        
        # Event signaling
        self._completed_events: dict[str, asyncio.Event] = {}
        
        # State
        self._started = False
        self._shutdown = False
        self._scheduler_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start the MAEOS kernel and worker pool."""
        if self._started:
            return
        
        logger.info(f"[MAEOS] starting with {self.max_workers} workers")
        
        # Create worker pool
        for _ in range(self.max_workers):
            worker = FSMWorker(
                provider=self.provider,
                model=self.model,
                api_key=self.api_key,
                base_url=self.base_url,
                max_concurrency=1,
            )
            self._workers.append(worker)
        
        # Start scheduler loop
        self._started = True
        self._shutdown = False
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info(f"[MAEOS] started, {len(self._workers)} workers ready")
    
    async def shutdown(self, wait: bool = True) -> None:
        """Shutdown the OS."""
        logger.info("[MAEOS] shutting down")
        self._shutdown = True
        
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        
        # Wait for running tasks
        if wait:
            while any(w.is_busy for w in self._workers):
                await asyncio.sleep(0.1)
        
        self._started = False
        logger.info("[MAEOS] shutdown complete")
    
    async def submit(
        self,
        description: str,
        priority: int = TaskPriority.NORMAL,
        intent: str = "",
        provider: str = None,
        model: str = None,
        api_key: str = None,
        wait: bool = True,
    ) -> str:
        """
        Submit a task to MAEOS.
        
        Args:
            description: Task description
            priority: Task priority (CRITICAL/HIGH/NORMAL/LOW/BACKGROUND)
            intent: Optional intent hint
            provider: LLM provider
            model: LLM model
            api_key: API key (optional, falls back to default)
            wait: If True, block until task completes
        
        Returns:
            task_id
        """
        task = Task(
            id=f"task_{uuid.uuid4().hex[:12]}",
            description=description,
            priority=priority,
            intent=intent,
            provider=provider or self.provider,
            model=model or self.model,
            api_key=api_key or self.api_key,
            base_url=self.base_url,
        )
        
        # Create completion event
        event = asyncio.Event()
        self._completed_events[task.id] = event
        
        # Push to queue
        self.queue.push(task)
        logger.info(f"[MAEOS] submitted task {task.id} priority={priority}")
        
        if wait:
            await event.wait()
        
        return task.id
    
    async def wait(self, task_id: str, timeout: float = 300.0) -> Optional[Task]:
        """
        Wait for a task to complete.
        
        Returns the completed Task, or None on timeout.
        """
        event = self._completed_events.get(task_id)
        if not event:
            # Check if already completed
            task = self.queue.get(task_id)
            if task and task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.ABORTED):
                return task
            return None
        
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"[MAEOS] wait timeout for task {task_id}")
            return None
        
        self._completed_events.pop(task_id, None)
        return self.queue.get(task_id)
    
    def get_status(self, task_id: str) -> Optional[dict]:
        """Get status of a task."""
        task = self.queue.get(task_id)
        if not task:
            # Check memory
            state = self.memory.load(task_id)
            return state
        return task.to_dict()
    
    def debug_task(self, task_id: str) -> Optional[dict]:
        """
        Get full debug info for a task.
        Includes trace, diversity report, all teammate outputs.
        """
        return self.memory.replay(task_id)
    
    def list_tasks(self, status: str = None) -> list[dict]:
        """List all tasks, optionally filtered by status."""
        tasks = self.queue.list_all()
        if status:
            tasks = [t for t in tasks if t.status == status]
        return [t.to_dict() for t in tasks]
    
    def stats(self) -> dict:
        """Get full system statistics."""
        worker_stats = [w.stats for w in self._workers]
        memory_stats = self.memory.stats()
        
        return {
            "status": "running" if self._started else "stopped",
            "total_workers": len(self._workers),
            "busy_workers": sum(1 for w in self._workers if w.is_busy),
            "queue_size": self.queue.total,
            "queue_pending": self.queue.count_by_status(TaskStatus.PENDING),
            "queue_running": self.queue.count_by_status(TaskStatus.RUNNING),
            "workers": worker_stats,
            "memory": memory_stats,
        }
    
    # ── Internal Scheduler Loop ──
    
    async def _scheduler_loop(self) -> None:
        """
        Main scheduler loop.
        
        Continuously:
          1. Check for pending tasks in queue
          2. Assign to available workers
          3. Save completed task states to memory
        """
        logger.info("[MAEOS] scheduler loop started")
        
        while not self._shutdown:
            try:
                # Find available worker
                available = [w for w in self._workers if not w.is_busy]
                
                if available and not self.queue.is_empty:
                    # Get highest priority task
                    task = self.queue.pop()
                    if task:
                        task.status = TaskStatus.SCHEDULED
                        task.scheduled_at = time.time()
                        
                        # Assign to first available worker
                        worker = available[0]
                        
                        # Execute in background
                        asyncio.create_task(self._execute_on_worker(worker, task))
                
                # Small sleep to prevent busy-waiting
                await asyncio.sleep(0.05)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MAEOS] scheduler error: {e}")
                await asyncio.sleep(1.0)
        
        logger.info("[MAEOS] scheduler loop stopped")

    async def _execute_on_worker(self, worker: FSMWorker, task: Task) -> None:
        """Execute a task on a worker and save results."""
        try:
            # Execute
            completed_task = await worker.execute(task)
            
            # Save to memory
            self.memory.save(completed_task)
            
            # Signal completion
            event = self._completed_events.get(task.id)
            if event:
                event.set()
                
        except Exception as e:
            logger.error(f"[MAEOS] worker execution error: {e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = time.time()
            self.memory.save(task)
            
            event = self._completed_events.get(task.id)
            if event:
                event.set()


# ═══════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════

def create_maeos(**kwargs) -> MAEOS:
    """Create a MAEOS instance."""
    return MAEOS(**kwargs)
