"""Startup lifecycle steps, one function per concern.

Order is load-bearing: encryption validation before plaintext-key migration,
and task hooks register Memory → Brain → ChannelNotify (preserves the
original ordering in main.py).
"""
import asyncio
import logging

logger = logging.getLogger("startup")


async def init_encryption():
    from backend.security.crypto import validate_key, get_encryption_key_info
    key_info = get_encryption_key_info()
    logger.info("Encryption key source: %s", key_info["source"])
    validate_key()  # RuntimeError propagates to lifespan


async def migrate_legacy_keys():
    from backend.services.migration import migrate_plaintext_keys
    migrated = await migrate_plaintext_keys()
    if migrated:
        logger.info("Migrated %d plaintext API keys", migrated)


def register_task_hooks():
    from backend.services.memory.memory_event_handler import MemoryTaskHook
    from backend.services.brain.task_hook import BrainTaskHook
    from backend.services.brain.channel_notify_hook import ChannelNotifyHook
    from backend.services.task.artifact_hook import ArtifactTaskHook
    from backend.services.task.task_hooks import get_task_hook_registry
    registry = get_task_hook_registry()
    for hook in (MemoryTaskHook(), BrainTaskHook(), ChannelNotifyHook(), ArtifactTaskHook()):
        registry.register(hook)
        logger.info("%s registered", hook.__class__.__name__)


def register_event_subscribers():
    from backend.services.autonomous.event_wakeup import get_event_wakeup_bus, WakeupEvent
    from backend.services.autonomous.task_claim_subscriber import handle_task_created
    get_event_wakeup_bus().subscribe(WakeupEvent.TASK_CREATED, handle_task_created)
    logger.info("TASK_CREATED wakeup subscriber registered")


async def ensure_default_data():
    """Seed first-run data: default channel + 2 teammates.

    Moved from frontend App.jsx (was ensureDefaultData).  Uses the same
    async_session the rest of the backend uses; ponytail: one-shot, no
    retry logic — if DB is empty at startup, seed once.
    """
    from backend.database import async_session
    from backend.models import Channel, Teammate, APIKey
    from sqlalchemy import select, func as sa_func

    async with async_session() as db:
        cnt = (await db.execute(sa_func.count(Channel.id))).scalar()
        if cnt and cnt > 0:
            return  # already has data

        # ── API key ──
        keys = (await db.execute(select(APIKey).limit(1))).scalars().all()
        key_id = keys[0].id if keys else None

        # ── Default teammates ──
        tm_cnt = (await db.execute(sa_func.count(Teammate.id))).scalar()
        engineer_id = pm_id = None
        if not tm_cnt and key_id:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            engineer = Teammate(
                name="高级工程师", role="engineer", avatar_emoji="👨‍💻",
                system_prompt="You are a Senior Engineer. Write clean, efficient code.",
                model_provider="openrouter", model_name="openrouter/auto",
                api_key_ref=key_id, created_at=now, updated_at=now,
            )
            pm = Teammate(
                name="产品经理", role="pm", avatar_emoji="🧠",
                system_prompt="You are a Product Manager. Focus on user needs and strategic decisions.",
                model_provider="openrouter", model_name="openrouter/auto",
                api_key_ref=key_id, created_at=now, updated_at=now,
            )
            db.add_all([engineer, pm])
            await db.flush()
            engineer_id, pm_id = engineer.id, pm.id
        elif tm_cnt:
            tms = (await db.execute(select(Teammate).limit(2))).scalars().all()
            engineer_id = tms[0].id if tms else None
            pm_id = tms[1].id if len(tms) > 1 else None

        # ── Default channel ──
        channel = Channel(name="General", description="Main chat channel",
                          teammate_ids=[i for i in (engineer_id, pm_id) if i])
        db.add(channel)
        await db.commit()

    logger.info("Seeded default channel + teammates (first run)")


class BackgroundTaskManager:
    """Lifecycle for the periodic model sync / automation poll loops."""

    def __init__(self):
        self._tasks: list[asyncio.Task] = []

    def spawn(self, coro, name: str):
        task = asyncio.create_task(coro)
        task.set_name(name)
        self._tasks.append(task)
        logger.info("%s started", name)

    async def shutdown(self):
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
