"""
cache_kernel.py — Unified cache kernel.

Consolidated from:
  - semantic_cache/embedding_cache.py
  - semantic_cache/multi_layer_cache.py
  - semantic_cache/prompt_dedup.py
  - semantic_cache/request_normalizer.py
  - semantic_cache/semantic_cache_key.py
  - cache_prefix_builder.py
  - cache_warmup_service.py
"""

import json
import math
import re
import hashlib
import logging
import time
import asyncio
from enum import Enum
from dataclasses import dataclass, field
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger("cache_kernel")


# === Request Normalizer (from request_normalizer.py) ===

class Intent(str, Enum):
    QUESTION = "question"
    CODE = "code"
    ANALYSIS = "analysis"
    REASONING = "reasoning"
    CREATIVE = "creative"
    PLANNING = "planning"
    MODIFICATION = "modification"


class Domain(str, Enum):
    PROGRAMMING = "programming"
    DATA = "data"
    DESIGN = "design"
    BUSINESS = "business"
    GENERAL = "general"
    MATH = "math"
    SYSTEM = "system"


@dataclass
class NormalizedRequest:
    raw: str
    intent: "Intent"
    domain: "Domain"
    complexity: float
    canonical: str
    keywords: list
    language: str
    has_code: bool
    has_question: bool
    entity_count: int

    def to_dict(self):
        return {
            "raw": self.raw[:100],
            "intent": self.intent.value,
            "domain": self.domain.value,
            "complexity": round(self.complexity, 3),
            "keywords": self.keywords[:10],
            "language": self.language,
        }


def normalize_request(text: str) -> "NormalizedRequest":
    canonical = _canonicalize(text)
    intent = _detect_intent(canonical)
    domain = _detect_domain(canonical)
    complexity = _score_complexity(canonical)
    keywords = _extract_keywords(canonical)
    has_code = bool(re.search(r"```|def |class |function|import Ii|#include", text))
    has_question = bool(re.search(r"[?？]", text))
    language = "zh" if re.search(r"[\u4e00-\u9fff]", text) else "en"
    entity_count = len(set(keywords))
    return NormalizedRequest(
        raw=text, intent=intent, domain=domain, complexity=complexity,
        canonical=canonical, keywords=keywords, language=language,
        has_code=has_code, has_question=has_question, entity_count=entity_count,
    )


