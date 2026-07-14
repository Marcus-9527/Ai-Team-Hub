"""DAG executor — DB-backed store, retry, execution record linkage, policy & approval."""
import asyncio
import logging
import time
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from backend.services.dag.core import (
    DAGDefinition,
    DAGNode,
    NodeStatus,
    get_ready_nodes,
    topological_sort,
)
from backend.services.runtime.executor import ExecutionRuntime
from backend.services.approval import get_approval_service
from backend.services.policy import get_policy_service
from backend.services.teammate_intelligence import TeammateSelector

logger = logging.getLogger("planner.dag_executor")


class DAGStore:
    """DB-backed DAG store.  Sync SQLAlchemy engine inline.

    ponytail: single sync engine, no async wrappers needed (SQLite fast enough
    for the route handlers that call get/list synchronously).
    """

    def __init__(self, db_url: str = ""):
        from backend.database import Base, get_sync_db_url

        self._db_url = db_url or get_sync_db_url()
        self._engine = create_engine(
            self._db_url,
            echo=False,
            connect_args={"check_same_thread": False} if "sqlite" in self._db_url else {},
        )
        # Auto-create tables
        Base.metadata.create_all(self._engine)

    # ── Save ──

    def save(self, dag: DAGDefinition) -> None:
        """Upsert DAG + all nodes."""
        from backend.models import DAGDefinitionModel, DAGNodeModel

        with SyncSession(self._engine) as session:
            existing = session.get(DAGDefinitionModel, dag.id)
            if existing:
                existing.name = dag.name
                existing.status = "CREATED"
            else:
                session.add(DAGDefinitionModel(
                    id=dag.id, name=dag.name, status="CREATED",
                ))
            session.commit()

            for node in dag.nodes.values():
                node_row = session.get(DAGNodeModel, node.id)
                if node_row:
                    node_row.description = node.description
                    node_row.teammate = node.teammate
                    node_row.deps = node.deps
                    node_row.status = node.status.value
                    node_row.max_retry = node.max_retry
                    node_row.retry_count = node.retry_count
                    node_row.strategy = node.strategy
                    node_row.require_approval = "1" if node.require_approval else "0"
                    node_row.result = node.result
                    node_row.error = node.error
                    node_row.execution_id = node.execution_id
                    node_row.required_skills = node.required_skills
                    node_row.selected_teammate_id = node.selected_teammate_id
                    node_row.assigned_at = node.assigned_at
                else:
                    session.add(DAGNodeModel(
                        id=node.id, dag_id=dag.id,
                        description=node.description,
                        teammate=node.teammate,
                        deps=node.deps,
                        required_skills=node.required_skills,
                        selected_teammate_id=node.selected_teammate_id,
                        assigned_at=node.assigned_at,
                        status=node.status.value,
                        max_retry=node.max_retry,
                        retry_count=node.retry_count,
                        strategy=node.strategy,
                        result=node.result,
                        error=node.error,
                        execution_id=node.execution_id,
                    ))
            session.commit()

    # ── Get ──

    def get(self, dag_id: str) -> Optional[DAGDefinition]:
        from backend.models import DAGDefinitionModel, DAGNodeModel

        with SyncSession(self._engine) as session:
            dag_row = session.get(DAGDefinitionModel, dag_id)
            if not dag_row:
                return None
            dag = DAGDefinition(name=dag_row.name)
            dag.id = dag_row.id
            node_rows = (
                session.query(DAGNodeModel)
                .filter(DAGNodeModel.dag_id == dag_id)
                .all()
            )
            for nr in node_rows:
                node = DAGNode(
                    description=nr.description or "",
                    teammate=nr.teammate or "",
                    deps=nr.deps or [],
                    max_retry=nr.max_retry or 0,
                    strategy=nr.strategy or "linear",
                    required_skills=nr.required_skills or [],
                    selected_teammate_id=nr.selected_teammate_id or "",
                )
                node.id = nr.id
                node.status = NodeStatus(nr.status or "PENDING")
                node.require_approval = (nr.require_approval or "0") == "1"
                node.result = nr.result or ""
                node.error = nr.error or ""
                node.execution_id = nr.execution_id or ""
                node.retry_count = nr.retry_count or 0
                node.assigned_at = nr.assigned_at or 0.0
                dag.add_node(node)
            return dag

    # ── List ──

    def list(self) -> list[DAGDefinition]:
        from backend.models import DAGDefinitionModel

        with SyncSession(self._engine) as session:
            rows = session.query(DAGDefinitionModel).order_by(
                DAGDefinitionModel.created_at.desc()
            ).all()
            return [self.get(r.id) for r in rows if r]

    # ── Helpers ──

    def link_execution(self, node_id: str, execution_id: str) -> None:
        """Link an execution record to a DAG node."""
        from backend.models import DAGNodeModel

        with SyncSession(self._engine) as session:
            nr = session.get(DAGNodeModel, node_id)
            if nr:
                nr.execution_id = execution_id
                session.commit()

    def update_node_status(self, node_id: str, status: str,
                           result: str = "", error: str = "",
                           retry_count: int = 0) -> None:
        from backend.models import DAGNodeModel

        with SyncSession(self._engine) as session:
            nr = session.get(DAGNodeModel, node_id)
            if nr:
                nr.status = status
                nr.result = result
                nr.error = error
                nr.retry_count = retry_count
                session.commit()


