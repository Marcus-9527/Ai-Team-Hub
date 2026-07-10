"""
base.py — ExecutionEvaluator interface

Defines the abstract evaluator interface and the EvaluationResult dataclass
used across all evaluation strategies (rule-based, LLM, hybrid).

Phase B: Only RuleBasedEvaluator is implemented.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EvaluationResult:
    """Structured output of an execution evaluation.

    All scores are 0.0–1.0 unless otherwise noted.
    """
    completeness: float = 0.0
    coherence: float = 0.0
    accuracy: Optional[float] = None       # reserved for future LLM judge
    overall_quality: float = 0.0
    confidence: float = 1.0                # rule-based is deterministic → 1.0
    evaluator: str = "rule"                # strategy identifier
    details: dict = field(default_factory=dict)   # scoring breakdown for transparency


class ExecutionEvaluator(ABC):
    """Abstract interface for evaluating step execution results.

    Implementations must produce scores for completeness, coherence,
    and overall_quality. Accuracy is reserved and may be None.
    """

    @abstractmethod
    async def evaluate(
        self,
        *,
        actual_output: str,
        expected_output: str = "",
        objective: str = "",
    ) -> EvaluationResult:
        """Evaluate an execution output and return quality scores.

        Args:
            actual_output: The raw output produced by the step execution.
            expected_output: The expected output from the task plan (optional).
            objective: The step's objective/instruction (optional).

        Returns:
            EvaluationResult with quality scores and metadata.
        """
        ...
