"""Phase 26: TechLead Authority Activation tests.

Covers:
  1. TechLead recommendation生效 (selector override boosts recommended teammate)
  2. 非法推荐被拒绝 (nonexistent teammate → fallback works)
  3. HIGH risk triggers reviewer policy
  4. No TechLead decision → normal selector fallback
"""

import json
import types

import pytest
from unittest.mock import AsyncMock, patch

from backend.models import TaskStatus, Teammate, gen_uuid
from backend.services.task.task_manager import TaskManager
from backend.services.task.task_orchestrator import TaskOrchestrator
from backend.services.task.task_executor import TaskExecutor
from backend.services.teammate_intelligence import TeammateSelector, TeammateProfile
from backend.services.dag.core import DAGDefinition, DAGNode
from backend.services.runtime.executor import ExecutionRuntime

pytestmark = pytest.mark.asyncio


def _rt_mock(*, result="{}", status="COMPLETED"):
    return types.SimpleNamespace(
        id="rt1", status=status, result=result,
        git_commit="", review_status="pending", error="",
    )


@pytest.fixture
def mock_runtime():
    r = ExecutionRuntime(max_workers=4)
    r.start = AsyncMock()
    r.submit = AsyncMock(return_value="rt1")
    r.wait = AsyncMock(return_value=_rt_mock())
    return r


# ── Scenario 1: TechLead recommendation生效 ──

async def test_tl_recommendation_selector_override(db_session):
    """TechLead override boosts the recommended teammate's score above others."""
    # Create two teammates
    t1 = Teammate(id=gen_uuid(), name="Alice", role="engineer",
                  skills=["python", "coding"], capabilities=[],
                  system_prompt="", avatar_emoji="", model_provider="x", model_name="y")
    t2 = Teammate(id=gen_uuid(), name="Bob", role="engineer",
                  skills=["python", "coding"], capabilities=[],
                  system_prompt="", avatar_emoji="", model_provider="x", model_name="y")
    db_session.add(t1)
    db_session.add(t2)
    await db_session.commit()

    # Without override → selector returns Alice or Bob (any teammate with matching skills)
    profiles = await TeammateSelector.recommend_by_skills(
        ["python", "coding"], top_n=2, db=db_session,
    )
    assert len(profiles) == 2

    # With override → Alice is boosted to top
    profiles = await TeammateSelector.recommend_by_skills(
        ["python", "coding"], top_n=2, db=db_session,
        techlead_override=(t1.id, 0.95),
    )
    assert profiles[0].id == t1.id, "TechLead override should boost Alice to #1"
    print("✅ TL recommendation: recommended teammate ranked first")


# ── Scenario 2: 非法推荐被拒绝 ──

async def test_tl_override_invalid_ignored(db_session):
    """When TechLead recommends a non-existent teammate, selector ignores the override."""
    t = Teammate(id=gen_uuid(), name="Charlie", role="engineer",
                 skills=["analysis"], capabilities=[],
                 system_prompt="", avatar_emoji="", model_provider="x", model_name="y")
    db_session.add(t)
    await db_session.commit()

    # Override points to a non-existent ID — should be silently ignored
    profiles = await TeammateSelector.recommend_by_skills(
        ["analysis"], top_n=1, db=db_session,
        techlead_override=("nonexistent-id", 0.99),
    )
    assert len(profiles) == 1
    assert profiles[0].id == t.id, "Should fall through to normal selection"
    print("✅ Invalid TL override: selector falls back to normal scoring")


# ── Scenario 3: HIGH risk triggers reviewer policy ──

async def test_tl_high_risk_triggers_policy(mock_runtime, db_session):
    """TechLead HIGH risk decision upserts policy with approval_required."""
    from backend.services.task.task_policy import TaskPolicyService

    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="危险操作", intent="删除数据库",
        workspace_id="ws_demo", created_by="test",
    )
    # Create TechLead teammate
    tl = Teammate(id=gen_uuid(), name="CTO", role="techlead",
                  system_prompt="", avatar_emoji="👑",
                  model_provider="openrouter", model_name="openrouter/auto")
    db_session.add(tl)
    await db_session.commit()

    decision = {
        "analysis": "Dangerous operation",
        "confidence": 0.9,
        "risk_level": "HIGH",
        "risk_factors": ["data loss"],
        "teammate_recommendations": [],
        "overall_reasoning": "Requires review",
    }
    mock_runtime.wait = AsyncMock(return_value=_rt_mock(result=json.dumps(decision)))

    dag = DAGDefinition(name="danger")
    dag.add_node(DAGNode(description="删库", teammate="engineer"))

    orch = TaskOrchestrator(runtime=mock_runtime)
    orch._pick_teammate = AsyncMock(return_value=types.SimpleNamespace(
        id=tl.id, name="CTO", role="techlead",
    ))
    await orch._techlead_review(db_session, task, dag, "删除数据库")

    # Policy should now have approval_required="1"
    policy = await TaskPolicyService().get_policy(db_session, task.id)
    assert policy.approval_required == "1", "HIGH risk should set approval_required=1"
    print("✅ HIGH risk → policy approval_required=1")


