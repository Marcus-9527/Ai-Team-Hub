"""Test the dashboard aggregator API (Phase 15).

Only tests stateless / non-DB-dependent paths.  The /api/dashboard endpoint
is a thin aggregator over existing stores verified by their own tests.
"""
import pytest

from backend.services.runtime.execution_store import get_execution_store
from backend.services.memory.memory_service import get_memory_service


@pytest.mark.asyncio
async def test_dashboard_memory_stats():
    """Memory stats returns expected shape."""
    svc = get_memory_service()
    stats = await svc.stats()
    assert "total_items" in stats
    assert "by_type" in stats
    assert isinstance(stats["total_items"], int)
    assert isinstance(stats["by_type"], dict)


@pytest.mark.asyncio
async def test_dashboard_execution_stats():
    """Execution stats from existing store."""
    store = get_execution_store()
    stats = await store.astats()
    assert "total_executions" in stats
    assert "completed" in stats
    assert "failed" in stats
    assert "running" in stats
    assert "total_tokens" in stats
    assert "total_cost_micro_usd" in stats


@pytest.mark.asyncio
async def test_dashboard_dag_stats():
    """DAG status returns expected keys (no DB dependency)."""
    from backend.routes.dashboard import _dag_status
    stats = await _dag_status()
    assert "total_dags" in stats
    assert "dag_nodes_by_status" in stats
    assert isinstance(stats["total_dags"], int)
