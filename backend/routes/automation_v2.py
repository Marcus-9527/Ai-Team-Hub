"""routes/automation_v2.py — Teammate Autonomous Automation Engine v2.

Reuses existing TaskOrchestrator for execution. Adds:
- AutomationJob CRUD (new schema: teammate-bound jobs with goal/SOP)
- AutomationRun history
- Background check-in poll loop (extensible to cron/event/webhook)
"""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models import AutomationJobModel, AutomationRunModel, gen_uuid, utcnow, Teammate

logger = logging.getLogger("routes.automation_v2")
router = APIRouter(prefix="/api/automation-jobs", tags=["automation-v2"])

# Tunables — normal B-batch runs finish in ~10-30s; 5min is a conservative ceiling.
AUTOMATION_RUN_TIMEOUT_SEC = int(
    __import__("os").environ.get("AUTOMATION_RUN_TIMEOUT_SEC", "300")
)
# Stale threshold for orphan reclaim on startup. Restart loses in-flight create_task coroutines.
AUTOMATION_ORPHAN_STALE_MIN = int(
    __import__("os").environ.get("AUTOMATION_ORPHAN_STALE_MIN", "15")
)


async def reap_orphaned_runs():
    """On startup, any run still 'running' and older than the stale threshold can
    never recover — its fire-and-forget coroutine died with the previous process.
    Mark it failed with a traceable reason so it doesn't pollute future diagnostics."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=AUTOMATION_ORPHAN_STALE_MIN)
    try:
        async with async_session() as db:
            result = await db.execute(
                select(AutomationRunModel).where(
                    AutomationRunModel.status == "running",
                    AutomationRunModel.started_at < cutoff,
                )
            )
            stale = result.scalars().all()
            for r in stale:
                r.status = "failed"
                r.error = "orphaned-by-restart"
                r.completed_at = datetime.now(timezone.utc)
            await db.commit()
            if stale:
                logger.warning("[AUTOv2] reaped %d orphaned run(s): %s",
                               len(stale), [s.id[:8] for s in stale])
    except Exception as e:
        logger.warning("[AUTOv2] orphan reap failed: %s", e)


async def automation_orphan_reaper_loop(interval: int = 300):
    """Continuous backstop: even if the process never restarts, periodically
    reclaim runs that slipped past the wait_for timeout (e.g. a task that hangs
    without awaiting anything cancellable). Runs forever alongside the app."""
    await asyncio.sleep(interval)  # first pass already done at startup
    while True:
        await reap_orphaned_runs()
        await asyncio.sleep(interval)


# ── Schemas ──
class CreateJobRequest(BaseModel):
    name: str
    teammate_id: str = ""
    workspace_id: str = ""
    trigger_type: str = "manual"
    schedule_expression: str = ""
    goal: str = ""
    sop_definition: dict = {}
    status: str = "active"


# ── Schedule helpers ──

_PRESET_INTERVALS = {
    "daily": 86400,
    "weekly": 604800,
    "hourly": 3600,
    "every_6h": 21600,
    "every_12h": 43200,
}


def _parse_schedule_interval(expr: str | None) -> int | None:
    """Convert schedule_expression to interval seconds (preset name or raw int)."""
    if not expr:
        return None
    if expr in _PRESET_INTERVALS:
        return _PRESET_INTERVALS[expr]
    try:
        return int(expr)
    except (ValueError, TypeError):
        return None


# ── Job CRUD ──

@router.get("")
async def list_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AutomationJobModel).order_by(AutomationJobModel.created_at.desc())
    )
    return {"jobs": [_j2d(j) for j in result.scalars().all()]}


@router.post("", status_code=201)
async def create_job(req: CreateJobRequest, db: AsyncSession = Depends(get_db)):
    job = AutomationJobModel(
        id=gen_uuid(),
        name=req.name,
        teammate_id=req.teammate_id,
        workspace_id=req.workspace_id,
        trigger_type=req.trigger_type,
        schedule_expression=req.schedule_expression,
        goal=req.goal,
        sop_definition=req.sop_definition or {},
        status=req.status,
        is_active="1",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _j2d(job)


@router.patch("/{job_id}")
async def update_job(job_id: str, req: CreateJobRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AutomationJobModel).where(AutomationJobModel.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, detail="Job not found")
    for field in ("name", "teammate_id", "workspace_id", "trigger_type",
                  "schedule_expression", "goal", "sop_definition", "status"):
        setattr(job, field, getattr(req, field))
    job.updated_at = utcnow()
    await db.commit()
    await db.refresh(job)
    return _j2d(job)


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AutomationJobModel).where(AutomationJobModel.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, detail="Job not found")
    await db.delete(job)
    await db.commit()


# ── Run history ──

@router.get("/runs")
async def list_all_runs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AutomationRunModel)
        .order_by(AutomationRunModel.created_at.desc())
        .limit(50)
    )
    return {"runs": [_r2d(r) for r in result.scalars().all()]}


@router.get("/{job_id}/runs")
async def list_runs(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AutomationRunModel)
        .where(AutomationRunModel.job_id == job_id)
        .order_by(AutomationRunModel.created_at.desc())
        .limit(50)
    )
    return {"runs": [_r2d(r) for r in result.scalars().all()]}


# ── Manual trigger ──

@router.post("/{job_id}/trigger")
async def trigger_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AutomationJobModel).where(AutomationJobModel.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, detail="Job not found")
    if job.is_active != "1":
        raise HTTPException(400, detail="Job is not active")

    # Create run record
    run = AutomationRunModel(
        id=gen_uuid(),
        job_id=job.id,
        trigger="manual",
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()

    # Fire-and-forget execution
    asyncio.create_task(_execute_job(job, run))
    return {"run_id": run.id, "status": "running"}


# ── Background check-in loop ──

async def _execute_job(job: AutomationJobModel, run: AutomationRunModel):
    """Execute one automation job: load teammate → create task via orchestrator."""
    try:
        async with async_session() as db:
            # Reload run in this session
            db_run = await db.get(AutomationRunModel, run.id)
            if not db_run:
                logger.warning("[AUTOv2] run %s disappeared", run.id[:8])
                return

            # Load teammate identity
            tm = None
            if job.teammate_id:
                tm = await db.get(Teammate, job.teammate_id)

            # Create a task for this check-in run
            from backend.services.task.task_manager import TaskManager

            title = f"[Auto] {job.name}"
            description = job.goal[:500] if job.goal else job.name

            mgr = TaskManager()
            ws_id = tm.workspace_id if tm else None
            task = await mgr.create_task(
                db, title=title, description=description,
                channel_id="", workspace_id=ws_id,
                intent=job.goal or job.name,
            )
            await db.commit()

            # Run through OrganizationRuntime → OrganizationLoop → TaskOrchestrator
            from backend.services.organization.runtime import OrganizationRuntime
            rt = OrganizationRuntime(db)
            await asyncio.wait_for(
                rt.run_task(
                    task_id=task.id,
                    goal=job.goal or job.name,
                    channel_id="",
                    workspace_id=ws_id or "",
                ),
                timeout=AUTOMATION_RUN_TIMEOUT_SEC,
            )

            # Update run record
            db_run.status = "completed" if getattr(task, "status", "") == "COMPLETED" else "failed"
            db_run.result = f"Task {task.id[:8]} finished: {getattr(task, 'status', 'unknown')}"
            db_run.created_tasks = [task.id]
            db_run.completed_at = datetime.now(timezone.utc)

            job.last_run = datetime.now(timezone.utc)
            await db.commit()

            logger.info("[AUTOv2] job '%s' → task %s → %s", job.name[:30], task.id[:8], db_run.status)
    except asyncio.TimeoutError:
        logger.error("[AUTOv2] job '%s' timed out after %ss", job.name[:30], AUTOMATION_RUN_TIMEOUT_SEC)
        try:
            async with async_session() as db:
                db_run = await db.get(AutomationRunModel, run.id)
                if db_run:
                    db_run.status = "failed"
                    db_run.error = "execution-timeout"
                    db_run.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            pass
    except Exception as e:
        logger.error("[AUTOv2] job '%s' failed: %s", job.name[:30], e)
        try:
            async with async_session() as db:
                db_run = await db.get(AutomationRunModel, run.id)
                if db_run:
                    db_run.status = "failed"
                    db_run.error = str(e)[:2000]
                    db_run.completed_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception:
            pass


async def _check_due_jobs():
    """Check for due cron-type automation jobs."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(AutomationJobModel).where(
                    AutomationJobModel.is_active == "1",
                    AutomationJobModel.trigger_type.in_(["cron", "manual"]),
                )
            )
            now = datetime.now(timezone.utc)
            for job in result.scalars().all():
                interval = _parse_schedule_interval(job.schedule_expression)
                if interval is None:
                    continue  # can't interpret schedule
                if job.last_run and (now - job.last_run.replace(tzinfo=timezone.utc)).total_seconds() < interval:
                    continue  # not due yet
                # Create run and execute
                run = AutomationRunModel(
                    id=gen_uuid(), job_id=job.id, trigger="cron",
                    status="running", started_at=now,
                )
                db.add(run)
                await db.commit()
                asyncio.create_task(_execute_job(job, run))
    except Exception as e:
        logger.debug("[AUTOv2] check cycle: %s", e)


