"""
test_memory.py — Memory Engine Unit Tests

Covers:
  1. memory_namespaces: namespace creation/lookup
  2. memory (intelligence layer): storage + retrieval
  3. memory_summarizer: turn processing stub
  4. ExecutionMemory: MAEOS memory save/load
"""
import pytest
from unittest.mock import AsyncMock, patch


class TestMemoryStore:
    """Basic memory storage operations."""

    def test_memory_namespace_lookup(self):
        """Memory namespace should be creatable and reusable."""
        from backend.services.memory_namespaces import get_namespace, MemoryNamespace

        ns = get_namespace("tm_001")
        assert isinstance(ns, MemoryNamespace)
        assert ns.teammate_id == "tm_001"

        # Same ID returns same namespace
        ns2 = get_namespace("tm_001")
        assert ns2 is ns

    def test_memory_summarizer_interval(self):
        """Memory summarizer should have SUMMARY_INTERVAL."""
        from backend.services.memory_summarizer import SUMMARY_INTERVAL
        assert SUMMARY_INTERVAL == 10

    def test_memory_summarizer_function(self):
        """Memory summarizer should export process_conversation_turn."""
        from backend.services.memory_summarizer import process_conversation_turn
        assert callable(process_conversation_turn)


class TestWorkspaceMemory:
    """Workspace-level memory operations."""

    @pytest.mark.asyncio
    async def test_execution_memory(self):
        """ExecutionMemory from MAEOS should work independently."""
        from backend.services.maeos import ExecutionMemory, Task, TaskStatus

        mem = ExecutionMemory(max_entries=10)
        assert mem.stats()["total_entries"] == 0

        task = Task(
            id="test_mem_1",
            description="Test memory task",
            status=TaskStatus.COMPLETED,
            result="Hello from memory test",
        )
        saved_id = mem.save(task)
        assert saved_id == task.id
        assert mem.stats()["total_entries"] == 1

        loaded = mem.load("test_mem_1")
        assert loaded is not None
        assert loaded["result"] == "Hello from memory test"

    def test_workspace_memory_import(self):
        """Workspace memory module should be importable."""
        from backend.services.workspace_memory import WorkspaceMemory
        assert WorkspaceMemory is not None
