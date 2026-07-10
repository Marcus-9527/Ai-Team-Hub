"""
rule_evaluator.py — RuleBasedEvaluator

Deterministic, zero-LLM quality evaluation using text analysis heuristics.

Metrics:
  - completeness (0.0–1.0): keyword overlap between expected_output and actual
  - coherence (0.0–1.0): structural quality (paragraphs, sentences, connectors)
  - overall_quality (0.0–1.0): weighted combination (completeness * 0.6 + coherence * 0.4)
  - accuracy: None (reserved for future LLM-based evaluation)
"""

import re
from typing import Optional

from backend.services.task.evaluation.base import (
    ExecutionEvaluator,
    EvaluationResult,
)

# ── Stopwords for keyword extraction ──
_STOPWORDS: set[str] = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "this", "that", "these", "those", "it", "its", "they", "them", "their",
    "we", "our", "you", "your", "he", "she", "his", "her", "him",
    "not", "no", "nor", "so", "if", "then", "than", "too", "very",
    "just", "also", "about", "above", "after", "again", "all", "any",
    "both", "each", "few", "more", "most", "other", "some", "such",
    "only", "own", "same", "into", "over", "under", "up", "out",
    "here", "there", "when", "where", "why", "how", "what", "which",
    "who", "whom", "while", "during", "before", "between", "through",
    "because", "since", "until", "like", "than", "per",
}

# ── Coherence markers ──
_LOGICAL_CONNECTORS: set[str] = {
    "therefore", "however", "furthermore", "moreover", "nevertheless",
    "consequently", "additionally", "meanwhile", "otherwise", "accordingly",
    "first", "second", "third", "finally", "next", "then",
    "specifically", "particularly", "notably", "importantly",
    "in addition", "as a result", "for example", "for instance",
    "in conclusion", "in summary", "on the other hand",
    "in contrast", "as well as", "in particular",
    "firstly", "secondly", "thirdly",
}

# ── Default weights ──
W_COMPLETENESS = 0.6
W_COHERENCE = 0.4


class RuleBasedEvaluator(ExecutionEvaluator):
    """Rule-based quality evaluator using deterministic text heuristics.

    This evaluator does NOT use any LLM calls. It relies purely on
    text analysis: keyword overlap, sentence structure, paragraph
    detection, and logical connector presence.

    Use this as the default evaluator in Phase B. Replace with an
    LLM-based evaluator in a future phase when deeper semantic
    understanding is required.
    """

    async def evaluate(
        self,
        *,
        actual_output: str,
        expected_output: str = "",
        objective: str = "",
    ) -> EvaluationResult:
        """Evaluate output quality using rule-based heuristics."""
        output = actual_output or ""
        expected = expected_output or ""
        obj = objective or ""

        completeness = self._compute_completeness(output, expected, obj)
        coherence = self._compute_coherence(output)
        overall_quality = completeness * W_COMPLETENESS + coherence * W_COHERENCE

        details = {
            "completeness_method": "keyword_overlap" if expected else "length_proxy",
            "coherence_signals": self._get_coherence_signals(output),
            "expected_provided": bool(expected),
            "output_length": len(output),
        }

        return EvaluationResult(
            completeness=round(completeness, 4),
            coherence=round(coherence, 4),
            accuracy=None,
            overall_quality=round(overall_quality, 4),
            confidence=1.0,
            evaluator="rule",
            details=details,
        )

    # ── Completeness ──

    def _compute_completeness(
        self,
        output: str,
        expected: str,
        objective: str,
    ) -> float:
        """Score how completely the output covers expected content.

        Strategy:
          1. If expected_output is provided → keyword overlap ratio
          2. If only objective is provided → keyword overlap with objective
          3. If neither → length/structure proxy score
        """
        if not output.strip():
            return 0.0

        if expected.strip():
            return self._keyword_overlap_score(output, expected)

        if objective.strip():
            return min(self._keyword_overlap_score(output, objective) * 1.2, 1.0)

        # Length proxy when nothing to compare against
        return self._length_proxy_score(output)

    def _keyword_overlap_score(self, output: str, reference: str) -> float:
        """Compute keyword overlap ratio between output and reference text."""
        ref_keywords = self._extract_keywords(reference)
        if not ref_keywords:
            return self._length_proxy_score(output)

        out_lower = output.lower()
        matched = sum(1 for kw in ref_keywords if kw in out_lower)
        return matched / len(ref_keywords)

    def _length_proxy_score(self, text: str) -> float:
        """Heuristic quality based on output length and structure."""
        length = len(text.strip())
        if length == 0:
            return 0.0
        if length < 50:
            return 0.2
        if length < 200:
            return 0.5
        if length < 500:
            return 0.65
        # Has paragraphs AND substantial content → likely complete
        if "\n\n" in text:
            return 0.8
        return 0.7

    # ── Coherence ──

    def _compute_coherence(self, output: str) -> float:
        """Score how coherent / well-structured the output is."""
        text = output.strip()
        if not text:
            return 0.0

        signals = self._get_coherence_signals(text)
        score = 0.0

        # Base: non-empty
        score += 0.1

        # Has at least 2 sentences
        if signals["sentence_count"] >= 2:
            score += 0.15
        if signals["sentence_count"] >= 5:
            score += 0.1

        # Paragraphs
        if signals["has_paragraphs"]:
            score += 0.15
        if signals["paragraph_count"] >= 3:
            score += 0.1

        # Sentence quality
        if signals["avg_sentence_words"] is not None:
            avg = signals["avg_sentence_words"]
            if 8 <= avg <= 40:
                score += 0.1
            elif 5 <= avg <= 50:
                score += 0.05

        # End punctuation consistency
        if signals["good_endings_ratio"] >= 0.8:
            score += 0.1
        elif signals["good_endings_ratio"] >= 0.5:
            score += 0.05

        # Logical connectors
        if signals["connector_count"] >= 1:
            score += 0.1
        if signals["connector_count"] >= 3:
            score += 0.1

        return min(score, 1.0)

    def _get_coherence_signals(self, text: str) -> dict:
        """Extract coherence-relevant statistics from text."""
        sentences = self._split_sentences(text)
        sentence_count = len(sentences)
        paragraphs = re.split(r"\n\s*\n", text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]
        paragraph_count = len(paragraphs)

        # Average sentence length
        avg_words: Optional[float] = None
        if sentence_count > 0:
            word_counts = [len(s.split()) for s in sentences if s.strip()]
            if word_counts:
                avg_words = sum(word_counts) / len(word_counts)

        # End punctuation quality
        good_endings = sum(
            1 for s in sentences if s.strip() and s.strip()[-1] in ".!?"
        )
        good_ratio = good_endings / sentence_count if sentence_count > 0 else 0.0

        # Logical connectors
        text_lower = text.lower()
        connector_count = sum(
            1 for c in _LOGICAL_CONNECTORS if c in text_lower
        )

        return {
            "sentence_count": sentence_count,
            "has_paragraphs": paragraph_count > 1,
            "paragraph_count": paragraph_count,
            "avg_sentence_words": avg_words,
            "good_endings_ratio": good_ratio,
            "connector_count": connector_count,
        }

    # ── Helpers ──

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """Extract meaningful keywords from text (lowercase, no stopwords)."""
        words = re.findall(r"[a-zA-Z\u4e00-\u9fff]{3,}", text.lower())
        return [w for w in words if w not in _STOPWORDS]

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences on . ! ? boundaries."""
        raw = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in raw if s.strip()]
