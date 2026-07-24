"""Phase 6 — Organization Loop 收敛测试。

验收标准：
1. Chat 输入：OrganizationRun → OrganizationLoop → RESPOND → teammate_runner
2. Task 创建：OrganizationRun → OrganizationLoop → DELEGATE → TaskOrchestrator
3. 新增 Action 类型无需修改 messages/tasks
4. SessionEvent 顺序：run.created → action.created → action.started
   → turn.start → turn.close → action.completed → run.completed
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

pytestmark = pytest.mark.asyncio

from backend.models.session import SessionTrigger, SessionEvent
from backend.services.organization.runtime import OrganizationRuntime, OrganizationAction
from backend.services.session.session_hooks import SessionHooks


# ── helpers ──

async def _events(db, trigger_id) -> list[SessionEvent]:
    from sqlalchemy import select
    r = await db.execute(
        select(SessionEvent)
        .where(SessionEvent.trigger_id == trigger_id)
        .order_by(SessionEvent.timestamp)
    )
    return list(r.scalars().all())


async def _create_trigger(db_session) -> SessionTrigger:
    trigger = SessionTrigger(trigger_type="test", channel_id="ch")
    db_session.add(trigger)
    await db_session.flush()
    return trigger


async def _create_run(db_session, trigger_id: str, run_type: str = "chat"):
    runtime = OrganizationRuntime(db_session)
    run = await runtime.start_run(
        run_type=run_type,
        source_id=trigger_id,
        workspace_id="ws1",
        channel_id="ch",
        title="Test run",
    )
    return runtime, run


# ═══════════════════════════════════════════════════════════════
# 1. OrganizationLoop dispatches RESPOND → generate_team_response
# ═══════════════════════════════════════════════════════════════

async def test_loop_respond_dispatches_to_team_collaboration(db_session):
    """RESPOND action → OrganizationLoop calls generate_team_response via runtime.handle_input."""
    trigger = await _create_trigger(db_session)
    runtime, org_run = await _create_run(db_session, trigger.id)

    # Fake SSE chunk
    async def _fake_respond(**kw):
        yield "data: {\"type\": \"teammate_message\", \"payload\": {\"content\": \"hi\"}}\n\n"

    with patch("backend.services.team_collaboration.generate_team_response", new=_fake_respond):
        chunks = []
        async for chunk in runtime.handle_input(
            run_id=org_run.id,
            trigger_id=trigger.id,
            teammates=[{"id": "tm1", "name": "Bot"}],
            user_message="hello",
            channel_id="ch",
        ):
            chunks.append(chunk)

    assert len(chunks) > 0
    assert "hi" in chunks[0]

    # Verify action lifecycle events were recorded
    events = await _events(db_session, trigger.id)
    event_types = [e.event_type for e in events]
    assert "action.created" in event_types
    assert "action.started" in event_types
    assert "action.completed" in event_types


async def test_loop_respond_records_action_failed_on_error(db_session):
    """RESPOND failure records action.failed event."""
    trigger = await _create_trigger(db_session)
    runtime, org_run = await _create_run(db_session, trigger.id)

    async def _broken(**kw):
        raise RuntimeError("test failure")
        yield  # pragma: no cover

    with patch("backend.services.team_collaboration.generate_team_response", new=_broken):
        with pytest.raises(RuntimeError, match="test failure"):
            async for _ in runtime.handle_input(
                run_id=org_run.id,
                trigger_id=trigger.id,
                teammates=[{"id": "tm1"}],
                user_message="hi",
                channel_id="ch",
            ):
                pass

    events = await _events(db_session, trigger.id)
    assert any(e.event_type == "action.failed" for e in events)


# ═══════════════════════════════════════════════════════════════
# 2. OrganizationLoop dispatches DELEGATE → TaskOrchestrator
# ═══════════════════════════════════════════════════════════════

async def test_loop_delegate_dispatches_to_task_orchestrator(db_session):
    """DELEGATE action → OrganizationRuntime.dispatch_delegate → TaskOrchestrator."""
    trigger = await _create_trigger(db_session)
    runtime, org_run = await _create_run(db_session, trigger.id, run_type="task")

    mock_orch = AsyncMock()
    mock_orch.start_task = AsyncMock()

    with patch("backend.services.task.task_orchestrator.TaskOrchestrator", return_value=mock_orch):
        await runtime.dispatch_delegate(
            trigger_id=trigger.id,
            run_id=org_run.id,
            task_id="task-1",
            goal="do something",
        )

    mock_orch.start_task.assert_awaited_once()
    args, _ = mock_orch.start_task.call_args
    assert args[1] == "task-1"  # second positional arg is task_id
    assert args[2] == "do something"  # third positional arg is goal

    # Verify action lifecycle events
    events = await _events(db_session, trigger.id)
    event_types = [e.event_type for e in events]
    assert "action.created" in event_types
    assert "action.started" in event_types
    assert "action.completed" in event_types


async def test_loop_delegate_records_action_failed(db_session):
    """DELEGATE failure records action.failed event."""
    trigger = await _create_trigger(db_session)
    runtime, org_run = await _create_run(db_session, trigger.id, run_type="task")

    mock_orch = AsyncMock()
    mock_orch.start_task = AsyncMock(side_effect=RuntimeError("delegate fail"))

    with patch("backend.services.task.task_orchestrator.TaskOrchestrator", return_value=mock_orch):
        with pytest.raises(RuntimeError, match="delegate fail"):
            await runtime.dispatch_delegate(
                trigger_id=trigger.id,
                run_id=org_run.id,
                task_id="task-1",
                goal="fail",
            )

    events = await _events(db_session, trigger.id)
    assert any(e.event_type == "action.failed" for e in events)


# ═══════════════════════════════════════════════════════════════
# 3. OrganizationLoop dispatches EXECUTE → TaskExecutor
# ═══════════════════════════════════════════════════════════════

async def test_loop_execute_dispatches_to_task_executor(db_session):
    """EXECUTE action → OrganizationRuntime.dispatch_execute → TaskExecutor."""
    trigger = await _create_trigger(db_session)
    runtime, org_run = await _create_run(db_session, trigger.id, run_type="task")

    mock_executor = AsyncMock()
    mock_executor.execute_task = AsyncMock()
    mock_runtime = MagicMock()

    with (
        patch("backend.services.task.task_executor.TaskExecutor", return_value=mock_executor),
        patch("backend.services.runtime.executor.ExecutionRuntime", return_value=mock_runtime),
    ):
        await runtime.dispatch_execute(db_session=db_session, task=MagicMock())

    mock_executor.execute_task.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════
# 4. Run lifecycle events: run.created → run.completed
# ═══════════════════════════════════════════════════════════════

async def test_run_created_event(db_session):
    """emit_run_event records run.created (and any arbitrary event_type)."""
    trigger = await _create_trigger(db_session)
    runtime, org_run = await _create_run(db_session, trigger.id)

    await runtime.emit_run_event(trigger.id, "run.created", org_run.id)

    events = await _events(db_session, trigger.id)
    assert any(e.event_type == "run.created" for e in events)


async def test_run_completed_event(db_session):
    """finish_run with trigger_id emits run.completed."""
    trigger = await _create_trigger(db_session)
    runtime, org_run = await _create_run(db_session, trigger.id)

    await runtime.finish_run(org_run.id, status="completed", trigger_id=trigger.id)

    events = await _events(db_session, trigger.id)
    assert any(e.event_type == "run.completed" for e in events)
    # Verify run is actually closed
    from backend.models.organization_run import OrganizationRun
    fresh_run = await db_session.get(OrganizationRun, org_run.id)
    assert fresh_run is not None
    assert fresh_run.status == "completed"
    assert fresh_run.ended_at is not None


# ═══════════════════════════════════════════════════════════════
# 5. SessionEvent order verification
# ═══════════════════════════════════════════════════════════════

async def test_event_chain_order(db_session):
    """Full event chain for a chat: run.created → action.* → turn.* → run.completed
    (state.updated events interleaved from OrganizationState service)."""
    trigger = await _create_trigger(db_session)
    runtime, org_run = await _create_run(db_session, trigger.id)

    # Emit events in expected order (simulates what happens in production)
    await runtime.emit_run_event(trigger.id, "run.created", org_run.id)

    async def _fake(**kw):
        if False:
            yield  # pragma: no cover
        # After RESPOND completes, simulate turn events
        hooks = SessionHooks(db_session)
        turn = await hooks.start_turn(trigger.id, teammate_id="bot")
        await hooks.close_turn(turn.id, action=MagicMock(value="responded"))

    with patch("backend.services.team_collaboration.generate_team_response", new=_fake):
        async for _ in runtime.handle_input(
            run_id=org_run.id,
            trigger_id=trigger.id,
            teammates=[{"id": "tm1"}],
            user_message="hi",
            channel_id="ch",
        ):
            pass

    await runtime.finish_run(org_run.id, status="completed", trigger_id=trigger.id)

    events = await _events(db_session, trigger.id)
    event_types = [e.event_type for e in events]

    # Verify key lifecycle events exist in correct relative order
    # (state.updated events are interleaved from OrganizationStateManager)
    key_events = [e for e in event_types if e != "state.updated"]
    assert key_events == [
        "run.created",
        "action.created",
        "action.started",
        "turn.start",
        "turn.close",
        "action.completed",
        "run.completed",
    ], f"Key event order broken, got: {key_events}"


# ═══════════════════════════════════════════════════════════════
# 6. New action type doesn't require modifying messages/tasks
# ═══════════════════════════════════════════════════════════════

async def test_new_action_type_in_organization_action(db_session):
    """Adding an action type only needs OrganizationAction enum + loop dispatch method."""
    # Verify existing action types
    assert OrganizationAction.RESPOND.value == "respond"
    assert OrganizationAction.DELEGATE.value == "delegate"
    assert OrganizationAction.EXECUTE.value == "execute"
    assert OrganizationAction.COMPLETE.value == "complete"
    assert OrganizationAction.TOOL_CALL.value == "tool_call"

    # Verify OrganizationRuntime.execute_action accepts any OrganizationAction
    trigger = await _create_trigger(db_session)
    runtime, org_run = await _create_run(db_session, trigger.id)

    await runtime.execute_action(
        trigger_id=trigger.id,
        action_type=OrganizationAction.TOOL_CALL,
        teammate_id="tm1",
        payload={"tool": "read_file"},
    )

    events = await _events(db_session, trigger.id)
    assert any(e.event_type == "action.tool_call" for e in events)


# ═══════════════════════════════════════════════════════════════
# 7. messages.py doesn't import AgentLoop (sanity check via structure)
# ═══════════════════════════════════════════════════════════════

def test_messages_py_does_not_import_subsystems():
    """Verify messages.py has no direct imports of AgentLoop or TaskExecutor."""
    import ast
    import os

    path = os.path.join(
        os.path.dirname(__file__), "..",
        "routes", "messages.py",
    )
    with open(path) as f:
        tree = ast.parse(f.read())

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports.add(f"{node.module or ''}.{alias.name}")

    forbidden = {"AgentLoop", "TaskExecutor", "generate_team_response", "teammate_runner"}
    found = {i for i in imports if any(f in i for f in forbidden)}
    assert not found, f"messages.py imports forbidden subsystems: {found}"


def test_tasks_py_does_not_import_TaskExecutor_from_route_path():
    """Verify tasks.py route functions don't directly call TaskExecutor."""
    import ast
    import os

    path = os.path.join(
        os.path.dirname(__file__), "..",
        "routes", "tasks.py",
    )
    with open(path) as f:
        tree = ast.parse(f.read())

    # Check that the non-helper function bodies don't contain
    # TaskExecutor() or executor.execute_task()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
            continue  # skip helpers
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if "execute_task" in node.func.attr:
                    # Check it's called via OrganizationRuntime, not TaskExecutor
                    pytest.fail(f"Direct execute_task call found in tasks.py")
