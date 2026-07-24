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
from backend.services.teammate_intelligence import TeammateSelector

logger = logging.getLogger("dag.executor")


class DAGStore:
    """DB-backed DAG store.  Sync SQLAlchemy engine, async-safe via to_thread.

    ponytail: all public methods are async wrappers around sync sessions,
    run via asyncio.to_thread so they never block the event loop.
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

    async def save(self, dag: DAGDefinition) -> None:
        """Upsert DAG + all nodes."""
        from backend.models import DAGDefinitionModel, DAGNodeModel

        def _sync():
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

        await asyncio.to_thread(_sync)

    # ── Get ──

    async def get(self, dag_id: str) -> Optional[DAGDefinition]:
        from backend.models import DAGDefinitionModel, DAGNodeModel

        def _sync():
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

        return await asyncio.to_thread(_sync)

    # ── List ──

    async def list(self) -> list[DAGDefinition]:
        from backend.models import DAGDefinitionModel

        def _sync():
            with SyncSession(self._engine) as session:
                rows = session.query(DAGDefinitionModel).order_by(
                    DAGDefinitionModel.created_at.desc()
                ).all()
                return [r.id for r in rows if r]

        ids = await asyncio.to_thread(_sync)
        result = []
        for dag_id in ids:
            d = await self.get(dag_id)
            if d:
                result.append(d)
        return result

    # ── Helpers ──

    async def bulk_update_node_statuses(self, nodes: list) -> None:
        """Bulk-write execution-time fields for many nodes — one session, one commit.

        ponytail: only touches columns that change during execution
        (status/result/error/retry_count/execution_id).  Skips the full-row
        SELECT+UPSERT that save() does per node.  Single commit, not 2 per call.
        """
        from backend.models import DAGNodeModel

        mappings = [
            {
                "id": n.id,
                "status": n.status.value,
                "result": n.result,
                "error": n.error,
                "retry_count": n.retry_count,
                "execution_id": n.execution_id,
            }
            for n in nodes
        ]
        if not mappings:
            return

        def _sync():
            with SyncSession(self._engine) as session:
                session.bulk_update_mappings(DAGNodeModel, mappings)
                session.commit()

        await asyncio.to_thread(_sync)

    async def link_execution(self, node_id: str, execution_id: str) -> None:
        """Link an execution record to a DAG node."""
        from backend.models import DAGNodeModel

        def _sync():
            with SyncSession(self._engine) as session:
                nr = session.get(DAGNodeModel, node_id)
                if nr:
                    nr.execution_id = execution_id
                    session.commit()

        await asyncio.to_thread(_sync)

    async def update_node_status(self, node_id: str, status: str,
                           result: str = "", error: str = "",
                           retry_count: int = 0) -> None:
        from backend.models import DAGNodeModel

        def _sync():
            with SyncSession(self._engine) as session:
                nr = session.get(DAGNodeModel, node_id)
                if nr:
                    nr.status = status
                    nr.result = result
                    nr.error = error
                    nr.retry_count = retry_count
                    session.commit()

        await asyncio.to_thread(_sync)


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


# ── Standalone DAG execution (replaces former DagExecutor class) ──


async def execute_dag(dag: DAGDefinition, runtime: ExecutionRuntime) -> DAGDefinition:
    """Execute a DAG by dispatching ready nodes to ExecutionRuntime.

    Inlined from the former DagExecutor class — callers (routes/dags.py)
    and tests import this directly.
    """
    topological_sort(dag)  # raises on cycle

    store = get_dag_store()
    await store.save(dag)

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
        tasks = [_run_node(runtime, dag, node) for node in ready]
        await asyncio.gather(*tasks)
        await store.bulk_update_node_statuses(list(dag.nodes.values()))

    return dag


async def _run_node(runtime: ExecutionRuntime, dag: DAGDefinition, node: DAGNode) -> None:
    """Execute a single DAG node with retry loop."""
    while node.retry_count <= node.max_retry:
        node.status = NodeStatus.RUNNING
        try:
            task = await runtime.execute(
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
