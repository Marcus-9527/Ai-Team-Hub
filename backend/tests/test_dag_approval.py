"""Phase 10 — Human Approval & Policy Engine Tests.

Covers:
  - ApprovalService pause/resume/reject lifecycle
  - PolicyService teammate/tool/task-type checks
  - Approval record wait/unblock mechanics
  - DagExecutor policy block & approval gate integration
  - Auto-execution path (no approval needed)
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.approval import (
    ApprovalRecord,
    ApprovalService,
    ApprovalStatus,
    get_approval_service,
    reset_approval_service,
)
from backend.services.policy import (
    PolicyService,
    PolicyResult,
    check_teammate_permission,
    check_tool_permission,
    check_task_type,
    get_policy_service,
    reset_policy_service,
)
from backend.services.dag.core import (
    DAGDefinition,
    DAGNode,
    NodeStatus,
    get_ready_nodes,
)
from backend.services.planner.dag_executor import DAGStore, reset_dag_store


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _make_node(description: str = "test", teammate: str = "",
               require_approval: bool = False,
               max_retry: int = 0, strategy: str = "linear",
               deps: list[str] | None = None) -> DAGNode:
    return DAGNode(
        description=description,
        teammate=teammate,
        require_approval=require_approval,
        max_retry=max_retry,
        strategy=strategy,
        deps=deps,
    )


# ═══════════════════════════════════════════════════════════════
# Approval Service Tests
# ═══════════════════════════════════════════════════════════════


class TestApprovalService:

    def setup_method(self):
        reset_approval_service()

    def test_create_approval(self):
        svc = get_approval_service()
        rec = svc.create("exec_1", "node_1", requested_by="alice")
        assert rec.id.startswith("apr_")
        assert rec.execution_id == "exec_1"
        assert rec.dag_node_id == "node_1"
        assert rec.requested_by == "alice"
        assert rec.status == ApprovalStatus.PENDING

    def test_approve_resolves(self):
        svc = get_approval_service()
        rec = svc.create("exec_1", "node_1")
        svc.approve(rec.id, by="admin")
        assert rec.status == ApprovalStatus.APPROVED
        assert rec.approved_by == "admin"
        assert rec.resolved_at > 0

    def test_reject_resolves(self):
        svc = get_approval_service()
        rec = svc.create("exec_1", "node_1")
        svc.reject(rec.id, by="admin")
        assert rec.status == ApprovalStatus.REJECTED
        assert rec.approved_by == "admin"

    def test_approve_non_pending_raises(self):
        svc = get_approval_service()
        rec = svc.create("exec_1", "node_1")
        svc.approve(rec.id)
        with pytest.raises(ValueError, match="Cannot approve"):
            svc.approve(rec.id)

    def test_reject_non_pending_raises(self):
        svc = get_approval_service()
        rec = svc.create("exec_1", "node_1")
        svc.reject(rec.id)
        with pytest.raises(ValueError, match="Cannot reject"):
            svc.reject(rec.id)

    def test_get_nonexistent_returns_none(self):
        svc = get_approval_service()
        assert svc.get("nope") is None

    def test_list_pending(self):
        svc = get_approval_service()
        svc.create("e1", "n1")
        r2 = svc.create("e1", "n2")
        svc.approve(r2.id)
        pending = svc.list_pending()
        assert len(pending) == 1
        assert pending[0]["dag_node_id"] == "n1"

    def test_list_all(self):
        svc = get_approval_service()
        svc.create("e1", "n1")
        r2 = svc.create("e1", "n2")
        svc.approve(r2.id)
        all_recs = svc.list_all()
        assert len(all_recs) == 2

    def test_to_dict(self):
        rec = ApprovalRecord("e1", "n1", "bob")
        d = rec.to_dict()
        assert d["execution_id"] == "e1"
        assert d["dag_node_id"] == "n1"
        assert d["status"] == "PENDING"
        assert d["requested_by"] == "bob"
        assert d["approved_by"] == ""
        assert d["created_at"] > 0
        assert d["resolved_at"] == 0.0

    @pytest.mark.asyncio
    async def test_wait_returns_true_on_approve(self):
        svc = get_approval_service()
        rec = svc.create("e1", "n1")

        async def _resolve():
            await asyncio.sleep(0.01)
            svc.approve(rec.id)

        asyncio.create_task(_resolve())
        result = await rec.wait(timeout=5.0)
        assert result is True
        assert rec.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_wait_returns_false_on_reject(self):
        svc = get_approval_service()
        rec = svc.create("e1", "n1")

        async def _resolve():
            await asyncio.sleep(0.01)
            svc.reject(rec.id)

        asyncio.create_task(_resolve())
        result = await rec.wait(timeout=5.0)
        assert result is False
        assert rec.status == ApprovalStatus.REJECTED


# ═══════════════════════════════════════════════════════════════
# Policy Service Tests
# ═══════════════════════════════════════════════════════════════


class TestPolicyService:

    def setup_method(self):
        reset_policy_service()

    # ── Unit checks ──

    def test_teammate_allowed_when_empty_list(self):
        result = check_teammate_permission("anyone", [])
        assert result.allowed is True

    def test_teammate_allowed_in_list(self):
        result = check_teammate_permission("alice", ["alice", "bob"])
        assert result.allowed is True

    def test_teammate_blocked(self):
        result = check_teammate_permission("charlie", ["alice", "bob"])
        assert result.allowed is False
        assert "charlie" in result.reason

    def test_tool_allowed_when_empty(self):
        result = check_tool_permission("any", [])
        assert result.allowed is True

    def test_tool_blocked(self):
        result = check_tool_permission("rm", ["ls", "cat"])
        assert result.allowed is False
        assert "rm" in result.reason

    def test_task_type_allowed_when_empty(self):
        result = check_task_type("linear", [])
        assert result.allowed is True

    def test_task_type_blocked(self):
        result = check_task_type("exponential", ["linear"])
        assert result.allowed is False
        assert "exponential" in result.reason

    # ── Aggregate evaluate_node ──

    def test_evaluate_node_allows_all_by_default(self):
        svc = get_policy_service()
        result = svc.evaluate_node(
            teammate="anyone",
            strategy="linear",
        )
        assert result.allowed is True

    def test_evaluate_node_blocks_teammate(self):
        svc = get_policy_service()
        result = svc.evaluate_node(
            teammate="charlie",
            allowed_teammates=["alice", "bob"],
        )
        assert result.allowed is False

    def test_evaluate_node_blocks_task_type(self):
        svc = get_policy_service()
        result = svc.evaluate_node(
            strategy="exponential",
            allowed_task_types=["linear"],
        )
        assert result.allowed is False

    def test_evaluate_node_allows_all_with_restrictions(self):
        svc = get_policy_service()
        result = svc.evaluate_node(
            teammate="alice",
            strategy="linear",
            allowed_teammates=["alice"],
            allowed_task_types=["linear"],
        )
        assert result.allowed is True


# ═══════════════════════════════════════════════════════════════
# DAG Execution with Approval / Policy Integration
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def _clean_services():
    reset_approval_service()
    reset_policy_service()
    reset_dag_store()
    store = DAGStore(db_url="sqlite:///:memory:")
    import backend.services.planner.dag_executor as _de
    _de._dag_store = store
    yield
    reset_dag_store()


def _make_executor(runtime_result_status="COMPLETED"):
    """Create a DagExecutor with a mock runtime."""
    rt = MagicMock()

    async def fake_execute(description="", priority=2, intent="",
                           provider=None, model=None,
                           api_key=None, base_url=None, wait=False,
                           **kwargs):
        task = MagicMock()
        task.id = "mock_task"
        task.status = runtime_result_status
        task.result = f"Result for: {description[:50]}"
        task.error = ""
        return task

    rt.execute = AsyncMock(side_effect=fake_execute)
    from backend.services.planner.dag_executor import DagExecutor
    return DagExecutor(rt)


@pytest.mark.usefixtures("_clean_services")
class TestDAGApprovalIntegration:

    @pytest.mark.asyncio
    async def test_auto_execute_no_approval(self):
        """Node without require_approval runs immediately."""
        executor = _make_executor()
        node = _make_node("Auto task")
        dag = DAGDefinition(name="test")
        dag.add_node(node)
        await executor.execute_dag(dag)
        assert node.status == NodeStatus.COMPLETED
        assert "Result for: Auto task" in node.result

    @pytest.mark.asyncio
    async def test_approval_pauses_then_continues(self):
        """Node with require_approval pauses until approved."""
        executor = _make_executor()
        node = _make_node("Approved task", require_approval=True)
        dag = DAGDefinition(name="test")
        dag.add_node(node)
        approval_svc = get_approval_service()

        async def _run_and_approve():
            await asyncio.sleep(0.02)
            pending = approval_svc.list_pending()
            assert len(pending) == 1
            approval_svc.approve(pending[0]["id"], by="admin")

        asyncio.create_task(_run_and_approve())
        await executor.execute_dag(dag)
        assert node.status == NodeStatus.COMPLETED
        assert "Result for: Approved task" in node.result

    @pytest.mark.asyncio
    async def test_approval_pauses_then_rejected(self):
        """Node with require_approval gets rejected → FAILED."""
        executor = _make_executor()
        node = _make_node("Rejected task", require_approval=True)
        dag = DAGDefinition(name="test")
        dag.add_node(node)
        approval_svc = get_approval_service()

        async def _run_and_reject():
            await asyncio.sleep(0.02)
            pending = approval_svc.list_pending()
            assert len(pending) == 1
            approval_svc.reject(pending[0]["id"], by="admin")

        asyncio.create_task(_run_and_reject())
        await executor.execute_dag(dag)
        assert node.status == NodeStatus.FAILED
        assert "REJECTED" in node.error

    @pytest.mark.asyncio
    async def test_policy_blocks_teammate(self):
        """Teammate not in allowed list → FAILED with POLICY_BLOCKED."""
        executor = _make_executor()
        node = _make_node("Blocked task", teammate="charlie")
        dag = DAGDefinition(name="test")
        dag.add_node(node)

        # Patch executor's _run_node to pass restrictive policy
        from backend.services.planner.dag_executor import DagExecutor
        orig_run = executor._run_node

        async def restricted_run(dag, node):
            await orig_run(dag, node,
                           allowed_teammates=["alice", "bob"])

        executor._run_node = restricted_run
        await executor.execute_dag(dag)
        assert node.status == NodeStatus.FAILED
        assert "POLICY_BLOCKED" in node.error

    @pytest.mark.asyncio
    async def test_policy_blocks_task_type(self):
        """Disallowed strategy → FAILED with POLICY_BLOCKED."""
        executor = _make_executor()
        node = _make_node("Type blocked", strategy="dangerous")
        dag = DAGDefinition(name="test")
        dag.add_node(node)

        from backend.services.planner.dag_executor import DagExecutor
        orig_run = executor._run_node

        async def restricted_run(dag, node):
            await orig_run(dag, node,
                           allowed_task_types=["linear"])

        executor._run_node = restricted_run
        await executor.execute_dag(dag)
        assert node.status == NodeStatus.FAILED
        assert "POLICY_BLOCKED" in node.error

    @pytest.mark.asyncio
    async def test_sequential_with_approval(self):
        """Two nodes where second requires approval → both complete."""
        executor = _make_executor()
        a = _make_node("First")
        b = _make_node("Second", deps=[a.id], require_approval=True)
        dag = DAGDefinition(name="seq")
        dag.add_node(a)
        dag.add_node(b)
        approval_svc = get_approval_service()

        async def _approve_second():
            await asyncio.sleep(0.05)
            pending = approval_svc.list_pending()
            if pending:
                approval_svc.approve(pending[0]["id"], by="admin")

        asyncio.create_task(_approve_second())
        await executor.execute_dag(dag)
        assert a.status == NodeStatus.COMPLETED
        assert b.status == NodeStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_dag_approval_survives_restart(self):
        """Approval record is in-memory. Verify create/list after reload."""
        approval_svc = get_approval_service()
        rec = approval_svc.create("dag1", "node_x")
        assert approval_svc.get(rec.id) is not None

        # Simulate "restart" by resetting — records are lost; this is expected
        # for in-memory. DB-backed persistence would survive.
        reset_approval_service()
        new_svc = get_approval_service()
        assert new_svc.get(rec.id) is None