def _canonicalize(text: str) -> str:
    """Aggressive canonicalization for cache key stability."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", "", text)  # strip punctuation
    text = re.sub(r"\d+", "#", text)  # normalize numbers to placeholder
    words = text.split()
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above", "below",
        "between", "out", "off", "over", "under", "again", "further", "then",
        "once", "here", "there", "when", "where", "why", "how", "all", "both",
        "each", "few", "more", "most", "other", "some", "such", "no", "nor",
        "not", "only", "own", "same", "so", "than", "too", "very", "just",
        "because", "but", "and", "or", "if", "while", "about", "up", "it",
        "its", "i", "me", "my", "we", "our", "you", "your", "he", "she",
        "they", "them", "his", "her", "their", "what", "which", "who",
        "的", "是", "在", "和", "了", "我", "你", "他", "她", "它",
        "们", "有", "与", "及", "或", "但", "如果", "因为", "所以",
    }
    words = [w for w in words if w not in stop and len(w) > 1]
    return " ".join(words)


def _detect_intent(text: str) -> "Intent":
    t = text.lower()
    if any(kw in t for kw in ["代码", "code", "编程", "class", "debug"]):
        return Intent.CODE
    if any(kw in t for kw in ["分析", "analyze", "数据", "趋势"]):
        return Intent.ANALYSIS
    if any(kw in t for kw in ["推理", "reasoning", "为什么"]):
        return Intent.REASONING
    if any(kw in t for kw in ["创意", "creative", "设计", "design"]):
        return Intent.CREATIVE
    if any(kw in t for kw in ["规划", "planning", "架构", "策略"]):
        return Intent.PLANNING
    if any(kw in t for kw in ["修改", "修复", "fix", "update"]):
        return Intent.MODIFICATION
    return Intent.QUESTION


def _detect_domain(text: str) -> "Domain":
    t = text.lower()
    if any(kw in t for kw in ["编程", "code", "function", "变量"]):
        return Domain.PROGRAMMING
    if any(kw in t for kw in ["数据", "sql", "database"]):
        return Domain.DATA
    if any(kw in t for kw in ["设计", "design", "ui", "ux"]):
        return Domain.DESIGN
    if any(kw in t for kw in ["数学", "math", "公式", "计算"]):
        return Domain.MATH
    if any(kw in t for kw in ["系统", "system", "架构"]):
        return Domain.SYSTEM
    return Domain.GENERAL


def _score_complexity(text: str) -> float:
    wc = len(text.split())
    if wc < 20:
        return 0.2
    elif wc < 50:
        return 0.5
    elif wc < 100:
        return 0.7
    return 0.85


def _extract_keywords(text: str) -> list:
    stop = {"the", "a", "an", "is", "are", "的", "是", "在", "和", "了", "我", "你"}
    words = re.findall(r"\b\w+\b", text)
    return [w for w in words if w not in stop and len(w) > 1][:20]


def compute_semantic_key(text: str, layer: str = "output") -> str:
    """Compute a semantic cache key from request text."""
    normalized = _canonicalize(text)
    keywords = _extract_keywords(normalized)
    key_str = f"{layer}:{' '.join(keywords[:10])}"
    return hashlib.md5(key_str.encode()).hexdigest()


# === Multi-Layer Cache (consolidated from multi_layer_cache.py) ===

class CacheLayer(str, Enum):
    PLANNER = "planner"
    EXECUTOR = "executor"
    OUTPUT = "output"


class MultiLayerCache:
    """Simple in-memory multi-layer cache."""

    def __init__(self, max_size: int = 1000):
        self._layers = {layer: OrderedDict() for layer in CacheLayer}
        self._max_size = max_size

    def get(self, key: str, layer: CacheLayer = CacheLayer.OUTPUT) -> Optional[Any]:
        d = self._layers.get(layer, {})
        if key in d:
            d.move_to_end(key)
            return d[key]
        return None

    def put(self, key: str, value: Any, layer: CacheLayer = CacheLayer.OUTPUT):
        d = self._layers.setdefault(layer, OrderedDict())
        d[key] = value
        if len(d) > self._max_size:
            d.popitem(last=False)

    def stats(self):
        return {layer.value: len(d) for layer, d in self._layers.items()}


_multi_layer_cache = MultiLayerCache()


def get_multi_layer_cache() -> MultiLayerCache:
    return _multi_layer_cache


# === Embedding Cache (consolidated from embedding_cache.py) ===

class EmbeddingCache:
    """Cache for computed embeddings."""

    def __init__(self, max_size: int = 5000):
        self._cache = OrderedDict()
        self._max_size = max_size

    def get(self, key: str) -> Optional[list]:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, value: list):
        self._cache[key] = value
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def stats(self):
        return {"size": len(self._cache)}


_embedding_cache = EmbeddingCache()


def get_embedding_cache() -> EmbeddingCache:
    return _embedding_cache


# === Prompt Deduplicator (consolidated from prompt_dedup.py) ===

class PromptDeduplicator:
    """Track recent prompts to avoid duplicate processing."""

    def __init__(self, max_size: int = 200):
        self._seen = OrderedDict()
        self._max_size = max_size

    def is_duplicate(self, prompt: str) -> bool:
        key = hashlib.md5(prompt.encode()).hexdigest()
        if key in self._seen:
            self._seen.move_to_end(key)
            return True
        self._seen[key] = True
        if len(self._seen) > self._max_size:
            self._seen.popitem(last=False)
        return False

    def stats(self):
        return {"size": len(self._seen)}


_prompt_deduplicator = PromptDeduplicator()


def get_prompt_deduplicator() -> PromptDeduplicator:
    return _prompt_deduplicator




