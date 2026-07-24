"""brain/brain_loader.py — BrainLoader (Phase 12.2 + 7.0)

统一 AI 上下文入口。Data fetching delegated to BrainContextAssembler.
BrainLoader is a pure formatter: brain_context dict → prompt markdown.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.services.brain.fragment_store import (
    BrainFragmentStore,
    get_brain_fragment_store,
    BrainFragmentType,
)
from backend.services.brain.context import BrainContextAssembler
from backend.services.memory.memory_service import MemoryService, get_memory_service

logger = logging.getLogger("brain.loader")

# ── Fragment type → section header mapping ──
_FRAGMENT_HEADERS = {
    BrainFragmentType.IDENTITY: "## IDENTITY",
    BrainFragmentType.PERSONALITY: "## PERSONALITY",
    BrainFragmentType.PRINCIPLES: "## PRINCIPLES",
    BrainFragmentType.RESPONSIBILITIES: "## RESPONSIBILITIES",
    BrainFragmentType.SKILLS: "## SKILLS & ABILITIES",
    BrainFragmentType.LESSONS: "## LESSONS LEARNED",
    BrainFragmentType.DECISIONS: "## PAST DECISIONS",
    BrainFragmentType.PREFERENCES: "## PREFERENCES",
}
_RELEVANT_TYPES = list(_FRAGMENT_HEADERS.keys())

# ── Knowledge type value → section header ──
_KNOWLEDGE_HEADERS = {
    "PROJECT_KNOWLEDGE": "## PROJECT KNOWLEDGE",
    "MEMBER_KNOWLEDGE": "## MEMBER KNOWLEDGE",
    "TEAM_PATTERN": "## TEAM PATTERNS",
}


class BrainLoader:
    """Build unified AI context from assembled brain data.

    Pure formatter: receives assembled dict (via build_prompt), returns markdown.
    """

    def __init__(
        self,
        fragment_store: Optional[BrainFragmentStore] = None,
        memory_service: Optional[MemoryService] = None,
    ):
        self._store = fragment_store or get_brain_fragment_store()
        self._mem_svc = memory_service or get_memory_service()
        self._assembler = BrainContextAssembler(self._store, self._mem_svc)

    async def build_prompt(
        self,
        teammate_id: str,
        *,
        workspace_id: str = "",
        recent_memory_limit: int = 10,
        extra_context: str = "",
        query: Optional[str] = None,
        db: Optional["AsyncSession"] = None,
        experience: Optional[list[dict]] = None,
    ) -> str:
        """Build the full system prompt for a teammate.

        Delegates data fetching to BrainContextAssembler, then formats.
        """
        ctx = await self._assembler.assemble(
            teammate_id, workspace_id=workspace_id, query=query, db=db,
            recent_memory_limit=recent_memory_limit, experience=experience,
        )
        return self._format(ctx, extra_context=extra_context)

    def _format(self, ctx: dict, extra_context: str = "") -> str:
        """Pure formatter: assembled dict → prompt markdown."""
        fragments = ctx["fragments"]
        if not fragments and not ctx.get("workspace_id") and not ctx.get("identity") and not ctx["experience"] \
           and not ctx.get("teammate_profile") and not ctx.get("history_summary") \
           and not ctx.get("collaboration_pattern") and not ctx.get("knowledge_items"):
            return extra_context

        sections: list[str] = [
            "## YOUR BRAIN — This is your persistent self-knowledge.",
            "These are facts about yourself built from past experience.",
        ]

        # ── Fragment sections ──
        frag_map = {f.fragment_type: f.content for f in fragments}
        for ftype in _RELEVANT_TYPES:
            content = frag_map.get(ftype.value)
            if not content:
                continue
            sections.append(f"\n{_FRAGMENT_HEADERS[ftype]}\n{content}")

        # ── Teammate Identity ──
        ident = ctx.get("identity")
        if ident:
            id_lines: list[str] = ["\n## TEAMMATE IDENTITY"]
            id_lines.append(f"You are the {ident['role']} teammate.")
            if ident.get("capabilities"):
                id_lines.append(f"Your capabilities: {', '.join(ident['capabilities'])}")
            for b in ident.get("learned_behaviors", []):
                id_lines.append(f"  - {b[:200].replace(chr(10), ' ')}")
            perf = ident.get("recent_performance", {})
            if perf.get("total_actions", 0) > 0:
                id_lines.append(f"Recent performance: {perf['completed']}/{perf['total_actions']} actions completed, {perf.get('failed', 0)} failed.")
            trend = ident.get("performance_trend", {})
            cur = trend.get("current", {})
            td = trend.get("trend", {})
            if cur.get("success_rate", 0) > 0:
                direction = "improving" if td.get("completed", 0) > 0 and td.get("failed", 0) <= 0 else "declining" if td.get("failed", 0) > 0 else "stable"
                id_lines.append(f"Performance trend: success rate {cur['success_rate']:.0%}, {direction}")
            sections.append("\n".join(id_lines))

        # ── Organization Knowledge ──
        knowledge_items = ctx.get("knowledge_items", {})
        if knowledge_items:
            k_sections: list[str] = []
            for ktype_val, header in _KNOWLEDGE_HEADERS.items():
                items = knowledge_items.get(ktype_val)
                if not items:
                    continue
                lines: list[str] = [f"\n{header}"]
                for m in items:
                    lines.append(f"  - {(m.content or '')[:200].replace(chr(10), ' ')}")
                k_sections.append("\n".join(lines))
            if k_sections:
                sections.append("\n".join(k_sections))

        # ── Memory context ──
        mem_text = ctx.get("recent_memory_text", "")
        if mem_text:
            header = "## RELEVANT MEMORY" if ctx.get("recent_memory_is_semantic") else "## RECENT EXPERIENCE"
            sections.append(f"\n{header}\n{mem_text}")

        prompt = "\n".join(sections)
        if extra_context:
            prompt += f"\n\n{extra_context}"

        # ── Organization Experience ──
        experience = ctx["experience"]
        if experience:
            exp_lines: list[str] = ["\n\n## ORGANIZATION EXPERIENCE", "Previous similar tasks:"]
            for e in experience[:5]:
                goal = (e.get("goal") or "")[:200]
                tm_v = (e.get("teammate") or "")[:100]
                result = (e.get("result") or "")[:100]
                lesson = (e.get("lesson") or "")[:100]
                entry = f"- task: {goal}"
                if tm_v:
                    entry += f"\n  teammate: {tm_v}"
                if result:
                    entry += f"\n  approach: {result}"
                if lesson:
                    entry += f"\n  lesson: {lesson}"
                entry = entry[:500]
                exp_lines.append(entry)
            if len(exp_lines) > 1:
                prompt += "\n".join(exp_lines)

        # ── Phase 14: Teammate profile sections ──
        profile = ctx.get("teammate_profile", {})
        if profile:
            style_parts = []
            if profile.get("personality"):
                style_parts.append(f"\n\n## TEAMMATE WORKING STYLE\n{profile['personality']}")
            if profile.get("preferences"):
                style_parts.append(f"\n\n## TEAMMATE PREFERENCES\n{profile['preferences']}")
            if profile.get("expertise"):
                style_parts.append(f"\n## TEAMMATE EXPERTISE\n{', '.join(profile['expertise'])}")
            if style_parts:
                prompt += "".join(style_parts)

        # ── Phase 14: History summary ──
        hist = ctx.get("history_summary", "")
        if hist:
            prompt += f"\n\n## TEAMMATE HISTORY\nRecent actions in this workspace:\n{hist}"

        # ── Phase 14: Collaboration pattern ──
        collab = ctx.get("collaboration_pattern", "")
        if collab:
            prompt += f"\n\n## COLLABORATION PATTERN\n{collab}"

        # ── Team / Project context ──
        for items, header in [
            (ctx.get("team_items", []), "\n\n## TEAM STATE"),
            (ctx.get("proj_items", []), "\n\n## PROJECT CONTEXT"),
        ]:
            if items:
                prompt += header
                for m in items:
                    prompt += f"\n  - {(m.content or '')[:200].replace(chr(10), ' ')}"

        return prompt

    async def semantic_recall(
        self,
        query: str,
        *,
        teammate_id: str,
        scope: Optional[str] = None,
        top_k: int = 10,
        min_score: float = 0.1,
    ) -> str:
        """Delegate to assembler for backward compat."""
        return await self._assembler.semantic_recall(
            query, teammate_id=teammate_id, scope=scope, top_k=top_k, min_score=min_score,
        )

    async def build_identity_block(self, teammate_id: str) -> str:
        """Shortcut: return only the IDENTITY + PERSONALITY section as one string."""
        fragments = await self._store.get_all_by_teammate(teammate_id)
        parts = []
        for f in fragments:
            if f.fragment_type == BrainFragmentType.IDENTITY:
                parts.append(f"Identity: {f.content}")
            elif f.fragment_type == BrainFragmentType.PERSONALITY:
                parts.append(f"Personality: {f.content}")
            elif f.fragment_type == BrainFragmentType.PRINCIPLES:
                parts.append(f"Principles: {f.content}")
        return "\n".join(parts)


# Singleton
_loader: Optional[BrainLoader] = None


def get_brain_loader() -> BrainLoader:
    global _loader
    if _loader is None:
        _loader = BrainLoader()
    return _loader
