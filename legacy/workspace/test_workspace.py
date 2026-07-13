"""
test_workspace.py — Workspace Layer Tests

Tests:
  1. Workspace creation and management
  2. Thread creation and status transitions
  3. Message adding and retrieval
  4. Human-in-the-loop (interrupt, modify, respond)
  5. Context read/write
  6. Memory recording and querying
  7. Timeline reconstruction
  8. Full integration flow
"""

import sys
import os
import asyncio
import pytest

sys.path.insert(0, os.path.dirname(__file__).replace("/tests", ""))
os.chdir(os.path.dirname(__file__).replace("/tests", ""))

from services.workspace import (
    Workspace, WorkspaceManager, WorkspaceStatus,
    ThreadStatus, get_workspace_manager,
)
from services.workspace_memory import (
    WorkspaceMemory, MemoryType,
)
from services.collaboration import get_event_bus, get_context_store


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def event_bus():
    return get_event_bus()


@pytest.fixture
def workspace_manager(event_bus):
    mgr = WorkspaceManager()
    yield mgr



# ═══════════════════════════════════════════════════════════
# Test 1: Workspace Creation
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_workspace(workspace_manager):
    """Test workspace creation."""
    ws = await workspace_manager.create_workspace(
        title="Test Project",
        description="A test workspace"
    )
    
    assert ws.id is not None
    assert ws.title == "Test Project"
    assert ws.status == WorkspaceStatus.ACTIVE
    assert ws.threads == []
    assert ws.messages == []


@pytest.mark.asyncio
async def test_list_workspaces(workspace_manager):
    """Test listing workspaces."""
    await workspace_manager.create_workspace(title="WS1")
    await workspace_manager.create_workspace(title="WS2")
    
    workspaces = workspace_manager.list_workspaces()
    assert len(workspaces) == 2


@pytest.mark.asyncio
async def test_get_workspace(workspace_manager):
    """Test getting workspace by ID."""
    ws = await workspace_manager.create_workspace(title="Test")
    retrieved = workspace_manager.get_workspace(ws.id)
    
    assert retrieved is not None
    assert retrieved.id == ws.id
    assert retrieved.title == "Test"


@pytest.mark.asyncio
async def test_archive_workspace(workspace_manager):
    """Test archiving workspace."""
    ws = await workspace_manager.create_workspace(title="To Archive")
    ok = await workspace_manager.archive_workspace(ws.id)
    
    assert ok is True
    assert ws.status == WorkspaceStatus.ARCHIVED


# ═══════════════════════════════════════════════════════════
# Test 2: Thread Management
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_thread(workspace_manager):
    """Test thread creation."""
    ws = await workspace_manager.create_workspace(title="Test")
    thread = await ws.create_thread(title="Implement auth")
    
    assert thread.id is not None
    assert thread.workspace_id == ws.id
    assert thread.title == "Implement auth"
    assert thread.status == ThreadStatus.OPEN


@pytest.mark.asyncio
async def test_thread_status_transition(workspace_manager):
    """Test thread status transitions."""
    ws = await workspace_manager.create_workspace(title="Test")
    thread = await ws.create_thread(title="Task")
    
    ok = await ws.update_thread_status(thread.id, ThreadStatus.IN_PROGRESS)
    assert ok is True
    assert thread.status == ThreadStatus.IN_PROGRESS
    
    ok = await ws.update_thread_status(thread.id, ThreadStatus.COMPLETED, "done")
    assert ok is True
    assert thread.status == ThreadStatus.COMPLETED


@pytest.mark.asyncio
async def test_list_active_threads(workspace_manager):
    """Test listing active threads."""
    ws = await workspace_manager.create_workspace(title="Test")
    t1 = await ws.create_thread(title="Active 1")
    t2 = await ws.create_thread(title="Active 2")
    t3 = await ws.create_thread(title="To Complete")
    
    await ws.update_thread_status(t3.id, ThreadStatus.COMPLETED)
    
    active = ws.active_threads
    assert len(active) == 2
    assert all(t.status in (ThreadStatus.OPEN, ThreadStatus.IN_PROGRESS, ThreadStatus.WAITING_HUMAN) for t in active)


# ═══════════════════════════════════════════════════════════
# Test 3: Messages
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_add_message(workspace_manager):
    """Test adding messages to a thread."""
    ws = await workspace_manager.create_workspace(title="Test")
    thread = await ws.create_thread(title="Chat")
    
    msg = await ws.add_message(
        thread_id=thread.id,
        participant_id="user_1",
        participant_type="human",
        content="Hello, please help with auth",
    )
    
    assert msg.id is not None
    assert msg.thread_id == thread.id
    assert msg.participant_type == "human"
    assert msg.content == "Hello, please help with auth"


@pytest.mark.asyncio
async def test_get_thread_messages(workspace_manager):
    """Test retrieving thread messages."""
    ws = await workspace_manager.create_workspace(title="Test")
    thread = await ws.create_thread(title="Chat")
    
    await ws.add_message(thread.id, "user_1", "human", "Message 1")
    await ws.add_message(thread.id, "agent_1", "agent", "Response 1")
    await ws.add_message(thread.id, "user_1", "human", "Message 2")
    
    messages = ws.get_thread_messages(thread.id)
    assert len(messages) == 3
    assert messages[0].content == "Message 1"
    assert messages[1].content == "Response 1"


