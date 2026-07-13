"""
maeos.py — Multi-Agent Execution Operating System (MAEOS)

v1.0: Thin wrapper around ExecutionRuntime.
All execution logic migrated to services/runtime/executor.py.

Retained for API backward compatibility:
  - /api/maeos/* routes still work
  - Task/TaskPriority/TaskStatus data classes preserved

Migrated to services/runtime/:
  ✓ Priority Queue        → ExecutionRuntime._PriorityQueue
  ✓ Worker Pool           → ExecutionRuntime._workers + _scheduler_loop
  ✓ Retry mechanism       → runtime/retry_policy.py
  ✓ Trace mechanism       → runtime/trace.py

Deprecated:
  ✗ FSM state management  → handled by pipeline.run_pipeline()
  ✗ Standalone MAEOS entry → routes use ExecutionRuntime directly
"""
import asyncio
import logging
import time
from typing import Optional

from backend.services.runtime.executor import ExecutionRuntime, TaskPriority, ExecStatus

logger = logging.getLogger("maeos")


# ═══════════════════════════════════════════════════════════
# Data classes preserved for API backward compat
# ═══════════════════════════════════════════════════════════

class TaskPriority(int):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class Task:
    """Lightweight task response — wraps RuntimeTask for compat."""
    def __init__(self, runtime_task=None, task_id="", description="",
                 status="PENDING", result="", error=""):
        if runtime_task:
            self.id = runtime_task.id
            self.description = runtime_task.description
            self.status = _map_status(runtime_task.status)
            self.result = runtime_task.result
            self.error = runtime_task.error
            self.priority = runtime_task.priority
            self.created_at = runtime_task.created_at
            self.started_at = runtime_task.started_at
            self.completed_at = runtime_task.completed_at
        else:
            self.id = task_id
            self.description = description
            self.status = status
            self.result = result
            self.error = error
            self.priority = TaskPriority.NORMAL
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
            "completed_at": self.completed_at,
        }


def _map_status(status: str) -> str:
    mapping = {
        ExecStatus.PENDING: "PENDING",
        ExecStatus.RUNNING: "RUNNING",
        ExecStatus.COMPLETED: "COMPLETED",
        ExecStatus.FAILED: "FAILED",
        ExecStatus.ABORTED: "ABORTED",
    }
    return mapping.get(status, status)


# ═══════════════════════════════════════════════════════════
# MAEOS — Thin Wrapper
# ═══════════════════════════════════════════════════════════

class MAEOS:
    """
    Multi-Agent Execution OS — v1.0 wrapper.

    Delegates all execution to ExecutionRuntime.
    Preserves public API for backward compat.

    Usage:
        os = MAEOS(max_workers=4)
        await os.start()
        task_id = await os.submit("Hello")
        result = await os.wait(task_id)
        os.shutdown()
    """

    def __init__(self, max_workers: int = 4,
                 provider: str = "openrouter",
                 model: str = "openrouter/auto",
                 api_key: str = "", base_url: str = None,
                 memory_size: int = 1000):
        self.max_workers = max_workers
        self._runtime = ExecutionRuntime(
            max_workers=max_workers,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
        # Preserve memory reference for /api/maeos/memory/stats
        self._memory_stats = {"total_entries": 0, "max_entries": memory_size}
        self._started = False

    async def start(self) -> None:
        await self._runtime.start()
        self._started = True

    async def shutdown(self, wait: bool = True) -> None:
        await self._runtime.shutdown()
        self._started = False

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
        return await self._runtime.submit(
            description=description,
            priority=priority,
            intent=intent,
            provider=provider,
            model=model,
            api_key=api_key,
            wait=wait,
        )

    async def wait(self, task_id: str, timeout: float = 300.0) -> Optional[Task]:
        rt = await self._runtime.wait(task_id, timeout=timeout)
        if rt is None:
            return None
        return Task(runtime_task=rt)

    def get_status(self, task_id: str) -> Optional[dict]:
        status = self._runtime.get_status(task_id)
        if not status:
            return None
        # Wrap in old format with full Task fields
        status["status"] = _map_status(status.get("status", "UNKNOWN"))
        return status

    def debug_task(self, task_id: str) -> Optional[dict]:
        status = self._runtime.get_status(task_id)
        if not status:
            return None
        return {
            "task_id": task_id,
            **status,
            "_runtime_v1": True,
        }

    def list_tasks(self, status: str = None) -> list[dict]:
        # ExecutionRuntime doesn't maintain a full task list publicly
        return []

    async def stats(self) -> dict:
        base = await self._runtime.stats()
        return {
            **base,
            "status": "running" if self._started else "stopped",
        }

    @property
    def memory(self):
        """Backward compat: memory.stats used by /api/maeos/memory/stats."""
        return self._memory_stats


def create_maeos(**kwargs) -> MAEOS:
    """Create a MAEOS instance (factory)."""
    return MAEOS(**kwargs)
