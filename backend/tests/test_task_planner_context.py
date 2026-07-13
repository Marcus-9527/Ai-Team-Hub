"""
test_task_planner_context.py — Phase B: Planner Context Integration tests.

Coverage:
  1. PlannerContext — creation, to_dict, to_prompt_section, empty
  2. PlannerContextBuilder — build with task only (no extra sources)
  3. PlannerContextBuilder — build with channel messages
  4. PlannerContextBuilder — build with task history
  5. PlannerContextBuilder — build with workspace memory
  6. PlannerContextBuilder — build with global rules
  7. PlannerContextBuilder — build with file metadata
  8. PlannerContextBuilder — token limit enforcement (truncation)
  9. PlannerContextBuilder — all sources combined
  10. build_planner_context — convenience function
  11. Driver integration — context passed to generate_plan
  12. Edge cases
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.task.task_planner_context import (
    PlannerContext,
    PlannerContextBuilder,
    build_planner_context,
    MAX_CONTEXT_TOKENS,
    _estimate_tokens,
    _truncate,
)
from backend.services.task.task_planner_driver import generate_plan
from backend.services.task.task_planner_schema import TaskPlan, TaskStepProposal


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def fake_task():
    """Create a fake TaskModel with the fields PlannerContextBuilder needs."""
    task = MagicMock()
    task.id = "task-001"
    task.title = "Build Auth System"
    task.description = "Implement JWT-based authentication with refresh tokens"
    task.intent = "task"
    task.priority = 2
    task.created_by = "user:alice"
    task.channel_id = "channel-001"
    task.workspace_id = "workspace-001"
    task.status = "CREATED"
    return task


@pytest.fixture
def fake_task_no_extra():
    """Task with no channel_id / workspace_id (no extra context sources)."""
    task = MagicMock()
    task.id = "task-002"
    task.title = "Simple Task"
    task.description = "Just a test"
    task.intent = ""
    task.priority = 1
    task.created_by = "system"
    task.channel_id = None
    task.workspace_id = None
    task.status = "CREATED"
    return task


def _make_db_execute_result(items=None):
    """Create a mock result for db.execute() that returns given items via .scalars().all()."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = items or []
    return r


def _make_db():
    """Create a properly configured AsyncMock(db) that returns empty results by default."""
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = _make_db_execute_result()
    return db


def _make_db_with_side_effect(results):
    """Create an AsyncMock(db) whose execute returns different results per call."""
    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = results
    return db


# ═══════════════════════════════════════════════════════════════
# 1. PlannerContext unit tests
# ═══════════════════════════════════════════════════════════════

class TestPlannerContext:
    def test_default_empty(self):
        """Default context has all empty sections."""
        ctx = PlannerContext()
        assert ctx.task_context == ""
        assert ctx.memory_context == ""
        assert ctx.channel_context == ""
        assert ctx.workspace_context == ""
        assert ctx.global_context == ""
        assert ctx.file_context == ""

    def test_to_dict(self):
        """to_dict serializes all main fields."""
        ctx = PlannerContext(
            task_context="Task X",
            memory_context="Step 1 done",
            total_chars=20,
            truncated=False,
        )
        d = ctx.to_dict()
        assert d["task_context"] == "Task X"
        assert d["memory_context"] == "Step 1 done"
        assert d["total_chars"] == 20
        assert d["truncated"] is False

    def test_to_prompt_section_ordering(self):
        """to_prompt_section orders by priority (task > history > channel > ...)."""
        ctx = PlannerContext(
            task_context="Goal: Build X",
            memory_context="Step 1 complete",
            channel_context="Recent chat",
            workspace_context="Workspace decisions",
            global_context="Use async/await",
        )
        prompt = ctx.to_prompt_section()
        task_pos = prompt.index("[TASK GOAL]")
        history_pos = prompt.index("[TASK HISTORY]")
        channel_pos = prompt.index("[CHANNEL CONTEXT]")
        assert task_pos < history_pos < channel_pos

    def test_to_prompt_section_omits_empty(self):
        """Empty sections are omitted from prompt."""
        ctx = PlannerContext(task_context="Goal X")
        prompt = ctx.to_prompt_section()
        assert "[TASK GOAL]" in prompt
        assert "[TASK HISTORY]" not in prompt
        assert "[CHANNEL CONTEXT]" not in prompt

    def test_truncated_note(self):
        """Truncated contexts include a note."""
        ctx = PlannerContext(task_context="X", truncated=True)
        prompt = ctx.to_prompt_section()
        assert "truncated" in prompt

    def test_empty_factory(self):
        """empty() returns a blank context."""
        ctx = PlannerContext.empty()
        assert isinstance(ctx, PlannerContext)
        assert ctx.task_context == ""


