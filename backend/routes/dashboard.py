"""routes/dashboard.py — Product Dashboard aggregator (Phase 15).

Aggregates existing observability data into a single /api/dashboard
response. No core Runtime/DAG/Memory logic is modified.
"""
import logging

from fastapi import APIRouter
from sqlalchemy import select, func

from backend.database import async_session
from backend.models import Teammate, DAGDefinitionModel, DAGNodeModel
from backend.services.runtime.execution_store import get_execution_store
from backend.services.memory.memory_service import get_memory_service

logger = logging.getLogger("routes.dashboard")
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


async def _teammate_stats() -> dict:
    """Aggregate teammate-level statistics."""
    async with async_session() as session:
        result = await session.execute(
            select(Teammate).order_by(Teammate.created_at)
        )
        teammates = result.scalars().all()

    total = len(teammates)
    total_execs = sum(t.execution_count or 0 for t in teammates)
    avg_success = (
        sum(t.success_rate or 0.0 for t in teammates) / total
        if total > 0 else 0.0
    )

    # ponytail: growth = count by month, from created_at
    return {
        "total_teammates": total,
        "total_executions": total_execs,
        "avg_success_rate": round(avg_success, 4),
        "growth": [
            {"name": t.name, "created_at": t.created_at.isoformat() if t.created_at else None}
            for t in teammates
        ],
    }


async def _dag_status() -> dict:
    """Aggregate DAG status counts."""
    async with async_session() as session:
        dag_result = await session.execute(select(DAGDefinitionModel))
        dags = dag_result.scalars().all()

        node_counts_q = select(
            DAGNodeModel.status, func.count(DAGNodeModel.id)
        ).group_by(DAGNodeModel.status)
        node_result = await session.execute(node_counts_q)
        by_status = dict(node_result.fetchall())

    return {
        "total_dags": len(dags),
        "dag_nodes_by_status": by_status,
    }


async def _memory_stats() -> dict:
    """Get memory storage statistics."""
    svc = get_memory_service()
    return await svc.stats()


@router.get("")
async def dashboard():
    """Aggregated product dashboard — one call, all KPIs."""
    store = get_execution_store()

    exec_stats = await store.astats()
    team_stats = await _teammate_stats()
    dag_stats = await _dag_status()
    mem_stats = await _memory_stats()

    return {
        "execution": exec_stats,
        "teammate": team_stats,
        "dag": dag_stats,
        "memory": mem_stats,
    }
