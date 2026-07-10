"""
task_planner_context.py — Planner Context Builder (Phase B)

Builds a rich PlannerContext from available sources:
  - Task goal + description
  - Task history (previous steps)
  - Channel memory (recent messages)
  - Workspace memory (decisions, reasoning traces)
  - Global memory (rules, defaults)
  - Related file metadata

Priority (truncation order, lowest first):
  Global > Workspace > File > Channel > Task History

V3.1 Integration:
  Memory Intelligence Layer (memory.memory_retriever + memory_compressor)
  feeds into `intelligence_context` section, placed between
  channel_context and workspace_context in priority.

All context is COLLECTED only — this module does NOT call MAEOS
or trigger planning. Callers own the orchestration.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    TaskModel,
    TaskStepModel,
    TaskStepStatus,
    Message,
    FileUpload,
)
from backend.services.memory.memory_types import MemoryType
from backend.services.memory.memory_retriever import MemoryRetriever, RetrievalQuery
from backend.services.memory.memory_compressor import MemoryCompressor

logger = logging.getLogger("task.planner.context")

# ═══════════════════════════════════════════════════════════════
# Token budget
# ═══════════════════════════════════════════════════════════════

MAX_CONTEXT_TOKENS = 6_000  # hard limit for total context (rough char/4)

# Per-section caps (before summary)
MAX_TASK_HISTORY_CHARS = 8_000
MAX_CHANNEL_CHARS = 6_000
MAX_WORKSPACE_CHARS = 4_000
MAX_GLOBAL_CHARS = 2_000
MAX_FILE_CHARS = 3_000

# Summary threshold (char count → trigger LLM summary)
SUMMARY_CHAR_THRESHOLD = 3_000

# V3.1 Memory Intelligence
MAX_INTELLIGENCE_CHARS = 3_000


# ═══════════════════════════════════════════════════════════════
# PlannerContext — structured output
# ═══════════════════════════════════════════════════════════════

@dataclass
class PlannerContext:
    """
    Structured context assembled for the Planner teammate.

    Sections are ordered by priority (higher = more important).
    Each section is a plain-text string.
    """

    task_context: str = ""          # Task goal + description
    memory_context: str = ""        # Previous step outputs (task history)
    channel_context: str = ""       # Recent channel messages
    intelligence_context: str = ""  # V3.1 Memory Intelligence Layer output
    workspace_context: str = ""     # Workspace memory (decisions, traces)
    global_context: str = ""        # Global rules / defaults
    file_context: str = ""          # Related file metadata

    # Metadata
    total_chars: int = 0
    truncated: bool = False
    sources: list[str] = field(default_factory=list)  # which sources contributed

    def to_dict(self) -> dict:
        """Serialize to dict for passing into generate_plan()."""
        return {
            "task_context": self.task_context,
            "memory_context": self.memory_context,
            "channel_context": self.channel_context,
            "intelligence_context": self.intelligence_context,
            "workspace_context": self.workspace_context,
            "global_context": self.global_context,
            "file_context": self.file_context,
            "total_chars": self.total_chars,
            "truncated": self.truncated,
        }

    def to_prompt_section(self) -> str:
        """
        Build a single prompt-worthy context string for the Planner LLM.

        Uses the priority ordering (task > memory > channel > workspace > file > global).
        """
        parts = []

        if self.task_context:
            parts.append(f"[TASK GOAL]\n{self.task_context}")

        if self.memory_context:
            parts.append(f"[TASK HISTORY]\n{self.memory_context}")

        if self.channel_context:
            parts.append(f"[CHANNEL CONTEXT]\n{self.channel_context}")

        if self.intelligence_context:
            parts.append(f"[MEMORY INTELLIGENCE]\n{self.intelligence_context}")

        if self.workspace_context:
            parts.append(f"[WORKSPACE MEMORY]\n{self.workspace_context}")

        if self.file_context:
            parts.append(f"[RELATED FILES]\n{self.file_context}")

        if self.global_context:
            parts.append(f"[GLOBAL RULES]\n{self.global_context}")

        result = "\n\n---\n\n".join(parts)

        if self.truncated:
            result += (
                "\n\n---\n[NOTE: Some context was truncated "
                "due to length limits.]"
            )

        return result

    @classmethod
    def empty(cls) -> PlannerContext:
        """Create an empty context (for fallback / no-source scenarios)."""
        return cls()


# ═══════════════════════════════════════════════════════════════
# Token counting helper
# ═══════════════════════════════════════════════════════════════

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def _truncate(text: str, max_chars: int, label: str = "") -> str:
    """
    Truncate text to max_chars, appending a truncation note.
    Returns original text if under limit.
    """
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    note = (
        f"\n\n[... {label} truncated from {len(text)} chars "
        f"to {max_chars}. See original source for full content.]"
    )
    logger.debug(f"Truncated {label or 'section'}: {len(text)} → {max_chars} chars")
    return truncated + note


# ═══════════════════════════════════════════════════════════════
# PlannerContextBuilder
# ═══════════════════════════════════════════════════════════════

class PlannerContextBuilder:
    """
    Collects and assembles PlannerContext from available data sources.

    Each `_collect_*` method reads from its source and returns a text string.
    The `build()` method assembles all sections, applies caps, and returns
    a PlannerContext.

    Usage:
        builder = PlannerContextBuilder()
        context = await builder.build(db, task, channel_id=...)
        plan = await generate_plan(maeos, goal, context=context.to_dict())
    """

    def __init__(self, max_tokens: int = MAX_CONTEXT_TOKENS, enable_intelligence: bool = True, enable_insights: bool = True):
        self.max_tokens = max_tokens
        self.max_chars = max_tokens * 4  # rough conversion
        self._enable_intelligence = enable_intelligence
        self._enable_insights = enable_insights
        logger.debug(f"PlannerContextBuilder initialized, max_chars={self.max_chars}, intelligence={enable_intelligence}, insights={enable_insights}")

    async def build(
        self,
        db: AsyncSession,
        task: TaskModel,
        *,
        channel_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        global_rules: Optional[list[str]] = None,
    ) -> PlannerContext:
        """
        Build the full PlannerContext for a task.

        Args:
            db: Async DB session.
            task: The TaskModel to build context for.
            channel_id: Explicit channel ID (falls back to task.channel_id).
            workspace_id: Explicit workspace ID (falls back to task.workspace_id).
            global_rules: Optional list of global rules to inject.

        Returns:
            A PlannerContext with all sections populated (potentially truncated).
        """
        cid = channel_id or task.channel_id
        wid = workspace_id or task.workspace_id

        sources: list[str] = []

        # 1. Task context (always present)
        task_context = self._build_task_context(task)
        sources.append("task")
        logger.debug(f"Task context: {len(task_context)} chars")

        # 2. Task history — previous steps (highest priority)
        memory_context = ""
        if task.id:
            memory_context = await self._collect_task_history(db, task.id)
            if memory_context:
                sources.append("history")
            logger.debug(f"Task history: {len(memory_context)} chars")

        # 3. Channel messages
        channel_context = ""
        if cid:
            channel_context = await self._collect_channel_messages(db, cid)
            if channel_context:
                sources.append("channel")
            logger.debug(f"Channel context: {len(channel_context)} chars")

        # 3b. V3.1 Memory Intelligence Layer
        intelligence_context = ""
        if self._enable_intelligence and cid:
            intelligence_context = await self._collect_intelligence(
                task_id=task.id,
                channel_id=cid,
                workspace_id=wid or "",
                task_title=task.title,
            )
            if intelligence_context:
                sources.append("intelligence")
            logger.debug(f"Intelligence context: {len(intelligence_context)} chars")

        # 3c. V2.7 Phase C: Memory Insights (from execution history analysis)
        insights_context = ""
        if self._enable_insights and task.id:
            insights_context = await self._collect_insights(task_id=task.id)
            if insights_context:
                sources.append("insights")
            logger.debug(f"Insights context: {len(insights_context)} chars")

        # Combine intelligence + insights into the same section
        combined_intelligence = self._merge_intelligence_insights(
            intelligence_context, insights_context
        )
        if combined_intelligence:
            if "intelligence" not in sources:
                sources.append("intelligence")

        # 4. Workspace memory
        workspace_context = ""
        if wid:
            workspace_context = await self._collect_workspace_memory(wid)
            if workspace_context:
                sources.append("workspace")
            logger.debug(f"Workspace context: {len(workspace_context)} chars")

        # 5. Global rules
        global_context = self._build_global_context(global_rules)
        if global_context:
            sources.append("global")
        logger.debug(f"Global context: {len(global_context)} chars")

        # 6. Related files
        file_context = ""
        if cid:
            file_context = await self._collect_file_metadata(db, cid)
            if file_context:
                sources.append("files")
            logger.debug(f"File context: {len(file_context)} chars")

        # Assemble with priority-based truncation
        ctx = PlannerContext(
            task_context=task_context,
            memory_context=memory_context,
            channel_context=channel_context,
            intelligence_context=combined_intelligence,
            workspace_context=workspace_context,
            global_context=global_context,
            file_context=file_context,
            sources=sources,
        )

        # Apply total token cap (truncate lowest-priority sections first)
        truncated = self._apply_total_cap(ctx)
        ctx.total_chars = sum(
            len(getattr(ctx, section, ""))
            for section in ["task_context", "memory_context", "channel_context",
                           "intelligence_context", "workspace_context",
                           "file_context", "global_context"]
        )
        ctx.truncated = truncated

        logger.info(
            f"PlannerContext built: {len(sources)} sources, "
            f"{ctx.total_chars} chars, truncated={truncated}"
        )
        return ctx

    # ── Section builders ──

    def _build_task_context(self, task: TaskModel) -> str:
        """Build the task goal section."""
        parts = [
            f"Title: {task.title}",
            f"Description: {task.description}",
            f"Intent: {task.intent or 'N/A'}",
            f"Priority: {task.priority}",
        ]
        if task.created_by:
            parts.append(f"Created by: {task.created_by}")
        return "\n".join(parts)

    async def _collect_task_history(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> str:
        """
        Collect completed steps as task history.
        Ordered by step order. Each includes objective + output.
        """
        result = await db.execute(
            select(TaskStepModel)
            .where(TaskStepModel.task_id == task_id)
            .order_by(TaskStepModel.order)
        )
        steps = list(result.scalars().all())

        if not steps:
            return ""

        lines = []
        for step in steps:
            status_str = step.status or "UNKNOWN"
            output = (step.output or "")[:2000]  # cap per-step output
            lines.append(
                f"Step {step.order} [{status_str}]: {step.objective}\n"
                f"  Output: {output}\n"
            )

        text = "\n".join(lines)
        return _truncate(text, MAX_TASK_HISTORY_CHARS, "task history")

    async def _collect_channel_messages(
        self,
        db: AsyncSession,
        channel_id: str,
    ) -> str:
        """
        Collect recent channel messages as conversation context.
        Limited to last N messages for relevance.
        """
        result = await db.execute(
            select(Message)
            .where(Message.channel_id == channel_id)
            .order_by(Message.created_at.desc())
            .limit(30)
        )
        messages = list(result.scalars().all())
        messages.reverse()  # chronological order

        if not messages:
            return ""

        lines = []
        for msg in messages:
            role_display = "User" if msg.role == "user" else "AI"
            content = (msg.content or "")[:500]
            lines.append(f"[{role_display}]: {content}")

        text = "\n".join(lines)
        return _truncate(text, MAX_CHANNEL_CHARS, "channel messages")

    async def _collect_workspace_memory(
        self,
        workspace_id: str,
    ) -> str:
        """
        Collect workspace memory for context.

        Uses WorkspaceMemory from existing infrastructure.
        Falls back gracefully if workspace does not exist.
        """
        try:
            # Try to get workspace memory entries
            from backend.services.workspace_memory import WorkspaceMemory
            from backend.services.collaboration.shared_context import (
                get_context_store,
            )

            shared_ctx = get_context_store().get_or_create(workspace_id)
            mem = WorkspaceMemory(workspace_id, shared_context=shared_ctx)

            entries = mem.get_all()
            if not entries:
                return ""

            # Sort by priority: decisions > revisions > reasoning > conversation
            type_order = {
                "decision": 0,
                "revision": 1,
                "reasoning": 2,
                "conversation": 3,
                "context": 4,
                "interruption": 5,
            }
            entries.sort(key=lambda e: type_order.get(e.memory_type, 99))

            lines = []
            # Collect up to 15 entries
            for entry in entries[:15]:
                type_tag = entry.memory_type.upper()
                content = (entry.content or "")[:500]
                lines.append(f"[{type_tag}] {entry.actor}: {content}")

            text = "\n".join(lines)
            if not text.strip():
                return ""

            return _truncate(text, MAX_WORKSPACE_CHARS, "workspace memory")

        except Exception as e:
            logger.debug(f"Workspace memory unavailable: {e}")
            return ""

    # ── V3.1 Memory Intelligence Layer ──────────────────

    async def _collect_intelligence(
        self,
        task_id: str,
        channel_id: str,
        workspace_id: str,
        task_title: str,
    ) -> str:
        """Collect V3.1 Memory Intelligence context.

        Flow:
          1. Build a RetrievalQuery scoped to task + channel + workspace
          2. Fetch + rank relevant MemoryItems
          3. Compress into a token-efficient string

        Falls back gracefully if the memory layer or DB is unavailable.
        """
        try:
            from backend.services.memory.memory_retriever import MemoryRetriever, RetrievalQuery
            from backend.services.memory.memory_compressor import MemoryCompressor

            retriever = MemoryRetriever()
            compressor = MemoryCompressor(max_chars=MAX_INTELLIGENCE_CHARS)

            # Key terms from task title for relevance matching
            keywords = [
                w for w in task_title.replace(",", " ").split()
                if len(w) > 2
            ]

            query = RetrievalQuery(
                source_id=channel_id,
                memory_types=[
                    MemoryType.EXECUTION,
                    MemoryType.DECISION,
                    MemoryType.EVENT,
                    MemoryType.TASK,
                ],
                keywords=keywords or None,
                context_hint=f"Task: {task_title}",
                top_k=15,
                max_hours=72.0,  # last 3 days
            )

            result = await retriever.retrieve(query)

            if not result.items:
                return ""

            compressed = compressor.compress(
                result.items,
                max_chars=MAX_INTELLIGENCE_CHARS,
            )

            if not compressed.text:
                return ""

            # Add a compact header with stats
            stats = (
                f"[{compressed.items_used} items from "
                f"{compressed.items_total} candidates, "
                f"{compressed.chars_after}/{compressed.chars_before} chars]"
            )

            return f"{stats}\n{compressed.text}"

        except ImportError as e:
            logger.debug(f"Memory intelligence unavailable (import): {e}")
            return ""
        except Exception as e:
            logger.debug(f"Memory intelligence unavailable: {e}")
            return ""

    # ── V2.7 Phase C: Memory Insights ─────────────────────

    async def _collect_insights(
        self,
        task_id: str,
    ) -> str:
        """
        Collect MemoryInsights for a task and format for Planner context.

        Uses MemoryIntelligenceService to fetch insights for this task.
        Returns a compact, token-efficient text block.
        """
        try:
            from backend.services.memory.memory_intelligence import (
                get_intelligence_service,
            )

            svc = get_intelligence_service()
            insights = await svc.list_insights(task_id=task_id, limit=20)

            if not insights:
                return ""

            lines: list[str] = []
            for ins in insights:
                line = f"[{ins.type}] {ins.title}: {ins.content[:200]}"
                lines.append(line)

            if not lines:
                return ""

            text = "\n".join(lines)
            truncated = _truncate(text, MAX_INTELLIGENCE_CHARS, "insights")
            return f"[INSIGHTS from previous executions ({len(insights)} items)]\n{truncated}"

        except ImportError as e:
            logger.debug(f"Insights unavailable (import): {e}")
            return ""
        except Exception as e:
            logger.debug(f"Insights unavailable: {e}")
            return ""

    @staticmethod
    def _merge_intelligence_insights(
        intelligence_text: str,
        insights_text: str,
    ) -> str:
        """
        Merge V3.1 Memory Intelligence + V2.7 Phase C Insights into one section.

        If both exist, concatenate with a separator.
        If only one exists, return that alone.
        """
        if not intelligence_text and not insights_text:
            return ""
        if not insights_text:
            return intelligence_text
        if not intelligence_text:
            return insights_text
        return f"{intelligence_text}\n\n---\n\n{insights_text}"

    def _build_global_context(
        self,
        global_rules: Optional[list[str]] = None,
    ) -> str:
        """Build global rules / defaults section."""
        if not global_rules:
            return ""

        lines = [f"- {rule}" for rule in global_rules]
        text = "\n".join(lines)
        return _truncate(text, MAX_GLOBAL_CHARS, "global rules")

    async def _collect_file_metadata(
        self,
        db: AsyncSession,
        channel_id: str,
    ) -> str:
        """Collect related file metadata from the channel."""
        try:
            result = await db.execute(
                select(FileUpload)
                .where(FileUpload.user_id == channel_id)
                .order_by(FileUpload.created_at.desc())
                .limit(10)
            )
            files = list(result.scalars().all())

            if not files:
                return ""

            lines = []
            for f in files:
                status = f.status or "unknown"
                size_info = f"{f.size} bytes" if f.size else "unknown size"
                lines.append(
                    f"- {f.filename} ({f.file_type}, {size_info}, status={status})"
                )

            text = "\n".join(lines)
            if not text.strip():
                return ""

            return _truncate(text, MAX_FILE_CHARS, "file metadata")

        except Exception as e:
            logger.debug(f"File metadata unavailable: {e}")
            return ""

    # ── Token cap enforcement ──

    def _apply_total_cap(self, ctx: PlannerContext) -> bool:
        """
        Enforce total token cap by dropping/truncating lowest-priority sections.

        Priority order (lowest first = most likely to be dropped):
        global → workspace → file → intelligence → channel → history → task

        Returns True if any truncation was applied.
        """
        # Priority-ordered section keys (lowest priority first)
        priority_order = [
            "global_context",
            "workspace_context",
            "file_context",
            "intelligence_context",
            "channel_context",
            "memory_context",
        ]
        # task_context is never dropped

        total = sum(len(getattr(ctx, k, "") or "") for k in priority_order)
        total += len(ctx.task_context)

        if total <= self.max_chars:
            return False

        logger.info(
            f"Context exceeds {self.max_chars} chars ({total}), "
            f"truncating lowest-priority sections"
        )

        # Try dropping sections one by one (lowest priority first)
        dropped = 0
        for section in priority_order:
            current = getattr(ctx, section, "")
            if not current:
                continue

            # First try to truncate to half
            half = len(current) // 2
            truncated = current[:half]
            note = (
                f"\n[... section truncated from {len(current)} chars to {half}]"
            )
            setattr(ctx, section, truncated + note)

            total = sum(len(getattr(ctx, k, "") or "") for k in priority_order)
            total += len(ctx.task_context)

            if total <= self.max_chars:
                logger.info(
                    f"Truncated {section} to fit within budget "
                    f"({total}/{self.max_chars} chars)"
                )
                return True

            # If still over, drop the section entirely
            setattr(ctx, section, "")
            total = sum(len(getattr(ctx, k, "") or "") for k in priority_order)
            total += len(ctx.task_context)
            dropped += 1

            if total <= self.max_chars:
                logger.info(
                    f"Dropped {section} to fit within budget "
                    f"({total}/{self.max_chars} chars)"
                )
                return True

        if dropped > 0:
            logger.warning(
                f"Dropped {dropped} sections, "
                f"context still {total}/{self.max_chars} chars [may exceed]"
            )

        return dropped > 0


# ═══════════════════════════════════════════════════════════════
# Convenience function for external callers
# ═══════════════════════════════════════════════════════════════

async def build_planner_context(
    db: AsyncSession,
    task: TaskModel,
    *,
    channel_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    global_rules: Optional[list[str]] = None,
    max_tokens: int = MAX_CONTEXT_TOKENS,
    enable_intelligence: bool = True,
) -> PlannerContext:
    """
    One-shot convenience: build a PlannerContext for a task.

    Example:
        context = await build_planner_context(db, task)
        plan = await generate_plan(maeos, goal, context=context.to_dict())
    """
    builder = PlannerContextBuilder(
        max_tokens=max_tokens,
        enable_intelligence=enable_intelligence,
    )
    return await builder.build(
        db,
        task,
        channel_id=channel_id,
        workspace_id=workspace_id,
        global_rules=global_rules,
    )
