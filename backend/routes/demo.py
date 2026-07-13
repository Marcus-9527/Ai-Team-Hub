"""routes/demo.py — Phase 11: Commercial Demo Flow.

Initializes a demo workspace: creates teammates, channel, and sample task.
No new engines — reuses existing services (TaskManager, Teammate CRUD).
"""
import asyncio
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.routes.teammates import create_teammate as _create_tm_fn
from backend.routes.channels import create_channel as _create_ch_fn
from backend.models import gen_uuid

logger = logging.getLogger("routes.demo")
router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/init")
async def demo_init():
    """Initialize a demo workspace with teammates, channel, and sample task.

    Idempotent: re-running skips existing items (based on name).
    Returns the created state.
    """
    from backend.models import Teammate, Channel
    from sqlalchemy import select
    from backend.services.task.task_manager import TaskManager
    from backend.services.task.task_orchestrator import TaskOrchestrator
    from backend.services.runtime.executor import ExecutionRuntime

    created = {"teammates": [], "channel": None, "task": None}

    async with async_session() as db:
        # 1. Check/create demo teammates
        existing_tms = (await db.execute(select(Teammate))).scalars().all()
        existing_names = {t.name for t in existing_tms}

        demo_team = [
            {"name": "Demo 工程师", "role": "engineer", "avatar_emoji": "👨‍💻",
             "system_prompt": "You are a Senior Engineer. Write clean, efficient code.",
             "model_provider": "openrouter", "model_name": "openrouter/auto"},
            {"name": "Demo 产品经理", "role": "pm", "avatar_emoji": "🧠",
             "system_prompt": "You are a Product Manager. Focus on user needs and strategy.",
             "model_provider": "openrouter", "model_name": "openrouter/auto"},
            {"name": "Demo 技术负责人", "role": "techlead", "avatar_emoji": "👑",
             "system_prompt": "You are a Tech Lead. Coordinate the team and synthesize results.",
             "model_provider": "openrouter", "model_name": "openrouter/auto"},
        ]

        teammate_ids = []
        for t in demo_team:
            if t["name"] in existing_names:
                tm = next(x for x in existing_tms if x.name == t["name"])
                teammate_ids.append(tm.id)
                created["teammates"].append({"id": tm.id, "name": tm.name})
            else:
                tm = Teammate(id=gen_uuid(), **t)
                db.add(tm)
                await db.flush()
                teammate_ids.append(tm.id)
                created["teammates"].append({"id": tm.id, "name": tm.name})

        # 2. Check/create demo channel
        existing_ch = (await db.execute(select(Channel))).scalars().all()
        demo_ch = next((c for c in existing_ch if c.name == "Demo"), None)
        if demo_ch is None:
            demo_ch = Channel(
                id=gen_uuid(), name="Demo",
                description="AI Team Hub demo workspace",
                teammate_ids=teammate_ids,
            )
            db.add(demo_ch)
            await db.flush()
        created["channel"] = {"id": demo_ch.id, "name": demo_ch.name}

        # 3. Create a sample task (no execute — just demonstration)
        mgr = TaskManager()
        demo_task = await mgr.create_task(
            db, title="Demo: 分析用户增长趋势",
            description="分析过去3个月的用户增长趋势，找出增长驱动因素，并给出下一步建议。",
            channel_id=demo_ch.id,
            intent="分析用户增长数据并提出建议",
        )
        await db.commit()

        # Background: orchestrate the demo task
        runtime = ExecutionRuntime(max_workers=2)
        orch = TaskOrchestrator(runtime=runtime)
        asyncio.create_task(orch.start_task(
            db, demo_task.id,
            "分析用户增长趋势：找出增长驱动因素，提出产品优化建议"
        ))

        created["task"] = {
            "id": demo_task.id,
            "title": demo_task.title,
            "description": demo_task.description,
            "status": demo_task.status,
        }

    return {
        "status": "ok",
        "message": "Demo workspace initialized. Check the 'Demo' channel.",
        "created": created,
    }
