"""
services/evaluation — Execution-Level Evaluation System (Phase 6)

Components:
  Metrics        — threshold/weight constants for rule-based scoring
  ScoringEngine  — computes scores from an ExecutionRecord
  EvaluationService — orchestrates CRUD + scoring for EvaluationRecordModel

Scoring model (all 0–1, 1 = best):
  latency_score  — inverse of duration_ms (log scale)
  cost_score     — inverse of cost_micro_usd (log scale)
  artifact_score — binary: 1 if any artifact exists, else 0
  error_score     — 1.0 if no error, 0.0 if error present
  overall score   — latency*W1 + cost*W2 + artifact*W3 + error*W4
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.models import EvaluationRecordModel, gen_uuid

logger = logging.getLogger("evaluation")


# ── Scoring Constants ──


class Metrics:
    """Thresholds and weights for rule-based scoring."""

    # Latency: duration_ms thresholds
    LATENCY_IDEAL_MS = 5_000       # ≤5s → 1.0
    LATENCY_ACCEPTABLE_MS = 60_000  # ≥60s → 0.0

    # Cost: cost_micro_usd thresholds
    COST_IDEAL = 500                # ≤500µ$ → 1.0
    COST_ACCEPTABLE = 100_000       # ≥100000µ$ → 0.0

    # Weights for overall score
    W_LATENCY = 0.30
    W_COST = 0.25
    W_ARTIFACT = 0.20
    W_ERROR = 0.25


_default_metrics = Metrics()


# ── Scoring Engine ──


class ScoringEngine:
    """Rule-based scoring engine for execution evaluations.

    Pure computation — no I/O.  Takes an ExecutionRecord-compatible
    dict and returns dimension scores.
    """

    def __init__(self, metrics: Metrics | None = None):
        self.m = metrics or _default_metrics

    def score(self, record: dict) -> dict:
        """Compute dimension scores from a dict (ExecutionRecord.to_dict())."""
        lat = self._latency(record.get("duration_ms", 0))
        cost = self._cost(record.get("cost_micro_usd", 0))
        art = self._artifact(record)
        err = self._error(record.get("error", ""))

        overall = (
            lat * self.m.W_LATENCY
            + cost * self.m.W_COST
            + art * self.m.W_ARTIFACT
            + err * self.m.W_ERROR
        )
        overall = round(max(0.0, min(1.0, overall)), 4)

        return {
            "score": overall,
            "latency_score": lat,
            "cost_score": cost,
            "artifact_score": art,
            "error_score": err,
        }

    # ── Dimension scorers ──

    def _latency(self, duration_ms: int) -> float:
        if duration_ms <= self.m.LATENCY_IDEAL_MS:
            return 1.0
        if duration_ms >= self.m.LATENCY_ACCEPTABLE_MS:
            return 0.0
        # Linear decay in between
        ratio = (self.m.LATENCY_ACCEPTABLE_MS - duration_ms) / (
            self.m.LATENCY_ACCEPTABLE_MS - self.m.LATENCY_IDEAL_MS
        )
        return round(ratio, 4)

    def _cost(self, cost_micro_usd: int) -> float:
        # Log scale: input clamped to [COST_IDEAL, COST_ACCEPTABLE]
        c = max(self.m.COST_IDEAL, min(self.m.COST_ACCEPTABLE, cost_micro_usd))
        if c <= self.m.COST_IDEAL:
            return 1.0
        if c >= self.m.COST_ACCEPTABLE:
            return 0.0
        log_ratio = (math.log(c) - math.log(self.m.COST_IDEAL)) / (
            math.log(self.m.COST_ACCEPTABLE) - math.log(self.m.COST_IDEAL)
        )
        return round(1.0 - log_ratio, 4)

    @staticmethod
    def _artifact(record: dict) -> float:
        # Ponytail: binary check.  Upgrade to type-weighted when artifact
        # meta is richer.
        events = record.get("events", [])
        for evt in events:
            d = evt.get("data", {})
            if d.get("tool") == "artifact" or "artifact" in evt.get("type", ""):
                return 1.0
        return 0.0

    @staticmethod
    def _error(error: str) -> float:
        return 1.0 if not error else 0.0


# ── Evaluation Service ──


class EvaluationService:
    """Orchestrates creation, scoring, and retrieval of evaluation records."""

    def __init__(self, engine: ScoringEngine | None = None):
        self._engine = engine or ScoringEngine()

    # ── Evaluate an execution ──

    async def evaluate(
        self,
        execution_id: str,
        record: dict,
        db: AsyncSession | None = None,
    ) -> EvaluationRecordModel:
        """Score an execution and persist the evaluation record.

        Upsert semantics: if an evaluation already exists for this
        execution_id, update it with fresh scores.

        Accepts an optional `db` session for testing; otherwise uses
        the production async_session.
        """
        scores = self._engine.score(record)
        feedback = self._build_feedback(record, scores)

        async def _do(session: AsyncSession) -> EvaluationRecordModel:
            existing = await session.execute(
                select(EvaluationRecordModel).where(
                    EvaluationRecordModel.execution_id == execution_id
                )
            )
            ev: EvaluationRecordModel | None = existing.scalar_one_or_none()

            if ev is None:
                ev = EvaluationRecordModel(
                    id=gen_uuid(),
                    execution_id=execution_id,
                    status="EVALUATED",
                    **scores,
                    feedback=feedback,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(ev)
            else:
                for k, v in scores.items():
                    setattr(ev, k, v)
                ev.status = "EVALUATED"
                ev.feedback = feedback

            await session.commit()
            await session.refresh(ev)
            logger.info(
                "[EVAL] %s → score=%.3f lat=%.3f cost=%.3f art=%.3f err=%.3f",
                execution_id,
                ev.score, ev.latency_score, ev.cost_score,
                ev.artifact_score, ev.error_score,
            )

            # Phase 7: Fire-and-forget teammate intelligence update
            try:
                from backend.services.teammate_intelligence import ExperienceStore
                asyncio.ensure_future(ExperienceStore.update_from_evaluation(execution_id))
            except Exception:
                logger.debug("[INTEL] teammate stat update skipped (non-fatal)")

            return ev

        if db is not None:
            return await _do(db)
        async with async_session() as s:
            return await _do(s)

    # ── Get evaluation by execution_id ──

    async def get(self, execution_id: str, db: AsyncSession | None = None) -> Optional[EvaluationRecordModel]:
        async def _do(session: AsyncSession):
            result = await session.execute(
                select(EvaluationRecordModel).where(
                    EvaluationRecordModel.execution_id == execution_id
                )
            )
            return result.scalar_one_or_none()
        if db is not None:
            return await _do(db)
        async with async_session() as s:
            return await _do(s)

    # ── List recent evaluations ──

    async def list_evaluations(
        self,
        db: AsyncSession | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        async def _do(session: AsyncSession) -> list[dict]:
            result = await session.execute(
                select(EvaluationRecordModel)
                .order_by(desc(EvaluationRecordModel.created_at))
                .offset(offset).limit(limit)
            )
            rows = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "execution_id": r.execution_id,
                    "score": r.score,
                    "latency_score": r.latency_score,
                    "cost_score": r.cost_score,
                    "artifact_score": r.artifact_score,
                    "error_score": r.error_score,
                    "status": r.status,
                    "created_at": str(r.created_at),
                }
                for r in rows
            ]
        if db is not None:
            return await _do(db)
        async with async_session() as s:
            return await _do(s)

    # ── Stats ──

    async def stats(self, db: AsyncSession | None = None) -> dict:
        """Aggregate evaluation statistics."""
        async def _do(session: AsyncSession) -> dict:
            total_q = select(func.count(EvaluationRecordModel.id))
            total_scalar = await session.execute(total_q)
            total = total_scalar.scalar() or 0

            avg_q = select(func.avg(EvaluationRecordModel.score))
            avg_scalar = await session.execute(avg_q)
            avg_score = round(float(avg_scalar.scalar() or 0.0), 4)

            evaluated_q = select(func.count(EvaluationRecordModel.id)).where(
                EvaluationRecordModel.status == "EVALUATED"
            )
            evaluated_scalar = await session.execute(evaluated_q)
            evaluated = evaluated_scalar.scalar() or 0

            pending_q = select(func.count(EvaluationRecordModel.id)).where(
                EvaluationRecordModel.status == "PENDING"
            )
            pending_scalar = await session.execute(pending_q)
            pending = pending_scalar.scalar() or 0

            best_q = (
                select(func.max(EvaluationRecordModel.score))
                .where(EvaluationRecordModel.status == "EVALUATED")
            )
            best_scalar = await session.execute(best_q)
            best = round(float(best_scalar.scalar() or 0.0), 4)

            return {
                "total_evaluations": total,
                "evaluated": evaluated,
                "pending": pending,
                "average_score": avg_score,
                "best_score": best,
            }
        if db is not None:
            return await _do(db)
        async with async_session() as s:
            return await _do(s)

    # ── Feedback builder ──

    @staticmethod
    def _build_feedback(record: dict, scores: dict) -> str:
        parts = []
        if record.get("error"):
            parts.append(f"Execution error: {record['error'][:200]}")
        if scores["latency_score"] < 0.3:
            parts.append(
                f"High latency (duration={record.get('duration_ms', 0)}ms)"
            )
        if scores["cost_score"] < 0.3:
            parts.append(
                f"High cost (cost_micro_usd={record.get('cost_micro_usd', 0)})"
            )
        if not parts:
            parts.append("Execution completed within acceptable parameters.")
        return "; ".join(parts)