_dag_store: Optional[DAGStore] = None


def get_dag_store() -> DAGStore:
    global _dag_store
    if _dag_store is None:
        _dag_store = DAGStore()
    return _dag_store


def reset_dag_store() -> None:
    """Reset singleton (testing)."""
    global _dag_store
    _dag_store = None


class DagExecutor:
    """Executes a DAG by dispatching ready nodes to ExecutionRuntime.

    Supports retry per node (max_retry / strategy) and links execution records.
    """

    def __init__(self, runtime: ExecutionRuntime):
        self._runtime = runtime

    async def execute_dag(self, dag: DAGDefinition) -> DAGDefinition:
        topological_sort(dag)  # raises on cycle

        store = get_dag_store()
        store.save(dag)

        while True:
            ready = get_ready_nodes(dag)
            if not ready:
                break

            # Sequential assignment before parallel execution (prevents duplicate)
            assigned = {n.teammate for n in dag.nodes.values() if n.teammate}
            for node in ready:
                if node.required_skills and not node.teammate:
                    try:
                        profiles = await TeammateSelector.recommend_by_skills(
                            node.required_skills, top_n=1,
                            exclude_teammate_names=assigned,
                        )
                        if profiles:
                            node.teammate = profiles[0].name
                            node.selected_teammate_id = profiles[0].id
                            node.assigned_at = time.time()
                            assigned.add(node.teammate)
                            logger.info("[DAG] auto-assigned %s → node %s",
                                        node.teammate, node.id[:8])
                    except Exception:
                        logger.warning("[DAG] auto-assignment failed for node %s", node.id[:8])
            tasks = [self._run_node(dag, node) for node in ready]
            await asyncio.gather(*tasks)
            store.save(dag)

        return dag

    async def _run_node(self, dag: DAGDefinition, node: DAGNode,
                        allowed_teammates: list[str] | None = None,
                        allowed_tools: list[str] | None = None,
                        allowed_task_types: list[str] | None = None) -> None:
        """Execute a single DAG node with policy check + optional approval gate."""
        # ── Policy check ──
        policy = get_policy_service()
        policy_result = policy.evaluate_node(
            teammate=node.teammate,
            strategy=node.strategy,
            allowed_teammates=allowed_teammates,
            allowed_tools=allowed_tools,
            allowed_task_types=allowed_task_types,
        )
        if not policy_result.allowed:
            node.status = NodeStatus.FAILED
            node.error = f"POLICY_BLOCKED: {policy_result.reason}"
            logger.warning("[DAG] node %s blocked by policy: %s",
                           node.id, policy_result.reason)
            return

        # ── Approval gate ──
        if node.require_approval:
            approval_svc = get_approval_service()
            rec = approval_svc.create(
                execution_id=dag.id,
                dag_node_id=node.id,
                requested_by=node.teammate or "",
            )
            node.status = NodeStatus.PENDING  # stays PENDING until approved
            logger.info("[DAG] node %s awaiting approval (%s)",
                        node.id, rec.id)
            ok = await rec.wait()
            if not ok:
                node.status = NodeStatus.FAILED
                node.error = "REJECTED: node approval was rejected or timed out"
                logger.warning("[DAG] node %s approval rejected/timeout", node.id)
                return

        # ── Execution retry loop ──
        while node.retry_count <= node.max_retry:
            node.status = NodeStatus.RUNNING
            try:
                task = await self._runtime.execute(
                    description=node.description,
                    teammate=node.teammate,
                    wait=True,
                )
                node.execution_id = task.id
                node.result = task.result
                if task.status == "COMPLETED":
                    node.status = NodeStatus.COMPLETED
                    return
                node.error = task.error
            except Exception as e:
                node.error = f"{type(e).__name__}: {e}"

            node.retry_count += 1
            if node.retry_count <= node.max_retry:
                node.status = NodeStatus.PENDING
                if node.strategy == "exponential":
                    await asyncio.sleep(2 ** node.retry_count)
                else:
                    await asyncio.sleep(1)

        node.status = NodeStatus.FAILED
