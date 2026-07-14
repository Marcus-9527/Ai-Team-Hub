"""test_task_claim.py — Phase 13.2 Task Claim Protocol 验证

验证：
- claim 竞争 — 第一个获胜
- 后续 claim 被拒绝
- 原子确认
"""
import pytest
import asyncio

from backend.services.autonomous.task_claim import TaskClaimManager, get_claim_manager

pytestmark = pytest.mark.asyncio


async def test_first_claim_wins():
    """First caller should claim the task."""
    manager = TaskClaimManager()
    task_id = "task_claim_test_1"

    ok1, _ = await manager.claim(task_id, "tm_eng", "Engineer", "Best fit")
    assert ok1 is True
    assert await manager.get_owner(task_id) == "tm_eng"


async def test_second_claim_rejected():
    """Second caller should be rejected."""
    manager = TaskClaimManager()
    task_id = "task_claim_test_2"

    ok1, _ = await manager.claim(task_id, "tm_eng", "Engineer", "First")
    ok2, msg2 = await manager.claim(task_id, "tm_des", "Designer", "Second")

    assert ok1 is True
    assert ok2 is False
    assert "already claimed" in msg2.lower()
    assert await manager.get_owner(task_id) == "tm_eng"


async def test_concurrent_claims_atomic():
    """Multiple concurrent claim attempts should result in exactly one winner."""
    manager = TaskClaimManager()
    task_id = "task_claim_test_3"

    async def try_claim(tm_id: str, name: str) -> tuple[str, bool]:
        ok, _ = await manager.claim(task_id, tm_id, name)
        return tm_id, ok

    # Fire 5 concurrent claims
    results = await asyncio.gather(*[
        try_claim(f"tm_{i}", f"TM{i}")
        for i in range(5)
    ])

    winners = [tm for tm, ok in results if ok]
    assert len(winners) == 1, f"Expected 1 winner, got {len(winners)}: {winners}"


async def test_claims_recorded():
    """All claim attempts should be recorded."""
    manager = TaskClaimManager()
    task_id = "task_claim_test_4"

    await manager.claim(task_id, "tm_a", "A")
    await manager.claim(task_id, "tm_b", "B")
    await manager.claim(task_id, "tm_c", "C")

    claims = await manager.get_claims(task_id)
    assert len(claims) == 3

    statuses = [c.status for c in claims]
    assert statuses.count("claimed") == 1
    assert statuses.count("rejected") == 2


async def test_clear_releases():
    """Clearing should reset claim state for a task."""
    manager = TaskClaimManager()
    task_id = "task_claim_test_5"

    await manager.claim(task_id, "tm_a", "A")
    assert await manager.get_owner(task_id) == "tm_a"

    await manager.clear(task_id)
    assert await manager.get_owner(task_id) is None
