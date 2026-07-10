"""
runtime/scheduler.py — Execution Scheduler Layer

Controls:
  - execution queue (FIFO)
  - task dispatching (serial or concurrent)
  - state transition timing
  - retry scheduling (delegates to RetryPolicy)
  - concurrency control (asyncio.Semaphore)

RULE: Team engine MUST NOT directly call teammates.
      All execution MUST go through Scheduler.
"""

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional
from enum import Enum

logger = logging.getLogger("runtime.scheduler")


# ── Execution Status ──

class ExecStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    ABORTED = "ABORTED"


# ── Execution Unit ──

@dataclass
class ExecUnit:
    """A single schedulable execution unit."""
    id: str
    teammate_id: str
    state: str              # FSM state that triggered this execution
    fn: Callable[..., Awaitable[Any]]  # teammate function to call
    kwargs: dict = field(default_factory=dict)
    status: str = ExecStatus.PENDING
    attempt: int = 0
    max_attempts: int = 3
    created_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    result: Any = None
    error: str = ""
    retry_delay_ms: int = 0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()

    @property
    def latency_ms(self) -> int:
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at) * 1000)
        return 0


# ── Scheduler ──

class Scheduler:
    """
    Execution scheduler — single point of dispatch for all teammate calls.

    Usage:
        scheduler = Scheduler(max_concurrency=1)
        unit = scheduler.submit(teammate_fn, teammate_id="strategy", state="PLAN", kwargs={...})
        result = await scheduler.execute(unit)
    """

    def __init__(self, max_concurrency: int = 1):
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._queue: asyncio.Queue[ExecUnit] = asyncio.Queue()
        self._completed: list[ExecUnit] = []
        self._running = False

    def submit(
        self,
        fn: Callable[..., Awaitable[Any]],
        teammate_id: str,
        state: str,
        kwargs: dict = None,
        max_attempts: int = 3,
    ) -> ExecUnit:
        """Submit an execution unit to the queue."""
        unit = ExecUnit(
            id=f"exec_{int(time.time()*1000)}_{teammate_id}",
            teammate_id=teammate_id,
            state=state,
            fn=fn,
            kwargs=kwargs or {},
            max_attempts=max_attempts,
        )
        logger.info(f"[SCHEDULER] submit {unit.id} teammate={teammate_id} state={state}")
        return unit

    async def execute(self, unit: ExecUnit) -> ExecUnit:
        """
        Execute a single unit with concurrency control.
        Returns the unit with result filled in.
        """
        async with self._semaphore:
            unit.status = ExecStatus.RUNNING
            unit.started_at = time.time()
            unit.attempt += 1

            logger.info(
                f"[SCHEDULER] execute {unit.id} "
                f"teammate={unit.teammate_id} attempt={unit.attempt}/{unit.max_attempts}"
            )

            try:
                result = await unit.fn(**unit.kwargs)
                unit.result = result
                unit.status = ExecStatus.SUCCESS
                logger.info(f"[SCHEDULER] success {unit.id}")
            except Exception as e:
                unit.error = f"{type(e).__name__}: {e}"
                unit.status = ExecStatus.FAILED
                logger.error(f"[SCHEDULER] failed {unit.id}: {unit.error}")

            unit.finished_at = time.time()
            self._completed.append(unit)
            return unit

    async def execute_with_retry(
        self,
        unit: ExecUnit,
        retry_policy: "RetryPolicy",
    ) -> ExecUnit:
        """
        Execute with retry loop controlled by RetryPolicy.
        Scheduler handles timing, not the orchestrator.
        """
        while unit.attempt < unit.max_attempts:
            unit = await self.execute(unit)

            if unit.status == ExecStatus.SUCCESS:
                return unit

            # Ask retry policy what to do
            decision = retry_policy.decide(unit)
            if decision.action == "abort":
                unit.status = ExecStatus.ABORTED
                unit.error = f"Aborted by policy: {decision.reason}"
                return unit

            if decision.action == "retry":
                unit.retry_delay_ms = decision.delay_ms
                unit.status = ExecStatus.RETRY_SCHEDULED
                logger.info(
                    f"[SCHEDULER] retry {unit.id} in {decision.delay_ms}ms "
                    f"(attempt {unit.attempt + 1}/{unit.max_attempts})"
                )
                await asyncio.sleep(decision.delay_ms / 1000.0)
                continue

            # fallback — no retry
            return unit

        # Max attempts exhausted
        unit.status = ExecStatus.FAILED
        unit.error = f"Max attempts ({unit.max_attempts}) exhausted"
        return unit

    @property
    def completed(self) -> list[ExecUnit]:
        return list(self._completed)

    def reset(self):
        self._completed.clear()