# ═══════════════════════════════════════════════════════════
# Test 4: Human-in-the-Loop
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_interrupt(workspace_manager):
    """Test interrupting a thread."""
    ws = await workspace_manager.create_workspace(title="Test")
    thread = await ws.create_thread(title="Task")
    await ws.update_thread_status(thread.id, ThreadStatus.IN_PROGRESS)
    
    await ws.interrupt(thread.id, "Need to change approach")
    
    assert ws.is_interrupted() is True
    assert thread.status == ThreadStatus.PAUSED


@pytest.mark.asyncio
async def test_modify_task(workspace_manager):
    """Test modifying a task."""
    ws = await workspace_manager.create_workspace(title="Test")
    thread = await ws.create_thread(title="Task")
    
    await ws.modify_task(thread.id, "Use JWT instead of session")
    
    mod = await ws.get_modification()
    assert mod is not None
    assert mod["thread_id"] == thread.id
    assert mod["modification"] == "Use JWT instead of session"


@pytest.mark.asyncio
async def test_human_input_response(workspace_manager):
    """Test human input request/response flow."""
    ws = await workspace_manager.create_workspace(title="Test")
    thread = await ws.create_thread(title="Task")
    
    # Simulate async human response
    async def simulate_human_response():
        await asyncio.sleep(0.1)
        await ws.provide_human_input("Use OAuth2")
    
    # Start human input request
    task = asyncio.create_task(
        ws.request_human_input(thread.id, "Which auth method?")
    )
    
    # Simulate human responding
    asyncio.create_task(simulate_human_response())
    
    response = await task
    assert response == "Use OAuth2"


# ═══════════════════════════════════════════════════════════
# Test 5: Context
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_context_read_write(workspace_manager):
    """Test context read/write."""
    ws = await workspace_manager.create_workspace(title="Test")
    
    await ws.write_context("project_type", "web_app", teammate_id="system")
    await ws.write_context("framework", "FastAPI", teammate_id="planner")
    
    assert ws.read_context("project_type") == "web_app"
    assert ws.read_context("framework") == "FastAPI"


@pytest.mark.asyncio
async def test_context_timeline(workspace_manager):
    """Test context timeline."""
    ws = await workspace_manager.create_workspace(title="Test")
    
    await ws.write_context("key1", "value1", teammate_id="system")
    await ws.write_context("key1", "value2", teammate_id="planner")
    await ws.write_context("key2", "other", teammate_id="executor")
    
    timeline = ws.get_context_timeline()
    assert len(timeline) == 3


# ═══════════════════════════════════════════════════════════
# Test 7: Timeline
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_workspace_timeline(workspace_manager):
    """Test full workspace timeline."""
    ws = await workspace_manager.create_workspace(title="Timeline Test")
    thread = await ws.create_thread(title="Task")
    
    await ws.add_message(thread.id, "user", "human", "Start task")
    await ws.write_context("status", "started", teammate_id="system")
    await ws.add_message(thread.id, "agent", "agent", "Working on it")
    
    timeline = ws.get_timeline()
    assert len(timeline) >= 3  # messages + context updates


# ═══════════════════════════════════════════════════════════
# Test 8: Full Integration Flow
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_full_collaboration_flow(workspace_manager):
    """
    Full flow:
    1. Create workspace
    2. Create thread
    3. Human sends message
    4. Agent responds
    5. Human interrupts with modification
    6. Agent adapts
    7. Complete thread
    """
    # 1. Create workspace
    ws = await workspace_manager.create_workspace(
        title="Auth System",
        description="Build authentication for web app"
    )
    
    # 2. Create thread
    thread = await ws.create_thread(
        title="Implement JWT auth",
        participants=[
            {"id": "user_1", "type": "human", "name": "Developer"},
            {"id": "planner", "type": "teammate", "name": "Planner"},
        ]
    )
    await ws.update_thread_status(thread.id, ThreadStatus.IN_PROGRESS)
    
    # 3. Human sends message
    await ws.add_message(
        thread.id, "user_1", "human",
        "Please implement JWT authentication with refresh tokens"
    )
    
    # 4. Agent responds (simulated)
    await ws.add_message(
        thread.id, "planner", "agent",
        "Plan: 1) Login endpoint 2) Token refresh 3) Logout"
    )
    
    # 5. Human interrupts with modification
    await ws.interrupt(thread.id, "Add rate limiting")
    await ws.modify_task(thread.id, "Add rate limiting to login endpoint")
    
    # Clear interrupt and continue
    ws.clear_interrupt()
    await ws.update_thread_status(thread.id, ThreadStatus.IN_PROGRESS)
    
    # 7. Complete
    await ws.update_thread_status(thread.id, ThreadStatus.COMPLETED)
    
    # Verify
    assert thread.status == ThreadStatus.COMPLETED
    # 2 user messages + 1 interruption + 1 revision = 4
    assert len(ws.get_thread_messages(thread.id)) == 4
    
    # Check timeline
    timeline = ws.get_timeline()
    assert len(timeline) >= 4  # 2 messages + context updates


# ═══════════════════════════════════════════════════════════
# Test 9: Workspace Stats
# ═══════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_workspace_stats(workspace_manager):
    """Test workspace statistics."""
    ws = await workspace_manager.create_workspace(title="Stats Test")
    await ws.create_thread(title="T1")
    await ws.create_thread(title="T2")
    
    stats = workspace_manager.stats()
    assert stats["total_workspaces"] == 1
    assert stats["total_threads"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
