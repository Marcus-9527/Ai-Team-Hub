"""Memory Intelligence Layer — AI Team Hub V3.1.

A pure-dataclass memory layer that provides intelligent context
for Planner and other consumers. No SQLAlchemy Model references.

Structure:
  memory_types.py      — MemoryType enum, MemoryItem dataclass
  memory_service.py    — Memory storage (CRUD, raw SQL persistence)
  memory_retriever.py  — Context-aware memory retrieval
  memory_retriever.py  — Context-aware memory retrieval + relevance ranking
  memory_compressor.py — Token-budget-aware compression
"""

from backend.services.memory.memory_types import MemoryType, MemoryItem
from backend.services.memory.memory_service import MemoryService, get_memory_service
from backend.services.memory.memory_retriever import MemoryRetriever, RetrievalResult, MemoryRanker, RankedItem
from backend.services.memory.memory_compressor import MemoryCompressor, CompressedContext
from backend.services.memory.memory_event_handler import MemoryTaskHook
from backend.services.memory.memory_context import MemoryContext, get_memory_context

__all__ = [
    "MemoryType",
    "MemoryItem",
    "MemoryService",
    "get_memory_service",
    "MemoryRetriever",
    "RetrievalResult",
    "MemoryRanker",
    "RankedItem",
    "MemoryCompressor",
    "CompressedContext",
    "MemoryTaskHook",
    "MemoryContext",
    "get_memory_context",
]
