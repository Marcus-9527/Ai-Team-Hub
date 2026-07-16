"""Verify BrainFragment writes carry workspace_id and channel summary lands.

Ponytail: single self-check, no framework. Run:
  PYTHONPATH=backend python backend/tests/test_brain_workspace_isolation.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/home/liunx/workspace/ai-team-hub/backend")

from backend.services.brain.fragment_store import (
    get_brain_fragment_store,
    BrainFragment,
    BrainFragmentType,
)
from backend.services.brain.reflection import get_reflection_service
from backend.services.task.task_hooks import TaskHookContext, TaskLifecycleEvent
from backend.services.brain.task_hook import BrainTaskHook


async def main():
    store = get_brain_fragment_store()

    # 1. Write a fragment WITH workspace_id, read back isolated
    ws_a, ws_b = "ws_A", "ws_B"
    f_a = BrainFragment(
        teammate_id="tm_x", workspace_id=ws_a,
        fragment_type=BrainFragmentType.LESSONS,
        content="lesson in A", source="reflection",
    )
    f_b = BrainFragment(
        teammate_id="tm_x", workspace_id=ws_b,
        fragment_type=BrainFragmentType.LESSONS,
        content="lesson in B", source="reflection",
    )
    await store.store(f_a)
    await store.store(f_b)

    got_a = await store.get_all_by_teammate("tm_x", workspace_id=ws_a)
    got_b = await store.get_all_by_teammate("tm_x", workspace_id=ws_b)
    # Without workspace filter, both show up
    got_all = await store.get_all_by_teammate("tm_x")

    # Without workspace filter, both workspaces coexist (unfiltered shows latest per type = 1 here due to dedup)
    got_all = await store.get_all_by_teammate("tm_x")
    # Cross-workspace isolation: A must NOT contain B's content
    a_contents = {f.content for f in got_a}
    assert "lesson in B" not in a_contents, f"A leaked B: {got_a}"
    assert len(got_a) == 1 and got_a[0].workspace_id == ws_a, f"A isolation failed: {got_a}"
    assert len(got_b) == 1 and got_b[0].workspace_id == ws_b, f"B isolation failed: {got_b}"
    print(f"[OK] workspace isolation: A={len(got_a)} (ws={got_a[0].workspace_id}) B={len(got_b)} (ws={got_b[0].workspace_id}) unfiltered={len(got_all)}")

    # 2. Channel summary via hook context
    hook = BrainTaskHook()
    ctx = TaskHookContext(
        task_id="t_1", task_title="Build landing page",
        task_status="COMPLETED", channel_id="ch_42", workspace_id=ws_a,
        execution_teammate_id="tm_x",
    )
    await hook.on_task_completed(ctx)
    await asyncio.sleep(0.3)  # fire-and-forget futures

    summary = await store.get_latest("ch_42", BrainFragmentType.CHANNEL_SUMMARY.value, ws_a)
    assert summary is not None, "channel summary not written"
    assert ws_a in (summary.workspace_id or ""), f"summary ws missing: {summary.workspace_id}"
    assert "Build landing page" in summary.content, f"summary content wrong: {summary.content}"
    print(f"[OK] channel summary written (ws={summary.workspace_id}):\n{summary.content}")

    # 3. Channel summary must NOT leak to another workspace
    summary_other = await store.get_latest("ch_42", BrainFragmentType.CHANNEL_SUMMARY.value, "ws_OTHER")
    assert summary_other is None, f"cross-workspace leak: {summary_other}"
    print("[OK] channel summary workspace-isolated (no leak to ws_OTHER)")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