# ═══════════════════════════════════════════════════════════════
# 2. PlannerContextBuilder — task only
# ═══════════════════════════════════════════════════════════════

class TestBuilderTaskOnly:
    @pytest.mark.asyncio
    async def test_build_with_task_only(self, fake_task_no_extra):
        """Builder works with just a task (no channel/workspace)."""
        db = _make_db()

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task_no_extra)

        assert fake_task_no_extra.title in ctx.task_context
        assert fake_task_no_extra.description in ctx.task_context
        assert ctx.memory_context == ""
        assert ctx.channel_context == ""
        assert ctx.workspace_context == ""
        assert ctx.global_context == ""
        assert ctx.file_context == ""
        assert ctx.total_chars > 0
        assert ctx.truncated is False

    @pytest.mark.asyncio
    async def test_sources_list_empty(self, fake_task_no_extra):
        """Sources list contains only 'task' when no extras."""
        db = _make_db()

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task_no_extra)

        assert "task" in ctx.sources
        assert "history" not in ctx.sources
        assert "channel" not in ctx.sources
        assert len(ctx.sources) == 1

    @pytest.mark.asyncio
    async def test_to_dict_usable_for_generate_plan(self, fake_task_no_extra):
        """to_dict() output can be passed as generate_plan context."""
        db = _make_db()

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task_no_extra)
        ctx_dict = ctx.to_dict()

        assert isinstance(ctx_dict, dict)
        assert "task_context" in ctx_dict
        assert "channel_context" in ctx_dict


# ═══════════════════════════════════════════════════════════════
# 3. PlannerContextBuilder — with channel messages
# ═══════════════════════════════════════════════════════════════

class TestBuilderChannelMessages:
    @pytest.mark.asyncio
    async def test_with_channel_messages(self, fake_task):
        """Channel messages are included in context."""
        msgs = [
            MagicMock(role="user", content="Build me auth"),
            MagicMock(role="ai", content="I'll help with auth"),
        ]
        db = _make_db_with_side_effect([
            _make_db_execute_result(),  # steps query (empty)
            _make_db_execute_result(msgs),  # messages query
        ])

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task)

        assert "Build me auth" in ctx.channel_context
        assert "I'll help with auth" in ctx.channel_context
        assert "channel" in ctx.sources

    @pytest.mark.asyncio
    async def test_no_channel_messages(self, fake_task_no_extra):
        """No channel context when task has no channel_id."""
        db = _make_db()

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task_no_extra)

        assert ctx.channel_context == ""

    @pytest.mark.asyncio
    async def test_channel_messages_capped(self, fake_task):
        """Messages are collected (limited by SQL query)."""
        many_msgs = [MagicMock(role="user", content=f"Msg {i}") for i in range(40)]
        db = _make_db_with_side_effect([
            _make_db_execute_result(),  # steps query (empty)
            _make_db_execute_result(many_msgs),  # messages query
        ])

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task)

        assert "Msg 0" in ctx.channel_context
        assert "channel" in ctx.sources


