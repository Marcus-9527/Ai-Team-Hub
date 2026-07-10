"""
orchestrator/diversity.py — Cognitive diversity enforcement (anti-homogenization).

Extracted from orchestrator_core.py Section 6 for single responsibility.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("orchestrator.diversity")


# ═══════════════════════════════════════════════════════════════
# Diversity Report
# ═══════════════════════════════════════════════════════════════

@dataclass
class DiversityReport:
    homogenization_detected: bool = False
    similarity_score: float = 0.0
    violations: list = field(default_factory=list)
    details: str = ""
    
    def to_dict(self) -> dict:
        return {
            "homogenization_detected": self.homogenization_detected,
            "similarity_score": round(self.similarity_score, 3),
            "violations": self.violations,
            "details": self.details,
        }


# ═══════════════════════════════════════════════════════════════
# Similarity Computation
# ═══════════════════════════════════════════════════════════════

def _tokenize(text: str) -> set[str]:
    """Simple tokenization for Chinese + English text."""
    # Split on whitespace and common Chinese punctuation
    tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9_]+', text.lower())
    return set(tokens)


def _jaccard_similarity(a: set, b: set) -> float:
    """Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union) if union else 0.0


def _structural_similarity(a: str, b: str) -> float:
    """Check if two outputs share structural patterns (headings, lists, code blocks)."""
    def extract_patterns(text: str) -> set:
        patterns = set()
        # Markdown headings
        patterns.update(re.findall(r'^#{1,6}\s', text, re.MULTILINE))
        # List markers
        patterns.update(re.findall(r'^[-*+]\s', text, re.MULTILINE))
        # Code blocks
        if '```' in text:
            patterns.add('code_block')
        # JSON blocks
        if '{' in text and '}' in text:
            patterns.add('json_block')
        # Numbered lists
        if re.search(r'^\d+[.)]\s', text, re.MULTILINE):
            patterns.add('numbered_list')
        return patterns
    
    pa = extract_patterns(a)
    pb = extract_patterns(b)
    return _jaccard_similarity(pa, pb)


def _beginning_similarity(a: str, b: str) -> float:
    """Check if outputs start similarly (copy-paste indicator)."""
    a_start = a[:80].lower()
    b_start = b[:80].lower()
    return _jaccard_similarity(_tokenize(a_start), _tokenize(b_start))


def _extract_text(output) -> str:
    """Extract text from various output formats."""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        return output.get("result", str(output))
    return str(output)


# ═══════════════════════════════════════════════════════════════
# Consensus Pattern Detection
# ═══════════════════════════════════════════════════════════════

CONSENSUS_PATTERNS = [
    "同意", "正如所说", "similarly", "as mentioned", "consistent with",
    "正如", "同样", "also", "building on", "in line with",
]

HOMOGENIZATION_MARKERS = [
    "首先/其次/最后", "first/second/finally", "in conclusion",
    "第一/第二/第三", "总之", "in summary",
]


def detect_consensus_patterns(text: str) -> list[str]:
    """Detect consensus/homogenization patterns in text."""
    found = []
    text_lower = text.lower()
    for pattern in CONSENSUS_PATTERNS:
        if pattern.lower() in text_lower:
            found.append(pattern)
    return found


# ═══════════════════════════════════════════════════════════════
# Main Diversity Analysis
# ═══════════════════════════════════════════════════════════════

def compute_output_similarity(outputs: dict) -> dict:
    """
    Compute pairwise similarity across teammate outputs.
    
    Returns dict with:
    - max_similarity: highest pairwise similarity
    - avg_similarity: average pairwise similarity
    - pairs: list of (teammate_a, teammate_b, similarity) tuples
    """
    teammate_ids = list(outputs.keys())
    if len(teammate_ids) < 2:
        return {"max_similarity": 0.0, "avg_similarity": 0.0, "pairs": []}
    
    pairs = []
    for i in range(len(teammate_ids)):
        for j in range(i + 1, len(teammate_ids)):
            a_content = _extract_text(outputs[teammate_ids[i]])
            b_content = _extract_text(outputs[teammate_ids[j]])
            
            tokens_a = _tokenize(a_content)
            tokens_b = _tokenize(b_content)
            
            token_sim = _jaccard_similarity(tokens_a, tokens_b)
            struct_sim = _structural_similarity(a_content, b_content)
            begin_sim = _beginning_similarity(a_content, b_content)
            
            # Weighted combination
            similarity = 0.4 * token_sim + 0.3 * struct_sim + 0.3 * begin_sim
            
            # Length ratio adjustment: if outputs differ greatly in length, reduce weight
            len_a = len(a_content)
            len_b = len(b_content)
            if len_a > 0 and len_b > 0:
                length_ratio = min(len_a, len_b) / max(len_a, len_b)
                if length_ratio < 0.3:
                    similarity *= 0.7  # Reduce similarity for very different lengths
            
            pairs.append((teammate_ids[i], teammate_ids[j], round(similarity, 3)))
    
    if not pairs:
        return {"max_similarity": 0.0, "avg_similarity": 0.0, "pairs": []}
    
    similarities = [p[2] for p in pairs]
    return {
        "max_similarity": max(similarities),
        "avg_similarity": round(sum(similarities) / len(similarities), 3),
        "pairs": pairs,
    }


def analyze_diversity(teammate_outputs: dict, threshold: float = 0.75) -> DiversityReport:
    """
    Analyze teammate outputs for homogenization.
    
    Args:
        teammate_outputs: dict of {teammate_id: output_text}
        threshold: similarity above which homogenization is detected
    
    Returns:
        DiversityReport with homogenization status
    """
    if len(teammate_outputs) < 2:
        return DiversityReport(homogenization_detected=False, details="insufficient_outputs")
    
    # Compute pairwise similarity
    sim_result = compute_output_similarity(teammate_outputs)
    max_sim = sim_result["max_similarity"]
    
    # Check consensus patterns
    all_violations = []
    for teammate_id, output in teammate_outputs.items():
        text = _extract_text(output)
        violations = detect_consensus_patterns(text)
        if violations:
            all_violations.extend([f"{teammate_id}:{v}" for v in violations])
    
    # Determine homogenization
    homogenized = max_sim > threshold or len(all_violations) > 0
    
    details_parts = []
    if max_sim > threshold:
        details_parts.append(f"similarity={max_sim:.3f} > {threshold}")
    if all_violations:
        details_parts.append(f"consensus_violations={all_violations}")
    
    return DiversityReport(
        homogenization_detected=homogenized,
        similarity_score=max_sim,
        violations=all_violations,
        details="; ".join(details_parts) if details_parts else "diversity_ok",
    )
