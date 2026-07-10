"""
memory_insight.py — V2.7 Phase C: MemoryInsight types + Engine

Pure rule-based analysis engine that converts task execution history
into structured Insights (no LLM calls).

Insight types:
  SUCCESS_PATTERN  — Stable success signatures (high quality, no retry)
  FAILURE_PATTERN  — Recurring failure patterns (retries, known failure categories)
  OPTIMIZATION     — Cost/duration/retry optimization signals
  RISK_WARNING     — Policy blocks, approval rejections

MemoeryInsight dataclass — pure Python, no ORM dependency.
MemoryInsightEngine — stateless rule engine.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# Insight Types
# ═══════════════════════════════════════════════════════════════


class InsightType(str, Enum):
    """Semantic category of an insight."""

    SUCCESS_PATTERN = "SUCCESS_PATTERN"
    FAILURE_PATTERN = "FAILURE_PATTERN"
    OPTIMIZATION = "OPTIMIZATION"
    RISK_WARNING = "RISK_WARNING"

    @classmethod
    def priority(cls, t: str) -> int:
        """Lower = higher priority for retention/display."""
        order = [
            cls.RISK_WARNING,
            cls.FAILURE_PATTERN,
            cls.OPTIMIZATION,
            cls.SUCCESS_PATTERN,
        ]
        try:
            return order.index(cls(t))
        except (ValueError, KeyError):
            return 99


# ═══════════════════════════════════════════════════════════════
# Insight Data Model
# ═══════════════════════════════════════════════════════════════


@dataclass
class MemoryInsight:
    """
    A single insight extracted from execution history.

    Pure dataclass — no ORM, no framework dependency.
    Persisted by MemoryInsightStore via raw SQL.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = InsightType.SUCCESS_PATTERN
    title: str = ""
    content: str = ""
    source_task_id: str = ""
    source_execution_id: str = ""
    confidence: float = 0.0       # 0.0 – 1.0
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "content": self.content,
            "source_task_id": self.source_task_id,
            "source_execution_id": self.source_execution_id,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> MemoryInsight:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            type=data.get("type", InsightType.SUCCESS_PATTERN),
            title=data.get("title", ""),
            content=data.get("content", ""),
            source_task_id=data.get("source_task_id", ""),
            source_execution_id=data.get("source_execution_id", ""),
            confidence=float(data.get("confidence", 0.0)),
            created_at=_parse_dt(data.get("created_at")),
            metadata=data.get("metadata", {}),
        )

    def __len__(self) -> int:
        """Rough char-length (token estimate ~ len/4)."""
        return len(self.content) + len(self.title) + len(str(self.metadata))


def _parse_dt(val: Optional[str]) -> datetime:
    if not val:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════
# Threshold constants
# ═══════════════════════════════════════════════════════════════

HIGH_QUALITY_THRESHOLD = 0.8       # overall_quality >= → success pattern
HIGH_COST_THRESHOLD_MICRO = 500    # estimated_cost (µ$) >= → cost warning
HIGH_DURATION_THRESHOLD_MS = 30_000  # 30s
HIGH_RETRY_THRESHOLD = 2


# ═══════════════════════════════════════════════════════════════
# Analysis input shape (loose dict adapter)
# ═══════════════════════════════════════════════════════════════


class TaskResultSnapshot:
    """
    Lightweight adapter for ExecutionResult + TaskExecution data.

    Accepts dicts (from SQL joins) so the engine doesn't depend on
    SQLAlchemy models. Fields match the raw query shape from
    TaskStateManager.list_results_by_task().
    """

    def __init__(self, data: dict):
        self._d = data

    @property
    def task_step_id(self) -> str:
        return self._d.get("task_step_id", "")

    @property
    def task_execution_id(self) -> str:
        return self._d.get("task_execution_id", "")

    @property
    def outcome(self) -> str:
        return self._d.get("outcome", "")

    @property
    def overall_quality(self) -> float:
        return float(self._d.get("overall_quality", 0.0))

    @property
    def failure_category(self) -> str:
        return self._d.get("failure_category", "")

    @property
    def total_tokens(self) -> int:
        return int(self._d.get("total_tokens", 0))

    @property
    def estimated_cost(self) -> int:
        return int(self._d.get("estimated_cost", 0))

    @property
    def step_order(self) -> int:
        return int(self._d.get("step_order", 0))

    @property
    def step_objective(self) -> str:
        return self._d.get("step_objective", "")

    @property
    def is_recoverable(self) -> bool:
        return self._d.get("is_recoverable", "1") == "1"


# ═══════════════════════════════════════════════════════════════
# MemoryInsightEngine
# ═══════════════════════════════════════════════════════════════