# ═══════════════════════════════════════════════════════════════
# 4. PlannerContextBuilder — with task history
# ═══════════════════════════════════════════════════════════════

class TestBuilderTaskHistory:
    @pytest.mark.asyncio
    async def test_with_completed_steps(self, fake_task):
        """Completed steps appear in memory_context."""
        steps = [
            MagicMock(order=1, objective="Research", output="Found lib X",
                      status="COMPLETED"),
            MagicMock(order=2, objective="Implement", output="Done",
                      status="COMPLETED"),
        ]
        db = _make_db_with_side_effect([
            _make_db_execute_result(steps),  # steps query
            _make_db_execute_result(),  # messages query (empty)
        ])

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task)

        assert "Research" in ctx.memory_context
        assert "Found lib X" in ctx.memory_context
        assert "Implement" in ctx.memory_context
        assert "history" in ctx.sources

    @pytest.mark.asyncio
    async def test_no_steps(self, fake_task_no_extra):
        """No memory context when no steps exist."""
        db = _make_db()

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task_no_extra)

        assert ctx.memory_context == ""


# ═══════════════════════════════════════════════════════════════
# 5. PlannerContextBuilder — with workspace memory
# ═══════════════════════════════════════════════════════════════

class TestBuilderWorkspaceMemory:
    @pytest.mark.asyncio
    async def test_workspace_memory_available(self, fake_task):
        """Workspace memory is collected when available."""
        db = _make_db()

        fake_entry = MagicMock()
        fake_entry.memory_type = "decision"
        fake_entry.actor = "system"
        fake_entry.content = "Use async/await for all I/O"

        with patch(
            "backend.services.workspace_memory.WorkspaceMemory"
        ) as MockWM:
            fake_wm = MockWM.return_value
            fake_wm.get_all.return_value = [fake_entry]

            builder = PlannerContextBuilder()
            ctx = await builder.build(db, fake_task)

            assert "Use async/await" in ctx.workspace_context
            assert "workspace" in ctx.sources

    @pytest.mark.asyncio
    async def test_workspace_memory_unavailable(self, fake_task_no_extra):
        """No workspace context when task has no workspace_id."""
        db = _make_db()

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task_no_extra)

        assert ctx.workspace_context == ""

    @pytest.mark.asyncio
    async def test_workspace_memory_fallback_graceful(self, fake_task):
        """Graceful fallback when workspace memory errors."""
        db = _make_db()

        with patch(
            "backend.services.workspace_memory.WorkspaceMemory",
            side_effect=ImportError("No workspace module"),
        ):
            builder = PlannerContextBuilder()
            ctx = await builder.build(db, fake_task)

            assert ctx.workspace_context == ""
            assert "workspace" not in ctx.sources


# ═══════════════════════════════════════════════════════════════
# 6. PlannerContextBuilder — with global rules
# ═══════════════════════════════════════════════════════════════

class TestBuilderGlobalRules:
    @pytest.mark.asyncio
    async def test_with_global_rules(self, fake_task_no_extra):
        """Global rules appear in global_context."""
        db = _make_db()

        builder = PlannerContextBuilder()
        ctx = await builder.build(
            db, fake_task_no_extra,
            global_rules=["Use async/await", "Prefer FastAPI"],
        )

        assert "Use async/await" in ctx.global_context
        assert "Prefer FastAPI" in ctx.global_context
        assert "global" in ctx.sources

    @pytest.mark.asyncio
    async def test_no_global_rules(self, fake_task_no_extra):
        """No global context when rules are empty."""
        db = _make_db()

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task_no_extra)

        assert ctx.global_context == ""


# ═══════════════════════════════════════════════════════════════
# 7. PlannerContextBuilder — with file metadata
# ═══════════════════════════════════════════════════════════════

