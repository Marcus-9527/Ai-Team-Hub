"""
test_planner_workspace_key.py — Planner-path workspace key propagation.

Regression guard for the bug where the *lower* resolver (_apply_db_key_to_kwargs
/ resolve_api_key) was correct, but the *upper* caller on the planner path did
not pass workspace_id down — so a workspace-scoped key existed yet planning
fell through to the legacy-global scope and failed.

This asserts the WHOLE planner call chain, not just the leaf resolver:
  TaskOrchestrator._plan(workspace_id) → PlanningEngine.plan(api_key=...) →
  generate_plan(api_key=...)
The workspace has a scoped key; NO legacy-global key exists. If the chain
regresses to the legacy path, generate_plan receives an empty api_key and the
assertion fires.
"""

import pytest
from unittest.mock import AsyncMock, patch

pytestmark = [pytest.mark.asyncio]

WS = "test-ws-planner-000000000001"
WS_KEY = "sk-planner-workspace-scoped-key-value-64-chars-long-aaaaaaaaaaaa"


async def _create_key(sess, workspace_id, label, body):
    from backend.models import APIKey
    from backend.crypto import encrypt_value
    k = APIKey(
        workspace_id=workspace_id,
        provider="openrouter",
        label=label,
        api_key=encrypt_value(body),
        is_active="1",
        base_url=None,
    )
    sess.add(k)
    await sess.flush()
    return k.id


async def test_planner_path_resolves_workspace_key_not_legacy():
    """
    Given: workspace WS has an active scoped key; there is NO legacy-global key.
    When:  TaskOrchestrator._plan runs for a task in WS.
    Then:  the api_key handed to generate_plan is WS's key — not "" and not a
           legacy-global fallback (which does not exist and would raise).
    """
    from backend.database import async_session
    from sqlalchemy import delete
    from backend.models import APIKey
    from backend.services.task.task_orchestrator import TaskOrchestrator
    from backend.services.task.task_planner_schema import TaskPlan, TaskStepProposal

    # Isolate: remove any legacy (workspace_id IS NULL) key so a wrong-path
    # regression would hit "No active API key found for scope 'legacy-global'".
    async with async_session() as sess:
        removed_legacy = (await sess.execute(
            delete(APIKey).where(APIKey.workspace_id.is_(None))
        )).rowcount
        await _create_key(sess, WS, "planner-ws-key", WS_KEY)
        await sess.commit()

    # Capture what generate_plan receives, without calling a real LLM.
    seen = {}

    async def fake_generate_plan(*, maeos, goal, task_id, context, api_key, provider):
        seen["api_key"] = api_key
        seen["provider"] = provider
        return TaskPlan(
            task_id=task_id,
            title="test plan",
            description=goal,
            steps=[TaskStepProposal(order=1, teammate_id="tm-x", objective=goal)],
        )

    orch = TaskOrchestrator(runtime=None)
    try:
        with patch(
            "backend.services.task.task_planner_driver.generate_plan",
            new=fake_generate_plan,
        ), patch(
            "backend.routes.maeos._get_maeos",
            new=AsyncMock(return_value=object()),
        ):
            async with async_session() as db:
                dag = await orch._plan(
                    goal="write a haiku",
                    task_id="planner-test-task",
                    workspace_id=WS,
                    db=db,
                )

        assert seen.get("api_key") == WS_KEY, (
            f"planner path did not propagate the workspace key; "
            f"got {seen.get('api_key')!r} (regression → legacy-global path)"
        )
        assert dag is not None and dag.nodes, "planner produced no DAG"
        print(f"  ✓ planner path propagated ws key: {seen['api_key'][:12]}...")
    finally:
        async with async_session() as sess:
            await sess.execute(delete(APIKey).where(APIKey.workspace_id == WS))
            await sess.commit()


async def test_planner_path_missing_key_does_not_borrow_legacy():
    """
    Given: workspace WS has NO key, and NO legacy-global key exists.
    When:  TaskOrchestrator._plan runs for a task in WS.
    Then:  it raises (no silent cross-scope borrow) rather than resolving a key.
    """
    from backend.database import async_session
    from sqlalchemy import delete
    from backend.models import APIKey
    from backend.services.task.task_orchestrator import TaskOrchestrator

    async with async_session() as sess:
        await sess.execute(delete(APIKey).where(APIKey.workspace_id.is_(None)))
        await sess.execute(delete(APIKey).where(APIKey.workspace_id == WS))
        await sess.commit()

    orch = TaskOrchestrator(runtime=None)
    with pytest.raises(RuntimeError, match="no active API key"):
        async with async_session() as db:
            await orch._plan(
                goal="write a haiku",
                task_id="planner-test-task-nokey",
                workspace_id=WS,
                db=db,
            )
    print("  ✓ planner path with no key raises, does not borrow legacy-global")
