"""routes/automation.py — Phase 7: Automation Rules CRUD + background trigger.

Ponytail: No scheduler engine. A simple polling loop in lifespan checks
for due AutomationRule records and creates tasks via existing TaskOrchestrator.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models import AutomationRuleModel, gen_uuid, utcnow

logger = logging.getLogger("routes.automation")
router = APIRouter(prefix="/api/automation", tags=["automation"])

# ── Schemas ──


class CreateRuleRequest(BaseModel):
    name: str
    description: str = ""
    schedule_interval_sec: int = 300
    task_title: str
    task_intent: str = ""
    channel_id: str = ""
    team_ids: list[str] = []
    is_active: str = "1"
    trigger_event: str = ""  # Phase 19: event-triggered, e.g. "task_created"


class RuleResponse(BaseModel):
    id: str
    name: str
    description: str
    schedule_interval_sec: int
    task_title: str
    task_intent: str
    channel_id: str
    team_ids: list[str]
    is_active: str
    trigger_event: str = ""
    last_triggered_at: Optional[str]
    created_at: Optional[str]


# ── CRUD ──


@router.get("")
async def list_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AutomationRuleModel).order_by(AutomationRuleModel.created_at.desc())
    )
    rules = result.scalars().all()
    return {"rules": [_rule_to_dict(r) for r in rules]}


@router.post("", status_code=201)
async def create_rule(req: CreateRuleRequest, db: AsyncSession = Depends(get_db)):
    rule = AutomationRuleModel(
        id=gen_uuid(),
        name=req.name,
        description=req.description,
        schedule_interval_sec=req.schedule_interval_sec,
        task_title=req.task_title,
        task_intent=req.task_intent,
        channel_id=req.channel_id,
        team_ids=req.team_ids,
        is_active=req.is_active,
        trigger_event=req.trigger_event or None,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _rule_to_dict(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AutomationRuleModel).where(AutomationRuleModel.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()


@router.patch("/{rule_id}")
async def toggle_rule(rule_id: str, is_active: str = "1", db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AutomationRuleModel).where(AutomationRuleModel.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, detail="Rule not found")
    rule.is_active = is_active
    rule.updated_at = utcnow()
    await db.commit()
    await db.refresh(rule)
    return _rule_to_dict(rule)


# ── Background polling (called from lifespan) ──


async def _check_and_trigger():
    """Check due automation rules and create tasks."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(AutomationRuleModel).where(AutomationRuleModel.is_active == "1")
            )
            rules = result.scalars().all()
            now = datetime.now(timezone.utc)
            triggered = 0
            for rule in rules:
                # Skip event-triggered rules — they're handled by event_wakeup
                if rule.trigger_event:
                    continue
                last = rule.last_triggered_at
                if last and (now - last.replace(tzinfo=timezone.utc)).total_seconds() < rule.schedule_interval_sec:
                    continue
                # Create task via TaskOrchestrator
                try:
                    from backend.services.task.task_manager import TaskManager
                    from backend.services.task.task_orchestrator import TaskOrchestrator
                    from backend.services.runtime.executor import ExecutionRuntime

                    mgr = TaskManager()
                    task = await mgr.create_task(
                        db,
                        title=rule.task_title,
                        description=rule.description,
                        channel_id=rule.channel_id or None,
                        intent=rule.task_intent or rule.task_title,
                    )
                    await db.commit()

                    # Background orchestration
                    runtime = ExecutionRuntime(max_workers=4)
                    orch = TaskOrchestrator(runtime=runtime)
                    asyncio.create_task(orch.start_task(db, task.id, rule.task_intent or rule.task_title))

                    rule.last_triggered_at = now
                    triggered += 1
                    logger.info("[AUTO] triggered rule '%s' → task %s", rule.name, task.id[:8])
                except Exception as e:
                    logger.warning("[AUTO] rule '%s' trigger failed: %s", rule.name, e)

            await db.commit()
            if triggered:
                logger.info("[AUTO] triggered %d automation rule(s)", triggered)
    except Exception as e:
        logger.debug("[AUTO] check cycle error (non-fatal): %s", e)


async def automation_poll_loop(interval: int = 30):
    """Background loop: poll due rules every `interval` seconds."""
    while True:
        await asyncio.sleep(interval)
        await _check_and_trigger()


# ── Helpers ──


def _rule_to_dict(r: AutomationRuleModel) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "schedule_interval_sec": r.schedule_interval_sec,
        "task_title": r.task_title,
        "task_intent": r.task_intent,
        "channel_id": r.channel_id,
        "team_ids": r.team_ids or [],
        "is_active": r.is_active,
        "trigger_event": r.trigger_event or "",
        "last_triggered_at": str(r.last_triggered_at) if r.last_triggered_at else None,
        "created_at": str(r.created_at) if r.created_at else None,
    }