class TestBuilderFileMetadata:
    @pytest.mark.asyncio
    async def test_with_files(self, fake_task):
        """File metadata appears in file_context."""
        db = _make_db_with_side_effect([
            _make_db_execute_result(),  # steps (empty)
            _make_db_execute_result(),  # messages (empty)
            _make_db_execute_result([
                MagicMock(filename="auth.py", file_type="py", size="2048", status="ready"),
            ]),  # files query
        ])

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task)

        assert "auth.py" in ctx.file_context
        assert "files" in ctx.sources

    @pytest.mark.asyncio
    async def test_no_files(self, fake_task_no_extra):
        """No file context when no channel_id."""
        db = _make_db()

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task_no_extra)

        assert ctx.file_context == ""


# ═══════════════════════════════════════════════════════════════
# 8. Token limit enforcement
# ═══════════════════════════════════════════════════════════════

class TestTokenLimit:
    @pytest.mark.asyncio
    async def test_fits_in_budget(self, fake_task_no_extra):
        """No truncation when total fits in budget."""
        db = _make_db()

        builder = PlannerContextBuilder(max_tokens=2000)
        ctx = await builder.build(db, fake_task_no_extra)

        assert ctx.truncated is False

    @pytest.mark.asyncio
    async def test_truncates_when_over_budget(self, fake_task_no_extra):
        """Truncation kicks in when context exceeds max_tokens."""
        db = _make_db()

        builder = PlannerContextBuilder(max_tokens=5)  # ~20 chars
        ctx = await builder.build(
            db, fake_task_no_extra,
            global_rules=["Rule " + "x" * 100],
        )

        assert ctx.truncated or ctx.total_chars > 0

    @pytest.mark.asyncio
    async def test_lowest_priority_dropped_first(self, fake_task):
        """Lowest priority sections are dropped before task context."""
        db = _make_db_with_side_effect([
            _make_db_execute_result([
                MagicMock(order=1, objective="X" * 2000, output="Y" * 2000,
                          status="COMPLETED"),
            ]),  # steps
            _make_db_execute_result([
                MagicMock(role="user", content="Z" * 2000),
            ]),  # messages
            _make_db_execute_result([
                MagicMock(filename="big.py", file_type="py", size="999999"),
            ]),  # files
        ])

        builder = PlannerContextBuilder(max_tokens=50)
        ctx = await builder.build(
            db, fake_task,
            global_rules=["A" * 500],
        )

        # Task context should survive
        assert fake_task.title in ctx.task_context
        assert ctx.truncated


# ═══════════════════════════════════════════════════════════════
# 9. All sources combined
# ═══════════════════════════════════════════════════════════════

class TestBuilderAllSources:
    @pytest.mark.asyncio
    async def test_all_sources_combined(self, fake_task):
        """All sources are combined when available."""
        db = _make_db_with_side_effect([
            _make_db_execute_result([
                MagicMock(order=1, objective="Research", output="Findings",
                          status="COMPLETED"),
            ]),  # steps
            _make_db_execute_result([
                MagicMock(role="user", content="Need auth"),
            ]),  # messages
            _make_db_execute_result([
                MagicMock(filename="auth.py", file_type="py", size="1024"),
            ]),  # files
        ])

        with patch(
            "backend.services.workspace_memory.WorkspaceMemory"
        ) as MockWM:
            fake_entry = MagicMock()
            fake_entry.memory_type = "decision"
            fake_entry.actor = "system"
            fake_entry.content = "Use JWT"
            fake_wm = MockWM.return_value
            fake_wm.get_all.return_value = [fake_entry]

            builder = PlannerContextBuilder()
            ctx = await builder.build(
                db, fake_task,
                global_rules=["Use async/await"],
            )

            assert fake_task.title in ctx.task_context
            assert "Research" in ctx.memory_context
            assert "Need auth" in ctx.channel_context
            assert "Use JWT" in ctx.workspace_context
            assert "Use async/await" in ctx.global_context
            assert "auth.py" in ctx.file_context

            # All sources recorded
            assert len(ctx.sources) == 6
            for src in ["task", "history", "channel", "workspace", "global", "files"]:
                assert src in ctx.sources


