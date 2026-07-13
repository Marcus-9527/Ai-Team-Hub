"""
evaluation.py — Phase B: Rule-Based Step-Level Evaluation

Implements ExecutionEvaluator interface with rule-based scoring:
  - Completeness: keyword overlap with expected output, or length proxy
  - Coherence: structural quality (paragraphs, connectors, sentencelength)
  - Accuracy: None (reserved for LLM judge in future)
  - Overall quality: weighted combination (completeness*0.6 + coherence*0.4)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional


# ── Connector words (English) ──
_CONNECTORS = {
    "first", "second", "third", "next", "then", "finally", "lastly",
    "therefore", "thus", "hence", "consequently", "as a result",
    "furthermore", "moreover", "additionally", "in addition",
    "however", "nevertheless", "nonetheless", "on the other hand",
    "specifically", "particularly", "notably", "for example",
    "for instance", "in conclusion", "in summary", "overall",
    "meanwhile", "subsequently", "previously", "conversely",
    "accordingly", "alternatively", "besides", "indeed",
}


@dataclass
class EvaluationResult:
    """Result of a single evaluation run."""
    completeness: float = 0.0
    coherence: float = 0.0
    accuracy: Optional[float] = None
    overall_quality: float = 0.0
    evaluator: str = "rule"
    confidence: float = 1.0


class ExecutionEvaluator:
    """Interface for execution output evaluators."""

    async def evaluate(
        self,
        actual_output: str,
        expected_output: str = "",
        objective: str = "",
    ) -> EvaluationResult:
        raise NotImplementedError


class RuleBasedEvaluator(ExecutionEvaluator):
    """
    Rule-based evaluator using heuristics.

    Completeness:
      - If expected_output provided: keyword overlap ratio
      - If not: length-based proxy (50-500+ chars → 0.2-0.9)
    Coherence:
      - Paragraph count * 0.15 (cap 0.4)
      - Connector ratio * 1.5 (cap 0.4)
      - Normalised sentence-length stddev bonus (cap 0.2)
    Overall quality: completeness*0.6 + coherence*0.4
    """

    async def evaluate(
        self,
        actual_output: str = "",
        expected_output: str = "",
        objective: str = "",
    ) -> EvaluationResult:
        text = (actual_output or "").strip()
        if not text:
            return EvaluationResult()

        completeness = self._score_completeness(text, expected_output)
        coherence = self._score_coherence(text)
        overall = round(completeness * 0.6 + coherence * 0.4, 4)

        return EvaluationResult(
            completeness=round(completeness, 4),
            coherence=round(coherence, 4),
            accuracy=None,
            overall_quality=overall,
            evaluator="rule",
            confidence=1.0,
        )

    # ── Completeness ──

    @staticmethod
    def _score_completeness(text: str, expected: str) -> float:
        if expected.strip():
            return _keyword_overlap(text, expected)
        return _length_proxy(text)

    # ── Coherence ──

    @staticmethod
    def _score_coherence(text: str) -> float:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        sentences = _split_sentences(text)
        words = text.split()
        word_count = len(words)
        if word_count < 5:
            return 0.0

        score = 0.0

        # Paragraph bonus (max 0.4)
        para_count = len(paragraphs)
        if para_count > 1:
            score += min(para_count * 0.15, 0.4)

        # Connector bonus (max 0.4)
        connector_count = sum(1 for w in words if w.strip(".,!?;:").lower() in _CONNECTORS)
        connector_ratio = connector_count / word_count
        score += min(connector_ratio * 1.5, 0.4)

        # Sentence-length variety bonus (max 0.2)
        if len(sentences) >= 3:
            lengths = [len(s.split()) for s in sentences]
            mean_len = sum(lengths) / len(lengths)
            if mean_len > 0:
                variance = sum((l - mean_len) ** 2 for l in lengths) / len(lengths)
                stddev = math.sqrt(variance)
                normalised = min(stddev / mean_len, 1.0)
                score += normalised * 0.2

        return min(score, 1.0)


# ── Helpers ──


def _keyword_overlap(text: str, expected: str) -> float:
    """Fraction of significant keywords from expected found in text."""
    _keywords = set(re.findall(r"[a-zA-Z]\w{2,}", expected.lower()))
    if not _keywords:
        return _length_proxy(text)
    text_lower = text.lower()
    found = sum(1 for kw in _keywords if kw in text_lower)
    return found / len(_keywords)


def _length_proxy(text: str) -> float:
    """Length-based completeness estimate."""
    char_count = len(text)
    if char_count < 50:
        return 0.2
    if char_count < 150:
        return 0.4
    if char_count < 300:
        return 0.6
    if char_count < 500:
        return 0.7
    return min(0.9, 0.7 + (char_count - 500) / 5000 * 0.2)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on .!? followed by space or end."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]
