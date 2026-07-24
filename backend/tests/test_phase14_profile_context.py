"""Phase 14: Teammate Profile + Context Enhancement + Decision Engine — tests.

Verifies:
1. TeammateProfileBuilder aggregates from fragments + turns
2. BrainContextAssembler returns new sections in assemble()
3. BrainLoader._format() produces the new sections in prompt
4. OrganizationDecisionEngine.suggested_roles() mapping
5. action.decided event payload includes suggested_roles
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from backend.services.organization.actions import OrganizationAction
from backend.services.organization.decision import OrganizationDecisionEngine
from backend.services.brain.fragment_store import (
    BrainFragmentStore, BrainFragment, BrainFragmentType,
)

pytestmark = pytest.mark.asyncio


# ── OrganizationDecisionEngine: suggested_roles ──

class TestSuggestedRoles:
    """OrganizationDecisionEngine.suggested_roles derives from action type."""

    def test_execute_suggests_developer(self):
        assert OrganizationDecisionEngine.suggested_roles(
            OrganizationAction.EXECUTE,
        ) == ["developer"]

    def test_delegate_suggests_orchestrator_planner(self):
        assert OrganizationDecisionEngine.suggested_roles(
            OrganizationAction.DELEGATE,
        ) == ["orchestrator", "planner"]

    def test_respond_suggests_communicator(self):
        assert OrganizationDecisionEngine.suggested_roles(
            OrganizationAction.RESPOND,
        ) == ["communicator"]

    def test_tool_call_suggests_tool_user(self):
        assert OrganizationDecisionEngine.suggested_roles(
            OrganizationAction.TOOL_CALL,
        ) == ["tool_user"]

    def test_complete_suggests_reviewer(self):
        assert OrganizationDecisionEngine.suggested_roles(
            OrganizationAction.COMPLETE,
        ) == ["reviewer"]

    def test_unknown_action_falls_back(self):
        from enum import Enum
        class FakeAction(str, Enum):
            BOGUS = "bogus"
        assert OrganizationDecisionEngine.suggested_roles(
            FakeAction.BOGUS,  # type: ignore
        ) == ["generalist"]

    def test_explain_unchanged(self):
        """decide.explain() API is unchanged by Phase 14."""
        reason, conf = OrganizationDecisionEngine.explain(OrganizationAction.EXECUTE)
        assert "Code" in reason
        assert conf == 0.90

    def test_decide_api_unchanged(self):
        """decide() still returns OrganizationAction, not a dict."""
        action = OrganizationDecisionEngine().decide(
            type("ctx", (), {})(), "Hello",
        )
        assert isinstance(action, OrganizationAction)


# ── TeammateProfileBuilder ──

class TestTeammateProfileBuilder:
    """Profile builder aggregates from fragments + memory + turns."""

    async def test_build_with_fragments_only(self):
        """Profile built from BrainFragments when no db session."""
        from backend.services.brain.profile_builder import TeammateProfileBuilder
        from backend.services.memory.memory_service import MemoryService

        mock_store = AsyncMock(spec=BrainFragmentStore)
        mock_store.get_all_by_teammate.return_value = [
            BrainFragment(
                teammate_id="tm_x",
                fragment_type=BrainFragmentType.PERSONALITY,
                content="Detail-oriented and thorough",
                source="manual",
            ),
            BrainFragment(
                teammate_id="tm_x",
                fragment_type=BrainFragmentType.PREFERENCES,
                content="Prefers async communication",
                source="manual",
            ),
            BrainFragment(
                teammate_id="tm_x",
                fragment_type=BrainFragmentType.SKILLS,
                content="Python, React, SQL",
                source="manual",
            ),
            BrainFragment(
                teammate_id="tm_x",
                fragment_type=BrainFragmentType.IDENTITY,
                content="Senior full-stack developer",
                source="manual",
            ),
        ]
        mock_mem = AsyncMock(spec=MemoryService)
        builder = TeammateProfileBuilder(
            fragment_store=mock_store, memory_service=mock_mem,
        )

        profile = await builder.build("tm_x")

        assert profile["personality"] == "Detail-oriented and thorough"
        assert profile["preferences"] == "Prefers async communication"
        assert "Python" in profile["expertise"]
        assert any("Senior" in e for e in profile["expertise"])  # from identity
        # work_style = personality + principles (no principles, so just personality)
        assert "Detail-oriented" in profile["work_style"]

    async def test_build_with_turns_when_db_provided(self):
        """Profile includes turn-derived expertise when db is available."""
        from backend.services.brain.profile_builder import TeammateProfileBuilder
        from backend.services.memory.memory_service import MemoryService
        from datetime import datetime, timezone

        mock_store = AsyncMock(spec=BrainFragmentStore)
        mock_store.get_all_by_teammate.return_value = [
            BrainFragment(
                teammate_id="tm_x",
                fragment_type=BrainFragmentType.SKILLS,
                content="Python",
                source="manual",
            ),
        ]
        mock_mem = AsyncMock(spec=MemoryService)

        # Mock DB with a session_turn query
        mock_db = AsyncMock()
        mock_scalar_result = MagicMock()
        mock_scalar_result.all = MagicMock(return_value=[])
        mock_execute_result = MagicMock()
        mock_execute_result.scalars = MagicMock(return_value=mock_scalar_result)
        mock_db.execute = AsyncMock(return_value=mock_execute_result)

        builder = TeammateProfileBuilder(
            fragment_store=mock_store, memory_service=mock_mem,
        )
        profile = await builder.build("tm_x", db=mock_db)

        assert "Python" in profile["expertise"]


# ── BrainContextAssembler: Phase 14 sections ──

class TestBrainContextAssemblerPhase14:
    """BrainContextAssembler.assemble() returns new Phase 14 keys."""

    async def test_assemble_returns_phase14_keys(self):
        """assemble() dict includes teammate_profile, history_summary, collaboration_pattern."""
        from backend.services.brain.context import BrainContextAssembler
        mock_store = AsyncMock(spec=BrainFragmentStore)
        mock_store.get_all_by_teammate.return_value = []

        from backend.services.memory.memory_service import MemoryService
        mock_mem = AsyncMock(spec=MemoryService)
        # Return empty for all query calls
        mock_mem.query.return_value = []

        assembler = BrainContextAssembler(
            fragment_store=mock_store, memory_service=mock_mem,
        )
        ctx = await assembler.assemble("tm_x")

        assert "teammate_profile" in ctx
        assert "history_summary" in ctx
        assert "collaboration_pattern" in ctx

        # Default empty values
        assert ctx["teammate_profile"] == {}
        assert ctx["history_summary"] == ""
        assert ctx["collaboration_pattern"] == ""

    async def test_assemble_with_db_populates_profile(self):
        """When db is provided, teammate_profile is populated."""
        from backend.services.brain.context import BrainContextAssembler
        mock_store = AsyncMock(spec=BrainFragmentStore)
        mock_store.get_all_by_teammate.return_value = [
            BrainFragment(
                teammate_id="tm_x",
                fragment_type=BrainFragmentType.PERSONALITY,
                content="Analytical thinker",
                source="manual",
            ),
        ]

        from backend.services.memory.memory_service import MemoryService
        mock_mem = AsyncMock(spec=MemoryService)
        mock_mem.query.return_value = []

        # Mock DB with a session_turn query
        mock_db = AsyncMock()
        mock_scalar_result = MagicMock()
        mock_scalar_result.all = MagicMock(return_value=[])
        mock_execute_result = MagicMock()
        mock_execute_result.scalars = MagicMock(return_value=mock_scalar_result)
        mock_db.execute = AsyncMock(return_value=mock_execute_result)

        assembler = BrainContextAssembler(
            fragment_store=mock_store, memory_service=mock_mem,
        )
        ctx = await assembler.assemble("tm_x", db=mock_db)
        profile = ctx["teammate_profile"]
        assert profile["personality"] == "Analytical thinker"

    async def test_collaboration_pattern_from_team_pattern_memories(self):
        """collaboration_pattern is built from TEAM_PATTERN memories."""
        from backend.services.brain.context import BrainContextAssembler
        from backend.services.memory.memory_types import MemoryItem, MemoryType
        from backend.services.memory.memory_service import MemoryService

        mock_store = AsyncMock(spec=BrainFragmentStore)
        mock_store.get_all_by_teammate.return_value = []
        mock_mem = AsyncMock(spec=MemoryService)
        # Return TEAM_PATTERN memory items
        mock_mem.query.return_value = [
            MemoryItem(
                content="Teammates collaborate via task handoff pattern",
                memory_type=MemoryType.TEAM_PATTERN,
            ),
        ]

        assembler = BrainContextAssembler(
            fragment_store=mock_store, memory_service=mock_mem,
        )
        ctx = await assembler.assemble("tm_x")

        assert ctx["collaboration_pattern"] != ""
        assert "task handoff" in ctx["collaboration_pattern"]

    async def test_assemble_with_db_populates_history(self):
        """When db is provided, history_summary is populated from recent turns."""
        from backend.services.brain.context import BrainContextAssembler
        from backend.services.memory.memory_service import MemoryService
        from datetime import datetime, timezone

        mock_store = AsyncMock(spec=BrainFragmentStore)
        mock_store.get_all_by_teammate.return_value = []
        mock_mem = AsyncMock(spec=MemoryService)
        mock_mem.query.return_value = []

        # Mock a turn with action_type
        mock_turn = AsyncMock()
        mock_turn.action_type = "respond"
        mock_turn.action = "responded"
        mock_turn.failure = None
        mock_turn.tokens_in = 50
        mock_turn.tokens_out = 30
        mock_turn.start_time = datetime(2026, 7, 23, 14, 30, tzinfo=timezone.utc)

        mock_db = AsyncMock()
        mock_scalar_result = MagicMock()
        mock_scalar_result.all = MagicMock(return_value=[mock_turn])
        mock_execute_result = MagicMock()
        mock_execute_result.scalars = MagicMock(return_value=mock_scalar_result)
        mock_db.execute = AsyncMock(return_value=mock_execute_result)

        assembler = BrainContextAssembler(
            fragment_store=mock_store, memory_service=mock_mem,
        )
        ctx = await assembler.assemble("tm_x", db=mock_db)

        assert ctx["history_summary"] != ""
        assert "respond" in ctx["history_summary"]
        assert "80t" in ctx["history_summary"] or "50" in ctx["history_summary"]


# ── BrainLoader._format(): Phase 14 sections ──

class TestBrainLoaderPhase14:
    """BrainLoader._format() renders Phase 14 sections."""

    def test_format_with_profile(self):
        """_format() adds TEAMMATE WORKING STYLE sections from profile."""
        from backend.services.brain.brain_loader import BrainLoader
        from backend.services.memory.memory_service import MemoryService
        from unittest.mock import AsyncMock

        loader = BrainLoader(
            fragment_store=AsyncMock(spec=BrainFragmentStore),
            memory_service=AsyncMock(spec=MemoryService),
        )

        ctx = {
            "fragments": [],
            "workspace_id": "",
            "identity": None,
            "knowledge_items": {},
            "recent_memory_text": "",
            "recent_memory_is_semantic": False,
            "experience": [],
            "team_items": [],
            "proj_items": [],
            "teammate_profile": {
                "personality": "Analytical and proactive",
                "preferences": "Prefers short tasks",
                "expertise": ["Python", "experienced_in:respond"],
                "work_style": "Analytical and proactive",
            },
            "history_summary": "",
            "collaboration_pattern": "",
        }

        prompt = loader._format(ctx)

        assert "## TEAMMATE WORKING STYLE" in prompt
        assert "Analytical and proactive" in prompt
        assert "## TEAMMATE PREFERENCES" in prompt
        assert "Prefers short tasks" in prompt
        assert "## TEAMMATE EXPERTISE" in prompt
        assert "Python" in prompt

    def test_format_with_history(self):
        """_format() adds TEAMMATE HISTORY section."""
        from backend.services.brain.brain_loader import BrainLoader
        from backend.services.memory.memory_service import MemoryService
        from unittest.mock import AsyncMock

        loader = BrainLoader(
            fragment_store=AsyncMock(spec=BrainFragmentStore),
            memory_service=AsyncMock(spec=MemoryService),
        )

        ctx = {
            "fragments": [],
            "workspace_id": "",
            "identity": None,
            "knowledge_items": {},
            "recent_memory_text": "",
            "recent_memory_is_semantic": False,
            "experience": [],
            "team_items": [],
            "proj_items": [],
            "teammate_profile": {},
            "history_summary": "  - [14:30] respond (ok, 80t)\n  - [14:25] execute (ok, 150t)",
            "collaboration_pattern": "",
        }

        prompt = loader._format(ctx)

        assert "## TEAMMATE HISTORY" in prompt
        assert "respond" in prompt
        assert "execute" in prompt

    def test_format_with_collaboration_pattern(self):
        """_format() adds COLLABORATION PATTERN section."""
        from backend.services.brain.brain_loader import BrainLoader
        from backend.services.memory.memory_service import MemoryService
        from unittest.mock import AsyncMock

        loader = BrainLoader(
            fragment_store=AsyncMock(spec=BrainFragmentStore),
            memory_service=AsyncMock(spec=MemoryService),
        )

        ctx = {
            "fragments": [],
            "workspace_id": "",
            "identity": None,
            "knowledge_items": {},
            "recent_memory_text": "",
            "recent_memory_is_semantic": False,
            "experience": [],
            "team_items": [],
            "proj_items": [],
            "teammate_profile": {},
            "history_summary": "",
            "collaboration_pattern": "  - [team] teammates collaborate via handoff pattern",
        }

        prompt = loader._format(ctx)

        assert "## COLLABORATION PATTERN" in prompt
        assert "handoff" in prompt

    def test_format_empty_profile_no_new_sections(self):
        """When profile/history/collab are empty, no new sections appear."""
        from backend.services.brain.brain_loader import BrainLoader
        from backend.services.memory.memory_service import MemoryService
        from unittest.mock import AsyncMock

        loader = BrainLoader(
            fragment_store=AsyncMock(spec=BrainFragmentStore),
            memory_service=AsyncMock(spec=MemoryService),
        )

        ctx = {
            "fragments": [],
            "workspace_id": "",
            "identity": None,
            "knowledge_items": {},
            "recent_memory_text": "",
            "recent_memory_is_semantic": False,
            "experience": [],
            "team_items": [],
            "proj_items": [],
            "teammate_profile": {},
            "history_summary": "",
            "collaboration_pattern": "",
        }

        prompt = loader._format(ctx)

        assert "## TEAMMATE WORKING STYLE" not in prompt
        assert "## TEAMMATE PREFERENCES" not in prompt
        assert "## TEAMMATE EXPERTISE" not in prompt
        assert "## TEAMMATE HISTORY" not in prompt
        assert "## COLLABORATION PATTERN" not in prompt


# ── OrganizationDecisionEngine: context-aware scoring ──

class TestContextAwareDecision:
    """decide() considers context (goal/team/identity/failures)."""

    def test_short_input_unchanged_by_context(self):
        """Inputs < 20 chars still return RESPOND even with task goal."""
        from backend.services.organization.context_builder import OrganizationContext
        eng = OrganizationDecisionEngine()
        ctx = OrganizationContext({
            "run_id": "run-1", "goal": "Refactor auth module",
            "members": ["tm-1", "tm-2"],
        })
        # "Hello" is 5 chars → context fallback threshold not reached
        assert eng.decide(ctx, "Hello") == OrganizationAction.RESPOND

    def test_goal_context_shifts_long_ambiguous_input(self):
        """Long >20 char input with goal context → DELEGATE instead of RESPOND."""
        from backend.services.organization.context_builder import OrganizationContext
        eng = OrganizationDecisionEngine()
        ctx = OrganizationContext({
            "run_id": "run-1", "goal": "Implement user auth",
            "members": ["tm-1", "tm-2"],
        })
        # No keyword match but > 20 chars AND goal set
        result = eng.decide(ctx, "This is a non-trivial request about something")
        assert result == OrganizationAction.DELEGATE

    def test_solo_member_cancels_delegate(self):
        """Solo teammate → no DELEGATE even with goal."""
        from backend.services.organization.context_builder import OrganizationContext
        eng = OrganizationDecisionEngine()
        ctx = OrganizationContext({
            "run_id": "run-1", "goal": "Do something",
            "members": ["tm-1"],  # solo
        })
        result = eng.decide(ctx, "This is a non-trivial request about something")
        assert result == OrganizationAction.RESPOND

    def test_failures_dampen_delegate(self):
        """Recent failures → prefer RESPOND over DELEGATE."""
        from backend.services.organization.context_builder import OrganizationContext
        eng = OrganizationDecisionEngine()
        ctx = OrganizationContext({
            "run_id": "run-1",
            "goal": "Complete project",
            "members": ["tm-1", "tm-2"],
            "recent_turns": [
                {"failure": "Timeout error"},
                {"failure": "API limit"},
            ],
        })
        result = eng.decide(ctx, "This is a non-trivial request about something")
        # 2 failures × 0.08 = -0.16 to DELEGATE, goal gives +0.10
        # Net: DELEGATE +0.10 - 0.16 = -0.06, RESPOND -0.05
        # → DELEGATE no longer beats RESPOND
        assert result == OrganizationAction.RESPOND

    def test_developer_identity_boosts_execute(self):
        """Dev role identity → EXECUTE gets a score bump."""
        from backend.services.organization.context_builder import OrganizationContext
        scores = OrganizationDecisionEngine._score_context(OrganizationContext({
            "run_id": "run-1",
            "members": ["tm-1"],
            "members_info": {"tm-1": {"role": "developer"}},
        }))
        assert scores[OrganizationAction.EXECUTE] >= 0.08
        # Solo teammate → DELEGATE dampened
        assert scores[OrganizationAction.DELEGATE] < 0

    def test_keyword_rules_still_win_over_context(self):
        """Keyword rules (code, debug) take priority over context."""
        from backend.services.organization.context_builder import OrganizationContext
        eng = OrganizationDecisionEngine()
        ctx = OrganizationContext({
            "run_id": "run-1", "goal": "Big project",
            "members": ["tm-1", "tm-2"],
        })
        # Code block even in task context → EXECUTE
        assert eng.decide(ctx, "```python\nx=1\n```") == OrganizationAction.EXECUTE
        # Debug keyword → EXECUTE
        assert eng.decide(ctx, "Fix this bug in auth") == OrganizationAction.EXECUTE
        # Multi-step → DELEGATE (already DELEGATE)
        inp = "We need to " + "x" * 301
        assert eng.decide(ctx, inp) == OrganizationAction.DELEGATE

    def test_explain_with_context_adjusts_confidence(self):
        """explain(action, ctx) adjusts confidence from context."""
        from backend.services.organization.context_builder import OrganizationContext
        # Without ctx: base confidence
        reason, conf = OrganizationDecisionEngine.explain(OrganizationAction.DELEGATE)
        assert conf == 0.85

        # With goal-active ctx: DELEGATE gets +0.10 boost
        ctx = OrganizationContext({
            "run_id": "run-1", "goal": "Active goal",
            "members": ["tm-1", "tm-2"],
        })
        reason, conf = OrganizationDecisionEngine.explain(OrganizationAction.DELEGATE, ctx)
        assert conf == pytest.approx(0.95, abs=0.01)  # 0.85 + 0.10

        # Solo teammate dampens DELEGATE
        solo_ctx = OrganizationContext({
            "run_id": "run-1", "goal": "Active goal",
            "members": ["tm-1"],  # solo
        })
        reason, conf = OrganizationDecisionEngine.explain(OrganizationAction.DELEGATE, solo_ctx)
        assert conf < 0.85  # dampened below base

    def test_no_context_no_change(self):
        """Without ctx, explain and suggested_roles match Phase 10 behavior exactly."""
        reason, conf = OrganizationDecisionEngine.explain(OrganizationAction.DELEGATE)
        assert reason == "Multi-step or long input detected"
        assert conf == 0.85

        roles = OrganizationDecisionEngine.suggested_roles(OrganizationAction.EXECUTE)
        assert roles == ["developer"]

    def test_chat_context_no_change(self):
        """Chat context (no goal, multi-member) → scores all zero for fallback actions."""
        from backend.services.organization.context_builder import OrganizationContext
        scores = OrganizationDecisionEngine._score_context(OrganizationContext({
            "run_id": "run-1", "members": ["tm-1", "tm-2"],
        }))
        # No goal, no identity info, no failures → no score deltas
        assert all(abs(v) < 0.01 for v in scores.values())