async def automation_v2_poll_loop(interval: int = 60):
    """Background loop: poll due automation jobs."""
    while True:
        await asyncio.sleep(interval)
        await _check_due_jobs()


# ── Helpers ──

def _j2d(j: AutomationJobModel) -> dict:
    return {
        "id": j.id,
        "workspace_id": j.workspace_id,
        "teammate_id": j.teammate_id,
        "name": j.name,
        "trigger_type": j.trigger_type,
        "schedule_expression": j.schedule_expression,
        "goal": j.goal,
        "sop_definition": j.sop_definition or {},
        "status": j.status,
        "is_active": j.is_active,
        "last_run": str(j.last_run) if j.last_run else None,
        "next_run": str(j.next_run) if j.next_run else None,
        "created_at": str(j.created_at) if j.created_at else None,
    }


def _r2d(r: AutomationRunModel) -> dict:
    return {
        "id": r.id,
        "job_id": r.job_id,
        "trigger": r.trigger,
        "actions": r.actions or [],
        "result": r.result,
        "artifact": r.artifact or {},
        "created_tasks": r.created_tasks or [],
        "status": r.status,
        "error": r.error,
        "started_at": str(r.started_at) if r.started_at else None,
        "completed_at": str(r.completed_at) if r.completed_at else None,
        "created_at": str(r.created_at) if r.created_at else None,
    }
