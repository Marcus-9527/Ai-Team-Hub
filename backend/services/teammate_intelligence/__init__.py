"""
Phase 7: Teammate Intelligence System.
Phase 14: Teammate Evolution Memory.

Components:
- SkillRegistry:  task_type → [required_skills] mapping
- TeammateProfile: enriched teammate view with stats + memory
- ExperienceStore: per-teammate stats + memory query/update from DB
- TeammateSelector: recommend best teammate for a task
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.models import Teammate, EvaluationRecordModel, ExecutionRecordModel, ExecutionEventModel

logger = logging.getLogger("teammate_intelligence")


# ── Built-in task type → skill mappings ──

_DEFAULT_SKILL_MAP: dict[str, list[str]] = {
    "coding":       ["python", "javascript", "typescript", "go", "rust", "coding", "debugging"],
    "writing":      ["writing", "editing", "copywriting", "content"],
    "analysis":     ["data_analysis", "statistics", "research", "analytics"],
    "design":       ["ui_design", "ux", "frontend", "visual_design"],
    "architecture": ["system_design", "architecture", "scalability"],
    "code_review":  ["code_review", "quality", "testing"],
    "devops":       ["devops", "ci_cd", "infrastructure", "deployment"],
    "general":      [],
}


class SkillRegistry:
    """Mapping from task type descriptors to required skills.

    Usage:
        SkillRegistry.get_skills("coding")     → ["python", "javascript", ...]
        SkillRegistry.register("ml", ["pytorch", "tensorflow", "mlops"])
    """

    _map: dict[str, list[str]] = dict(_DEFAULT_SKILL_MAP)

    @classmethod
    def get_skills(cls, task_type: str) -> list[str]:
        return cls._map.get(task_type, cls._map.get("general", []))

    @classmethod
    def register(cls, task_type: str, skills: list[str]) -> None:
        cls._map[task_type] = skills

    @classmethod
    def list_types(cls) -> list[str]:
        return list(cls._map.keys())

    @classmethod
    def reset(cls) -> None:
        cls._map = dict(_DEFAULT_SKILL_MAP)


@dataclass
class TeammateProfile:
    """Enriched teammate info including intelligence stats + evolution memory."""
    id: str
    name: str
    role: str
    avatar_emoji: str
    skills: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    success_rate: float = 0.0
    average_score: float = 0.0
    execution_count: int = 0
    # Phase 14: evolution memory
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    learned_patterns: list[str] = field(default_factory=list)
    failed_patterns: list[str] = field(default_factory=list)
    preferred_tools: list[str] = field(default_factory=list)

    @classmethod
    def from_orm(cls, t: Teammate) -> "TeammateProfile":
        return cls(
            id=t.id,
            name=t.name,
            role=t.role,
            avatar_emoji=t.avatar_emoji,
            skills=t.skills or [],
            capabilities=t.capabilities or [],
            success_rate=t.success_rate or 0.0,
            average_score=t.average_score or 0.0,
            execution_count=t.execution_count or 0,
            strengths=t.strengths or [],
            weaknesses=t.weaknesses or [],
            learned_patterns=t.learned_patterns or [],
            failed_patterns=t.failed_patterns or [],
            preferred_tools=t.preferred_tools or [],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "avatar_emoji": self.avatar_emoji,
            "skills": self.skills,
            "capabilities": self.capabilities,
            "success_rate": self.success_rate,
            "average_score": self.average_score,
            "execution_count": self.execution_count,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "learned_patterns": self.learned_patterns,
            "failed_patterns": self.failed_patterns,
            "preferred_tools": self.preferred_tools,
        }


class ExperienceStore:
    """Read/write teammate experience stats + evolution memory from evaluation data."""

    @staticmethod
    async def update_from_evaluation(
        execution_id: str,
        db: Optional[AsyncSession] = None,
    ) -> None:
        """Recalculate teammate stats from all evaluations for the same teammate.

        Called after an evaluation is created/updated.
        Also triggers evolution memory derivation (Phase 14).
        """
        async def _do(session: AsyncSession) -> None:
            exec_q = select(ExecutionRecordModel).where(
                ExecutionRecordModel.execution_id == execution_id
            )
            exec_result = await session.execute(exec_q)
            exec_rec = exec_result.scalar_one_or_none()
            if not exec_rec or not exec_rec.teammate:
                return

            teammate_name = exec_rec.teammate

            tm_q = select(Teammate).where(Teammate.name == teammate_name)
            tm_result = await session.execute(tm_q)
            teammate = tm_result.scalar_one_or_none()
            if not teammate:
                return

            # Get all execution IDs for this teammate
            exec_ids_q = select(ExecutionRecordModel.execution_id).where(
                ExecutionRecordModel.teammate == teammate_name
            )
            exec_ids_result = await session.execute(exec_ids_q)
            exec_ids = [row[0] for row in exec_ids_result]
            if not exec_ids:
                return

            # Get all EVALUATED records for those executions
            eval_q = select(EvaluationRecordModel).where(
                EvaluationRecordModel.execution_id.in_(exec_ids),
                EvaluationRecordModel.status == "EVALUATED",
            )
            eval_result = await session.execute(eval_q)
            evals = list(eval_result.scalars().all())
            if not evals:
                return

            total = len(evals)
            # ponytail: success = score >= 0.5 threshold
            successes = sum(1 for e in evals if e.score >= 0.5)
            avg_score = sum(e.score for e in evals) / total

            teammate.execution_count = total
            teammate.success_rate = round(successes / total, 4)
            teammate.average_score = round(avg_score, 4)
            await session.commit()

            logger.info(
                "[EXP] teammate=%s execs=%d success_rate=%.3f avg_score=%.3f",
                teammate_name, total, teammate.success_rate, teammate.average_score,
            )

            # Phase 14: derive evolution memory from evaluation history
            try:
                await ExperienceStore._update_memory(teammate_name, session, exec_ids)
            except Exception:
                logger.debug("[EVO] memory update skipped (non-fatal)")

        if db is not None:
            await _do(db)
        else:
            async with async_session() as s:
                await _do(s)

    @staticmethod
    async def _update_memory(
        teammate_name: str,
        session: AsyncSession,
        exec_ids: list[str],
    ) -> None:
        """Derive strengths, weaknesses, learned/failed patterns, and preferred tools
        from evaluation history. Overwrites memory fields with a fresh analysis
        on every call (cheaper than incremental merging).
        """
        eval_q = select(EvaluationRecordModel).where(
            EvaluationRecordModel.execution_id.in_(exec_ids),
            EvaluationRecordModel.status == "EVALUATED",
        )
        eval_result = await session.execute(eval_q)
        evals = list(eval_result.scalars().all())
        if not evals:
            return

        exec_q = select(ExecutionRecordModel).where(
            ExecutionRecordModel.execution_id.in_(exec_ids)
        )
        exec_result = await session.execute(exec_q)
        execs = {e.execution_id: e for e in exec_result.scalars().all()}

        strengths: set[str] = set()
        weaknesses: set[str] = set()
        learned: set[str] = set()
        failed: set[str] = set()
        tools: set[str] = set()

        for ev in evals:
            er = execs.get(ev.execution_id)
            tag = er.dag_node_id or "general" if er else "general"
            if ev.score >= 0.7:
                strengths.add(f"Excels at {tag}")
                learned.add(f"Completed {tag} successfully")
            elif ev.score < 0.4:
                weaknesses.add(f"Struggles with {tag}")
            if er and er.error:
                failed.add(f"Failed on {tag}")

        # ponytail: scan last 10 execs for tool usage
        last_ids = exec_ids[-10:]
        if last_ids:
            evt_q = select(ExecutionEventModel).where(
                ExecutionEventModel.execution_id.in_(last_ids)
            )
            evt_result = await session.execute(evt_q)
            for evt in evt_result.scalars().all():
                payload = evt.payload or {}
                tool = payload.get("tool", "")
                if tool:
                    tools.add(tool)

        # write back
        tm_q = select(Teammate).where(Teammate.name == teammate_name)
        tm_result = await session.execute(tm_q)
        teammate = tm_result.scalar_one_or_none()
        if not teammate:
            return

        teammate.strengths = list(strengths)
        teammate.weaknesses = list(weaknesses)
        teammate.learned_patterns = list(learned)
        teammate.failed_patterns = list(failed)
        teammate.preferred_tools = list(tools)
        await session.commit()

        logger.info(
            "[EVO] teammate=%s strengths=%d weaknesses=%d learned=%d failed=%d tools=%d",
            teammate_name, len(strengths), len(weaknesses),
            len(learned), len(failed), len(tools),
        )

    @staticmethod
    async def get_profile(
        teammate_id: str,
        db: Optional[AsyncSession] = None,
    ) -> Optional[TeammateProfile]:
        async def _do(session: AsyncSession) -> Optional[TeammateProfile]:
            q = select(Teammate).where(Teammate.id == teammate_id)
            result = await session.execute(q)
            t = result.scalar_one_or_none()
            return TeammateProfile.from_orm(t) if t else None

        if db is not None:
            return await _do(db)
        async with async_session() as s:
            return await _do(s)


class TeammateSelector:
    """Recommend teammates for a given task type or required skills list."""

    # Phase 14 scoring weights: skill_match 40%, experience 30%, semantic_memory 20%, availability 10%
    W_SKILL = 0.40
    W_EXPERIENCE = 0.30
    W_MEMORY = 0.20
    W_AVAILABILITY = 0.10

    @staticmethod
    async def recommend(
        task_type: str,
        top_n: int = 1,
        db: Optional[AsyncSession] = None,
    ) -> list[TeammateProfile]:
        """Score all teammates by skill_match + experience + semantic_memory + availability, return top N."""
        required_skills = SkillRegistry.get_skills(task_type)
        return await TeammateSelector.recommend_by_skills(
            required_skills, top_n=top_n, db=db,
        )

    @staticmethod
    async def recommend_by_skills(
        required_skills: list[str],
        top_n: int = 1,
        db: Optional[AsyncSession] = None,
        exclude_teammate_names: Optional[set[str]] = None,
        techlead_override: Optional[tuple[str, float]] = None,
    ) -> list[TeammateProfile]:
        """Score teammates by skill_match(0.4) + experience(0.3) + semantic_memory(0.2) + availability(0.1).

        Phase 24: availability score uses real TeammateRuntimeState.
        OFFLINE → excluded (score 0). WORKING → 0.2. ACTIVE/IDLE → 1.0.

        Phase 26: techlead_override = (teammate_id, confidence) from TechLead decision.
        Boosts the recommended teammate's score by confidence * (1 - final) * 0.5
        so high-confidence recommendations meaningfully influence selection.
        Invalid recommendations (teammate not in pool) are silently ignored.
        """
        async def _do(session: AsyncSession) -> list[TeammateProfile]:
            q = select(Teammate)
            # DB-level filter: only teammates whose skills overlap required_skills
            if required_skills:
                from sqlalchemy import or_
                # ponytail: LIKE on JSON text works for SQLite; use JSONB operators for PostgreSQL
                q = q.where(or_(*[
                    Teammate.skills.like(f'%"{s}"%')
                    for s in required_skills
                ]))
            if exclude_teammate_names:
                q = q.where(Teammate.name.notin_(exclude_teammate_names))
            q = q.order_by(Teammate.created_at)
            result = await session.execute(q)
            teammates = list(result.scalars().all())

            # ponytail: specific-skill filter excluded everyone → retry without
            # filter so planning can always produce steps.  Same pattern as
            # routes/tasks.py fallback, but in the shared function so every
            # caller (orchestrator, routes, dag_executor) benefits without
            # copy-pasting guards everywhere.
            _match_skills = required_skills
            if not teammates and required_skills:
                q2 = select(Teammate)
                if exclude_teammate_names:
                    q2 = q2.where(Teammate.name.notin_(exclude_teammate_names))
                q2 = q2.order_by(Teammate.created_at)
                r2 = await session.execute(q2)
                teammates = list(r2.scalars().all())
                if teammates:
                    _match_skills = []  # _compute_match returns 0.5 grace

            if not teammates:
                return []

            # Phase 24: load runtime state map once
            try:
                from backend.services.autonomous.teammate_state import get_state_manager
                all_states = await get_state_manager().list_all()
                state_map = {s["teammate_id"]: s["state"] for s in all_states}
            except Exception:
                state_map = {}

            scored: list[tuple[float, TeammateProfile]] = []
            for t in teammates:
                state = state_map.get(t.id, "active")
                # ponytail: OFFLINE = hard block, not just low score
                if state == "offline":
                    continue
                profile = TeammateProfile.from_orm(t)
                skill_score = TeammateSelector._compute_match(
                    profile.skills, _match_skills
                )
                exp_score = profile.average_score
                mem_score = TeammateSelector._memory_score(profile)
                avail_score = 1.0 if state in ("active", "idle") else 0.2
                final = (
                    skill_score * TeammateSelector.W_SKILL
                    + exp_score * TeammateSelector.W_EXPERIENCE
                    + mem_score * TeammateSelector.W_MEMORY
                    + avail_score * TeammateSelector.W_AVAILABILITY
                )
                # Phase 26: TechLead override — boost recommended teammate's score
                if techlead_override and t.id == techlead_override[0]:
                    bonus = techlead_override[1] * (1 - final) * 0.5
                    final += bonus
                scored.append((final, profile))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [p for _, p in scored[:top_n]]

        if db is not None:
            return await _do(db)
        async with async_session() as s:
            return await _do(s)

    @staticmethod
    def _compute_match(teammate_skills: list[str], required: list[str]) -> float:
        """Fraction of required skills the teammate has."""
        if not required:
            return 0.5
        ts = set(s.lower() for s in teammate_skills)
        req = set(s.lower() for s in required)
        if not req:
            return 0.5
        return len(ts & req) / len(req)

    @staticmethod
    def _memory_score(profile: TeammateProfile) -> float:
        """Semantic memory score: ratio of learned vs total patterns.

        Neutral (0.5) when no memory yet. Reflects how well the teammate's
        experience aligns with success vs failure.
        """
        total = len(profile.learned_patterns) + len(profile.failed_patterns)
        if total == 0:
            return 0.5
        return len(profile.learned_patterns) / total


__all__ = [
    "SkillRegistry",
    "TeammateProfile",
    "ExperienceStore",
    "TeammateSelector",
]