class MemoryInsightEngine:
    """
    Pure rule-based insight engine.

    Each `_analyze_*` method inspects a single TaskResultSnapshot and
    returns a list of MemoryInsight objects (empty = no insight).

    Rules are deterministic and explainable — no LLM involved.
    """

    # ── Public API ──

    async def analyze_task_result(
        self,
        result: TaskResultSnapshot,
    ) -> list[MemoryInsight]:
        """
        Analyze a single execution result and return applicable insights.

        Args:
            result: Wrapped execution result + execution data.

        Returns:
            List of MemoryInsight objects (may be empty).
        """
        insights: list[MemoryInsight] = []

        # Run all rule checks (order matters for grouping)
        success_insights = self._check_success(result)
        failure_insights = self._check_failure(result)
        optimization_insights = self._check_optimization(result)

        insights.extend(success_insights)
        insights.extend(failure_insights)
        insights.extend(optimization_insights)

        return insights

    async def generate_insights(
        self,
        results: list[TaskResultSnapshot],
    ) -> list[MemoryInsight]:
        """
        Analyze multiple execution results and return aggregated insights.

        Args:
            results: List of wrapped execution result snapshots.

        Returns:
            Aggregated list of MemoryInsight objects.
        """
        all_insights: list[MemoryInsight] = []
        for r in results:
            batch = await self.analyze_task_result(r)
            all_insights.extend(batch)
        return all_insights

    # ── Rule: SUCCESS_PATTERN ──

    def _check_success(self, r: TaskResultSnapshot) -> list[MemoryInsight]:
        """Detect stable success patterns.

        Rule: outcome=SUCCESS, overall_quality >= 0.8, no failure_category.
        """
        if r.outcome != "SUCCESS":
            return []
        if r.overall_quality < HIGH_QUALITY_THRESHOLD:
            return []
        if r.failure_category:
            return []  # even if outcome=SUCCESS, a failure_category suggests issues

        objective_hint = r.step_objective[:60] if r.step_objective else f"step {r.step_order}"
        return [
            MemoryInsight(
                type=InsightType.SUCCESS_PATTERN,
                title="稳定成功模式",
                content=(
                    f"Teammate 在 \"{objective_hint}\" 任务上表现稳定 "
                    f"(quality={r.overall_quality:.2f})"
                ),
                source_task_id="",
                source_execution_id=r.task_execution_id,
                confidence=min(r.overall_quality, 0.95),
                metadata={
                    "step_order": r.step_order,
                    "overall_quality": r.overall_quality,
                },
            )
        ]

    # ── Rule: FAILURE_PATTERN ──

    def _check_failure(self, r: TaskResultSnapshot) -> list[MemoryInsight]:
        """Detect failure patterns.

        Rule: outcome=FAILURE, failure_category is set, or is_recoverable=false.
        """
        if r.outcome != "FAILURE":
            return []

        objective_hint = r.step_objective[:60] if r.step_objective else f"step {r.step_order}"
        category_info = f" 类别: {r.failure_category}" if r.failure_category else ""

        return [
            MemoryInsight(
                type=InsightType.FAILURE_PATTERN,
                title="执行失败警告",
                content=(
                    f"\"{objective_hint}\" 执行失败{category_info}"
                ),
                source_task_id="",
                source_execution_id=r.task_execution_id,
                confidence=0.7,
                metadata={
                    "step_order": r.step_order,
                    "failure_category": r.failure_category,
                    "is_recoverable": r.is_recoverable,
                },
            )
        ]

    # ── Rule: OPTIMIZATION ──

    def _check_optimization(self, r: TaskResultSnapshot) -> list[MemoryInsight]:
        """Detect optimization opportunities.

        Rule: cost above threshold OR duration above threshold.
        """
        reasons: list[str] = []

        if r.estimated_cost >= HIGH_COST_THRESHOLD_MICRO:
            cost_usd = r.estimated_cost / 1_000_000
            reasons.append(f"成本 ${cost_usd:.4f}")

        if r.total_tokens >= 10_000:
            reasons.append(f"tokens={r.total_tokens}")

        if not reasons:
            return []

        objective_hint = r.step_objective[:60] if r.step_objective else f"step {r.step_order}"
        content = f"\"{objective_hint}\" 可优化: {'; '.join(reasons)}"

        return [
            MemoryInsight(
                type=InsightType.OPTIMIZATION,
                title="优化建议",
                content=content,
                source_task_id="",
                source_execution_id=r.task_execution_id,
                confidence=0.6,
                metadata={
                    "step_order": r.step_order,
                    "estimated_cost": r.estimated_cost,
                    "total_tokens": r.total_tokens,
                },
            )
        ]

    # ── External: Risk insight factory (called from hooks, not from result analysis) ──

    @staticmethod
    def make_risk_insight(
        *,
        task_id: str,
        title: str = "风险警告",
        content: str = "",
        confidence: float = 0.8,
        extra_meta: Optional[dict] = None,
    ) -> MemoryInsight:
        """Create a RISK_WARNING insight (used when policy blocks / approval rejects)."""
        meta = extra_meta or {}
        return MemoryInsight(
            type=InsightType.RISK_WARNING,
            title=title,
            content=content,
            source_task_id=task_id,
            confidence=confidence,
            metadata=meta,
        )
