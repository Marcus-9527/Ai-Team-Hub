"""Phase 8 — DAG Core + Planner tests.

Covers:
  - DAG node creation & serialisation
  - topological_sort (valid DAGs)
  - detect_cycle (self-loop, cross-cycle)
  - get_ready_nodes (fan-in dependency resolution)
  - parallel node execution via mocked ExecutionRuntime
  - state recovery (nodes reset and re-run)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.dag.core import (
    DAGDefinition,
    DAGNode,
    NodeStatus,
    detect_cycle,
    get_ready_nodes,
    topological_sort,
)
from backend.services.dag.executor import (
    execute_dag,
    DAGStore,
    get_dag_store,
    reset_dag_store,
)


# ── Fixtures ──


def _make_node(description: str, deps: list[str] | None = None,
               max_retry: int = 0, strategy: str = "linear") -> DAGNode:
    node = DAGNode(description=description, deps=deps,
                   max_retry=max_retry, strategy=strategy)
    return node


def _make_dag(*nodes: DAGNode, name: str = "test") -> DAGDefinition:
    dag = DAGDefinition(name=name)
    for n in nodes:
        dag.add_node(n)
    return dag


# ── DAG Node basics ──


class TestDAGNode:
    def test_create_node(self):
        node = DAGNode(description="hello", teammate="alice")
        assert node.description == "hello"
        assert node.teammate == "alice"
        assert node.status == NodeStatus.PENDING
        assert len(node.id) > 0

    def test_node_to_dict(self):
        node = DAGNode(description="test")
        d = node.to_dict()
        assert d["id"] == node.id
        assert d["status"] == "PENDING"
        assert d["description"] == "test"

    def test_node_with_deps(self):
        a = _make_node("A")
        b = _make_node("B", deps=[a.id])
        assert b.deps == [a.id]


# ── Topological sort ──


class TestTopologicalSort:
    def test_single_node(self):
        a = _make_node("A")
        dag = _make_dag(a)
        order = topological_sort(dag)
        assert order == [a.id]

    def test_linear_chain(self):
        a = _make_node("A")
        b = _make_node("B", deps=[a.id])
        c = _make_node("C", deps=[b.id])
        dag = _make_dag(a, b, c)
        order = topological_sort(dag)
        # A before B before C
        assert order.index(a.id) < order.index(b.id) < order.index(c.id)

    def test_fan_in(self):
        a = _make_node("A")
        b = _make_node("B")
        c = _make_node("C", deps=[a.id, b.id])
        dag = _make_dag(a, b, c)
        order = topological_sort(dag)
        assert order.index(a.id) < order.index(c.id)
        assert order.index(b.id) < order.index(c.id)

    def test_fan_out(self):
        a = _make_node("A")
        b = _make_node("B", deps=[a.id])
        c = _make_node("C", deps=[a.id])
        dag = _make_dag(a, b, c)
        order = topological_sort(dag)
        assert order.index(a.id) == 0
        assert order.index(b.id) in (1, 2)
        assert order.index(c.id) in (1, 2)


# ── Cycle detection ──


class TestCycleDetection:
    def test_no_cycle(self):
        a = _make_node("A")
        b = _make_node("B", deps=[a.id])
        dag = _make_dag(a, b)
        assert detect_cycle(dag) is False

    def test_self_loop(self):
        a = _make_node("A", deps=["self"])
        a.id = "self"
        dag = _make_dag(a)
        assert detect_cycle(dag) is True

    def test_cross_cycle(self):
        a = _make_node("A")
        b = _make_node("B", deps=[a.id])
        a.deps = [b.id]  # A → B → A
        dag = _make_dag(a, b)
        assert detect_cycle(dag) is True

    def test_cycle_raises_on_sort(self):
        a = _make_node("A", deps=["b"])
        a.id = "a"
        b = _make_node("B", deps=["a"])
        b.id = "b"
        dag = _make_dag(a, b)
        with pytest.raises(ValueError, match="Cycle"):
            topological_sort(dag)


# ── Ready nodes ──


class TestReadyNodes:
    def test_all_ready_when_no_deps(self):
        a = _make_node("A")
        b = _make_node("B")
        dag = _make_dag(a, b)
        ready = get_ready_nodes(dag)
        assert len(ready) == 2

    def test_dep_not_ready(self):
        a = _make_node("A")
        b = _make_node("B", deps=[a.id])
        dag = _make_dag(a, b)
        ready = get_ready_nodes(dag)
        assert ready == [a]  # only A ready

    def test_ready_after_dep_completes(self):
        a = _make_node("A")
        b = _make_node("B", deps=[a.id])
        dag = _make_dag(a, b)
        a.status = NodeStatus.COMPLETED
        ready = get_ready_nodes(dag)
        assert ready == [b]

    def test_multi_dep_ready(self):
        a = _make_node("A")
        b = _make_node("B")
        c = _make_node("C", deps=[a.id, b.id])
        dag = _make_dag(a, b, c)
        a.status = NodeStatus.COMPLETED
        b.status = NodeStatus.COMPLETED
        ready = get_ready_nodes(dag)
        assert ready == [c]

    def test_multi_dep_one_missing(self):
        a = _make_node("A")
        b = _make_node("B")
        c = _make_node("C", deps=[a.id, b.id])
        dag = _make_dag(a, b, c)
        a.status = NodeStatus.COMPLETED
        # b still PENDING → C NOT ready (B itself is root → ready)
        ready_ids = {n.id for n in get_ready_nodes(dag)}
        assert c.id not in ready_ids  # C blocked on B


# ── DAG execution with mocked runtime ──


@pytest.fixture
def _dag_store_in_memory():
    """Use in-memory SQLite for DAGStore during executor tests."""
    reset_dag_store()
    store = DAGStore(db_url="sqlite:///:memory:")
    # Inject into the module-level singleton
    import backend.services.dag.executor as _de
    _de._dag_store = store
    yield
    reset_dag_store()


@pytest.fixture
def mock_runtime():
    """An ExecutionRuntime that instantly "completes" any task."""
    rt = MagicMock()

    async def fake_execute(description="", priority=2, intent="",
                            provider=None, model=None,
                            api_key=None, base_url=None, wait=False,
                            **kwargs):
        task = MagicMock()
        task.id = "mock_task"
        task.status = "COMPLETED"
        task.result = f"Result for: {description[:50]}"
        task.error = ""
        return task

    rt.execute = AsyncMock(side_effect=fake_execute)
    return rt


@pytest.mark.usefixtures("_dag_store_in_memory")
class TestDagExecutor:
    @pytest.mark.asyncio
    async def test_single_node(self, mock_runtime):
        a = _make_node("Task A")
        dag = _make_dag(a)
        await execute_dag(dag, mock_runtime)
        assert a.status == NodeStatus.COMPLETED
        assert "Result for: Task A" in a.result

    @pytest.mark.asyncio
    async def test_parallel_nodes(self, mock_runtime):
        """Independent nodes should both execute."""
        a = _make_node("Task A")
        b = _make_node("Task B")
        dag = _make_dag(a, b)
        await execute_dag(dag, mock_runtime)
        assert a.status == NodeStatus.COMPLETED
        assert b.status == NodeStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_sequential_deps(self, mock_runtime):
        """Dependent nodes execute after deps complete."""
        a = _make_node("Task A")
        b = _make_node("Task B", deps=[a.id])
        c = _make_node("Task C", deps=[b.id])
        dag = _make_dag(a, b, c)
        await execute_dag(dag, mock_runtime)
        assert a.status == NodeStatus.COMPLETED
        assert b.status == NodeStatus.COMPLETED
        assert c.status == NodeStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_fan_in_execution(self, mock_runtime):
        """Two parallel deps then a merge node."""
        a = _make_node("Task A")
        b = _make_node("Task B")
        c = _make_node("Task C", deps=[a.id, b.id])
        dag = _make_dag(a, b, c)
        await execute_dag(dag, mock_runtime)
        assert a.status == NodeStatus.COMPLETED
        assert b.status == NodeStatus.COMPLETED
        assert c.status == NodeStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_state_recovery(self, mock_runtime):
        """After execution, all nodes have correct status."""
        a = _make_node("Task A")
        b = _make_node("Task B", deps=[a.id])
        dag = _make_dag(a, b)
        await execute_dag(dag, mock_runtime)
        # Verify full state
        d = dag.to_dict()
        nodes = d["nodes"]
        assert all(n["status"] == "COMPLETED" for n in nodes.values())
        assert d["node_count"] == 2
        assert d["name"] == "test"


# ── Phase 9: Persistence ──


class TestDAGPersistence:
    """DAG data survives store close / reopen."""

    @pytest.mark.asyncio
    async def test_persistence(self):
        a = _make_node("Persist A")
        b = _make_node("Persist B", deps=[a.id])
        dag = _make_dag(a, b, name="persist-dag")

        import tempfile, os
        tmpf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_path = tmpf.name
        tmpf.close()

        try:
            store_a = DAGStore(db_url=f"sqlite:///{tmp_path}")
            store_a.save(dag)

            # Simulate restart: new store, same file
            store_b = DAGStore(db_url=f"sqlite:///{tmp_path}")
            loaded = store_b.get(dag.id)
            assert loaded is not None
            assert loaded.id == dag.id
            assert loaded.name == "persist-dag"
            assert len(loaded.nodes) == 2
            node_ids = list(loaded.nodes.keys())
            assert len(node_ids) == 2
            # Verify dep relationship
            for n in loaded.nodes.values():
                if n.description == "Persist B":
                    assert n.deps == [a.id]
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_restart_recovery(self):
        """Data survives store close/reopen — verify node-level field fidelity."""
        import tempfile, os
        tmpf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp_path = tmpf.name
        tmpf.close()

        try:
            store_a = DAGStore(db_url=f"sqlite:///{tmp_path}")
            a = _make_node("A")
            a.id = "node-a"
            b = _make_node("B", deps=["node-a"])
            b.id = "node-b"
            dag = _make_dag(a, b, name="recovery")

            a.status = NodeStatus.COMPLETED
            a.result = "done"
            store_a.save(dag)

            # Close and reload
            store_b = DAGStore(db_url=f"sqlite:///{tmp_path}")
            reloaded = store_b.get(dag.id)
            assert reloaded is not None
            ra = reloaded.nodes["node-a"]
            rb = reloaded.nodes["node-b"]
            assert ra.status == NodeStatus.COMPLETED
            assert ra.result == "done"
            assert rb.status == NodeStatus.PENDING
            assert rb.deps == ["node-a"]
        finally:
            os.unlink(tmp_path)


# ── Phase 9: Retry ──


class TestDAGRetry:
    """Failed node retry via max_retry field."""

    @pytest.mark.asyncio
    async def test_failed_node_retry(self):
        """Node with max_retry=2 succeeds on 3rd attempt."""
        reset_dag_store()
        store = DAGStore(db_url="sqlite:///:memory:")
        import backend.services.dag.executor as _de
        _de._dag_store = store

        rt = MagicMock()
        fail_count = 0

        async def flaky_execute(description="", priority=2, intent="",
                                 provider=None, model=None,
                                 api_key=None, base_url=None, wait=False,
                                 **kwargs):
            nonlocal fail_count
            fail_count += 1
            task = MagicMock()
            if fail_count < 3:
                task.status = "FAILED"
                task.result = ""
                task.error = "simulated error"
            else:
                task.status = "COMPLETED"
                task.result = "success on attempt 3"
                task.error = ""
            task.id = f"mock_{fail_count}"
            return task

        rt.execute = AsyncMock(side_effect=flaky_execute)

        node = _make_node("Flaky task", max_retry=2)
        dag = _make_dag(node)
        await execute_dag(dag, rt)
        assert node.status == NodeStatus.COMPLETED
        assert node.retry_count == 2  # 2 retries, 3 total attempts
        assert node.result == "success on attempt 3"

    @pytest.mark.asyncio
    async def test_exhausted_retry_fails(self):
        """Node with max_retry=0 never retries on failure."""
        reset_dag_store()
        store = DAGStore(db_url="sqlite:///:memory:")
        import backend.services.dag.executor as _de
        _de._dag_store = store

        rt = MagicMock()

        async def fail_once(description="", **kw):
            task = MagicMock()
            task.status = "FAILED"
            task.result = ""
            task.error = "permanent failure"
            task.id = "mock_1"
            return task

        rt.execute = AsyncMock(side_effect=fail_once)

        node = _make_node("Fails once", max_retry=0)
        dag = _make_dag(node)
        await execute_dag(dag, rt)
        assert node.status == NodeStatus.FAILED
        assert node.retry_count == 1  # one attempt, no retry


# ── Phase 9: Execution Relation ──


class TestDAGExecutionRelation:
    """DAG node links back to the execution record."""

    @pytest.mark.asyncio
    async def test_execution_id_linked(self):
        reset_dag_store()
        store = DAGStore(db_url="sqlite:///:memory:")
        import backend.services.dag.executor as _de
        _de._dag_store = store

        rt = MagicMock()
        call_count = 0

        async def exec_with_id(description="", **kw):
            nonlocal call_count
            call_count += 1
            task = MagicMock()
            task.id = f"exec_{call_count}"
            task.status = "COMPLETED"
            task.result = f"result {call_count}"
            task.error = ""
            return task

        rt.execute = AsyncMock(side_effect=exec_with_id)

        a = _make_node("A")
        b = _make_node("B", deps=[a.id])
        dag = _make_dag(a, b)
        await execute_dag(dag, rt)

        # Each node should have a unique execution_id
        assert a.execution_id == "exec_1"
        assert b.execution_id == "exec_2"

        # Verify persisted in store
        persisted = store.get(dag.id)
        assert persisted is not None
        pa = persisted.nodes[a.id]
        pb = persisted.nodes[b.id]
        assert pa.execution_id == "exec_1"
        assert pb.execution_id == "exec_2"
