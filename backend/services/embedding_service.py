"""
embedding_service.py — Embedding Generation + Vector Retrieval

Features:
  - Local deterministic embedding (no external API needed)
  - Cosine similarity search with SQLite fallback
  - Query embedding cache + retrieval result cache
  - User-scoped retrieval (no cross-user leakage)
"""
import json
import math
import hashlib
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from collections import OrderedDict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# Embedding Configuration
# ═══════════════════════════════════════════════════════════

EMBEDDING_DIM = 384  # Same dimension as sentence-transformers for compatibility

# ═══════════════════════════════════════════════════════════
# Local Deterministic Embedding
# ═══════════════════════════════════════════════════════════

def _tokenize(text: str) -> List[str]:
    """Simple tokenizer: split on whitespace + punctuation, keep Chinese chars."""
    import re
    tokens = re.findall(r'[\u4e00-\u9fff]|[a-zA-Z0-9]+', text.lower())
    return tokens


def _hash_token(token: str, dim: int) -> List[float]:
    """Hash a token into a vector using multiple hash functions."""
    vec = [0.0] * dim
    # Use multiple hash seeds for better distribution
    for seed in range(4):
        h = hashlib.md5(f"{seed}:{token}".encode("utf-8")).hexdigest()
        for i in range(0, len(h), 2):
            idx = int(h[i:i+2], 16) % dim
            # Alternate +1 and -1 for better distribution
            val = 1.0 if int(h[i], 16) < 8 else -1.0
            vec[idx] += val
    return vec


def embed_text(text: str, dim: int = EMBEDDING_DIM) -> List[float]:
    """
    Generate a deterministic embedding for text.

    Uses a weighted hash-based approach that captures term frequency.
    Similar texts will have similar vectors (cosine similarity works well).
    """
    tokens = _tokenize(text)
    if not tokens:
        return [0.0] * dim

    vec = [0.0] * dim
    token_counts: Dict[str, int] = {}
    for token in tokens:
        token_counts[token] = token_counts.get(token, 0) + 1

    for token, count in token_counts.items():
        token_vec = _hash_token(token, dim)
        # Weight by log of term frequency
        weight = 1.0 + math.log(count + 1)
        for i in range(dim):
            vec[i] += token_vec[i] * weight

    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


# ═══════════════════════════════════════════════════════════
# Vector Operations
# ═══════════════════════════════════════════════════════════

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ═══════════════════════════════════════════════════════════
# LRU Cache
# ═══════════════════════════════════════════════════════════

class LRUCache:
    """Simple LRU cache for embeddings and retrieval results."""

    def __init__(self, max_size: int = 256):
        self._cache: OrderedDict = OrderedDict()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            self._cache.move_to_end(key)
            self._hits += 1
            return self._cache[key]
        self._misses += 1
        return None

    def put(self, key: str, value: Any):
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def clear(self):
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(1, self._hits + self._misses), 3),
        }


# ═══════════════════════════════════════════════════════════
# Embedding Service
# ═══════════════════════════════════════════════════════════

class EmbeddingService:
    """Service for generating embeddings and performing vector retrieval."""

    def __init__(self, cache_size: int = 256):
        self._embed_cache = LRUCache(max_size=cache_size)
        self._query_cache = LRUCache(max_size=cache_size)

    def embed(self, text: str) -> List[float]:
        """Generate embedding with cache."""
        cache_key = hashlib.md5(text.encode()).hexdigest()
        cached = self._embed_cache.get(cache_key)
        if cached is not None:
            return cached
        vec = embed_text(text)
        self._embed_cache.put(cache_key, vec)
        return vec

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        return [self.embed(t) for t in texts]

    def search(
        self,
        query_embedding: List[float],
        chunks: List[Dict[str, Any]],
        top_k: int = 5,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform cosine similarity search.

        Args:
            query_embedding: Query vector
            chunks: List of {chunk_id, file_id, content, embedding, user_id}
            top_k: Number of results to return
            user_id: If provided, filter by user_id (isolation)

        Returns:
            List of results with score, sorted by descending similarity
        """
        results = []
        for chunk in chunks:
            # User isolation
            if user_id and chunk.get("user_id") and chunk["user_id"] != user_id:
                continue
            chunk_embedding = chunk.get("embedding")
            if not chunk_embedding:
                continue
            score = cosine_similarity(query_embedding, chunk_embedding)
            results.append({
                "chunk_id": chunk["chunk_id"],
                "file_id": chunk["file_id"],
                "content": chunk["content"],
                "score": round(score, 4),
                "index": chunk.get("index", 0),
            })

        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def cached_search(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        top_k: int = 5,
        user_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Search with query-level cache.

        Returns:
            (results, from_cache)
        """
        cache_key = f"{user_id}:{query}:{top_k}"
        cached = self._query_cache.get(cache_key)
        if cached is not None:
            return cached, True

        query_embedding = self.embed(query)
        results = self.search(query_embedding, chunks, top_k, user_id)
        self._query_cache.put(cache_key, results)
        return results, False

    @property
    def cache_stats(self) -> Dict[str, Any]:
        return {
            "embedding_cache": self._embed_cache.stats,
            "query_cache": self._query_cache.stats,
        }


# ═══════════════════════════════════════════════════════════
# Database Integration Helpers
# ═══════════════════════════════════════════════════════════

async def store_chunks_in_db(chunks: List, file_id: str, session) -> int:
    """Store chunk embeddings in database."""
    from backend.models import FileChunk
    count = 0
    for chunk in chunks:
        embedding_vec = embed_text(chunk.content)
        db_chunk = FileChunk(
            id=chunk.chunk_id,
            file_id=file_id,
            content=chunk.content,
            index=str(chunk.index),
            embedding=json.dumps(embedding_vec),
            metadata_json=chunk.metadata,
        )
        session.add(db_chunk)
        count += 1
    await session.commit()
    return count


async def load_chunks_for_file(file_id: str, session) -> List[Dict[str, Any]]:
    """Load chunks with embeddings from database."""
    from sqlalchemy import select
    from backend.models import FileChunk
    result = await session.execute(
        select(FileChunk)
        .where(FileChunk.file_id == file_id)
        .order_by(FileChunk.index)
    )
    chunks = result.scalars().all()
    return [
        {
            "chunk_id": c.id,
            "file_id": c.file_id,
            "content": c.content,
            "index": int(c.index),
            "embedding": json.loads(c.embedding) if c.embedding else None,
        }
        for c in chunks
    ]


async def load_all_chunks_for_user(user_id: str, session) -> List[Dict[str, Any]]:
    """Load all chunks for a specific user (for scoped retrieval)."""
    from sqlalchemy import select
    from backend.models import FileChunk, FileUpload
    result = await session.execute(
        select(FileChunk, FileUpload)
        .join(FileUpload, FileChunk.file_id == FileUpload.id)
        .where(FileUpload.user_id == user_id)
        .order_by(FileChunk.file_id, FileChunk.index)
    )
    rows = result.all()
    chunks = []
    for chunk, file_upload in rows:
        chunks.append({
            "chunk_id": chunk.id,
            "file_id": chunk.file_id,
            "content": chunk.content,
            "index": int(chunk.index),
            "embedding": json.loads(chunk.embedding) if chunk.embedding else None,
            "user_id": file_upload.user_id,
        })
    return chunks


# ═══════════════════════════════════════════════════════════
# Global Service Instance
# ═══════════════════════════════════════════════════════════

_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