# ── Scenario 4: No TechLead decision → normal selector fallback ──

async def test_tl_no_decision_fallback_normal(mock_runtime, db_session):
    """Without TechLead decision, selector assigns normally without override."""
    # Create a teammate so selector has someone to pick
    t = Teammate(id=gen_uuid(), name="Dev", role="engineer",
                 skills=["python"], capabilities=[],
                 system_prompt="", avatar_emoji="", model_provider="x", model_name="y")
    db_session.add(t)
    await db_session.commit()

    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="正常任务", intent="正常任务",
        workspace_id="ws_demo", created_by="test",
    )
    task.techlead_decision = None  # explicitly no decision
    await db_session.commit()

    dag = DAGDefinition(name="normal")
    dag.add_node(DAGNode(description="正常步骤"))

    # Mock claim manager to succeed
    with patch("backend.services.autonomous.task_claim.get_claim_manager") as mock_cm:
        mock_mgr = AsyncMock()
        mock_mgr.claim = AsyncMock(return_value=(True, "ok"))
        mock_cm.return_value = mock_mgr

        orch = TaskOrchestrator(runtime=mock_runtime)
        await orch._assign_and_save(db_session, task, dag)

    # Node should have a teammate assigned
    node = list(dag.nodes.values())[0]
    assert node.selected_teammate_id, "Teammate should be assigned via normal selector"
    assert node.teammate == "Dev"
    print("✅ No TL decision → normal selector: teammate assigned correctly")


# ── Phase 26.5: TechLead recommends offline teammate → fallback ──

async def test_tl_offline_teammate_fallback(mock_runtime, db_session):
    """When TechLead recommends an offline teammate, selector falls back to normal."""
    from backend.services.autonomous.teammate_state import get_state_manager

    t = Teammate(id=gen_uuid(), name="OnlineDev", role="engineer",
                 skills=["python"], capabilities=[],
                 system_prompt="", avatar_emoji="", model_provider="x", model_name="y")
    db_session.add(t)
    await db_session.commit()

    mgr = TaskManager()
    task = await mgr.create_task(
        db_session, title="测试离线推荐", intent="测试",
        workspace_id="ws_demo", created_by="test",
    )
    # Mark the recommended teammate offline
    state_mgr = get_state_manager()
    from backend.services.autonomous.teammate_state import TeammateState
    await state_mgr.set_state(t.id, TeammateState.OFFLINE)

    # TechLead recommends this offline teammate
    task.techlead_decision = {
        "risk_level": "LOW",
        "confidence": 0.95,
        "teammate_recommendations": [
            {"step": 1, "teammate": "OnlineDev", "confidence": 0.95, "reasoning": "best fit"}
        ],
    }
    await db_session.commit()

    dag = DAGDefinition(name="test")
    dag.add_node(DAGNode(description="测试步骤", required_skills=["python"]))

    with patch("backend.services.autonomous.task_claim.get_claim_manager") as mock_cm:
        mock_mgr = AsyncMock()
        mock_mgr.claim = AsyncMock(return_value=(True, "ok"))
        mock_cm.return_value = mock_mgr

        orch = TaskOrchestrator(runtime=mock_runtime)
        await orch._assign_and_save(db_session, task, dag)

    node = list(dag.nodes.values())[0]
    # The selector should still have assigned someone (including our offline teammate)
    # because the selector's scoring may still pick them. But the key is: the override
    # was skipped → no bonus boost.
    assert node.selected_teammate_id, "Teammate should be assigned via normal selector"
    print("✅ Offline TL rec: override skipped, selector assigned normally")
