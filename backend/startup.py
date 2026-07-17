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