# ═══════════════════════════════════════════════════════════════
# 10. build_planner_context convenience function
# ═══════════════════════════════════════════════════════════════

class TestBuildPlannerContext:
    @pytest.mark.asyncio
    async def test_convenience_function(self, fake_task_no_extra):
        """build_planner_context returns a PlannerContext."""
        db = _make_db()

        ctx = await build_planner_context(
            db, fake_task_no_extra,
            global_rules=["Rule"],
        )

        assert isinstance(ctx, PlannerContext)
        assert fake_task_no_extra.title in ctx.task_context
        assert "Rule" in ctx.global_context

    @pytest.mark.asyncio
    async def test_convenience_custom_max_tokens(self, fake_task_no_extra):
        """Custom max_tokens is passed through."""
        db = _make_db()

        ctx = await build_planner_context(
            db, fake_task_no_extra,
            max_tokens=100,
        )
        assert isinstance(ctx, PlannerContext)


# ═══════════════════════════════════════════════════════════════
# 11. Driver integration — context passed to generate_plan
# ═══════════════════════════════════════════════════════════════

class TestDriverIntegration:
    @pytest.mark.asyncio
    async def test_context_dict_in_generate_plan(self):
        """Context dict from PlannerContext works in generate_plan."""
        from backend.tests.test_task_planner import FakeRuntime, _valid_plan_json

        maeos = FakeRuntime(result_text=_valid_plan_json(task_id="task-001"))

        ctx = PlannerContext(
            task_context="Build auth system",
            memory_context="Step 1: Research done",
            channel_context="User wants JWT auth",
            workspace_context="Prefer FastAPI",
        )
        ctx_dict = ctx.to_dict()

        plan = await generate_plan(
            maeos,
            goal="Build auth system",
            task_id="task-001",
            context=ctx_dict,
        )

        assert isinstance(plan, TaskPlan)
        assert plan.task_id == "task-001"

    @pytest.mark.asyncio
    async def test_empty_context_backward_compat(self):
        """Empty context dict still works (backward compat)."""
        from backend.tests.test_task_planner import FakeRuntime, _valid_plan_json

        maeos = FakeRuntime(result_text=_valid_plan_json())

        plan = await generate_plan(maeos, goal="Build auth", context={})
        assert isinstance(plan, TaskPlan)


# ═══════════════════════════════════════════════════════════════
# 12. Edge cases
# ═══════════════════════════════════════════════════════════════

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_task_with_very_long_description(self, fake_task):
        """Long descriptions are handled without error."""
        db = _make_db()
        fake_task.description = "X" * 50_000  # 50K chars

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task)

        assert fake_task.title in ctx.task_context
        assert ctx.total_chars > 0

    @pytest.mark.asyncio
    async def test_builder_without_db_session(self, fake_task_no_extra):
        """Builder handles a basic mock DB correctly."""
        db = _make_db()

        builder = PlannerContextBuilder()
        ctx = await builder.build(db, fake_task_no_extra)

        assert fake_task_no_extra.title in ctx.task_context
        assert ctx.sources == ["task"]

    @pytest.mark.asyncio
    async def test_to_prompt_section_with_all_sections(self):
        """to_prompt_section includes all non-empty sections."""
        ctx = PlannerContext(
            task_context="Goal",
            memory_context="History",
            channel_context="Chat",
            workspace_context="Workspace",
            global_context="Rules",
            file_context="Files",
        )
        prompt = ctx.to_prompt_section()

        assert "[TASK GOAL]" in prompt
        assert "[TASK HISTORY]" in prompt
        assert "[CHANNEL CONTEXT]" in prompt
        assert "[WORKSPACE MEMORY]" in prompt
        assert "[GLOBAL RULES]" in prompt
        assert "[RELATED FILES]" in prompt
