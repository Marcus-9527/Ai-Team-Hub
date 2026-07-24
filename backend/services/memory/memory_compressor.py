"""Memory Intelligence Layer — Memory Compressor.

Compresses ranked MemoryItems into a compact string for PlannerContext.

Strategies:
  1. Drop lowest-ranked items when over token budget.
  2. Truncate long item content with summary markers.
  3. Merge adjacent items of the same type into consolidated bullet points.

Output: CompressedContext — a structured, token-efficient memory block.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from backend.services.memory.memory_types import MemoryItem
from backend.services.memory.memory_retriever import RankedItem

logger = logging.getLogger("memory.compressor")

# ── Defaults ────────────────────────────────────────────────────

DEFAULT_MAX_CHARS = 3_000       # total compressed output cap
MAX_ITEM_CHARS = 600            # per-item content truncation
SECTION_HEADER_CHARS = 60       # estimate for section headers


@dataclass
class CompressedContext:
    """Compressed memory context ready for PlannerContextBuilder."""

    text: str = ""                     # The compressed memory text
    items_used: int = 0                # How many items survived compression
    items_total: int = 0               # How many items were input
    chars_before: int = 0              # Total chars before compression
    chars_after: int = 0               # Total chars after compression
    dropped_types: dict[str, int] = field(default_factory=dict)  # type → count dropped
    truncated: bool = False            # Whether any items were dropped


# ═════════════════════════════════════════════════════════════════
# MemoryCompressor
# ═════════════════════════════════════════════════════════════════


class MemoryCompressor:
    """Compresses ranked memory items into a compact context string.

    Use:
        compressor = MemoryCompressor(max_chars=3000)
        ctx = compressor.compress(ranked_items)
        planner_context.memory_context = ctx.text
    """

    def __init__(
        self,
        max_chars: int = DEFAULT_MAX_CHARS,
        max_item_chars: int = MAX_ITEM_CHARS,
    ):
        self.max_chars = max_chars
        self.max_item_chars = max_item_chars

    # ── Public API ─────────────────────────────────────────────

    def compress(
        self,
        ranked: list[RankedItem],
        *,
        max_chars: Optional[int] = None,
        include_breakdown: bool = False,
    ) -> CompressedContext:
        """Compress ranked items into a compact context block.

        Args:
            ranked: Ranked items (highest score first).
            max_chars: Override max output size.
            include_breakdown: If True, include score breakdown lines.

        Returns:
            CompressedContext with text and compression stats.
        """
        if not ranked:
            return CompressedContext(
                text="",
                items_used=0,
                items_total=0,
            )

        chars_limit = max_chars or self.max_chars
        total_in = sum(len(r.item) for r in ranked)

        # Group by type for structured output
        by_type: dict[str, list[RankedItem]] = {}
        for r in ranked:
            by_type.setdefault(r.item.memory_type, []).append(r)

        # Build compressed text, dropping lowest-priority types first
        type_order = [
            "EXECUTION", "DECISION", "TASK", "CHANNEL",
            "WORKSPACE", "EVENT", "GLOBAL",
        ]

        parts: list[str] = []
        used_count = 0
        total_out = 0
        dropped: dict[str, int] = {}
        budget_remaining = chars_limit

        # Process in priority order (highest first)
        for mt in type_order:
            if mt not in by_type:
                continue

            items = by_type[mt]
            # Items within a type are already sorted by score (descending)

            section_parts: list[str] = []
            section_count = 0

            for ranked_item in items:
                item = ranked_item.item
                content = item.content.strip()
                if not content:
                    continue

                # Truncate long content
                if len(content) > self.max_item_chars:
                    content = content[: self.max_item_chars] + "..."

                # Build one line
                line = f"  - {content}"
                if include_breakdown:
                    line += f" [score={ranked_item.score}]"

                # Check budget
                line_len = len(line) + 1  # +1 for newline
                if line_len > budget_remaining:
                    dropped[mt] = dropped.get(mt, 0) + 1
                    continue

                section_parts.append(line)
                budget_remaining -= line_len
                section_count += 1
                total_out += len(item)

            if section_parts:
                header = f"[{mt}]"
                header_len = len(header) + 1
                if header_len > budget_remaining:
                    # Can't even fit header — drop entire section
                    dropped[mt] = dropped.get(mt, 0) + len(section_parts)
                    continue

                budget_remaining -= header_len
                section_text = header + "\n" + "\n".join(section_parts)
                parts.append(section_text)
                used_count += section_count

            # Track dropped within this type
            remaining_in_type = len(items) - section_count
            if remaining_in_type > 0:
                dropped[mt] = dropped.get(mt, 0) + remaining_in_type

        compressed = "\n\n".join(parts)
        total_out = sum(len(r.item) for r in ranked[:used_count])

        return CompressedContext(
            text=compressed,
            items_used=used_count,
            items_total=len(ranked),
            chars_before=total_in,
            chars_after=len(compressed),
            dropped_types=dropped,
            truncated=used_count < len(ranked),
        )

    # ── Helper: merge with other context ───────────────────────

    def merge_into_context(
        self,
        existing_text: str,
        compressed: CompressedContext,
        *,
        max_total_chars: int = 6_000,
    ) -> str:
        """Merge compressed memory into an existing context string.

        If the combined text exceeds max_total_chars, the memory
        section is further truncated (lowest-score items removed first).
        """
        if not compressed.text:
            return existing_text

        combined = existing_text
        if combined and not combined.endswith("\n\n"):
            combined += "\n\n"

        combined += "[MEMORY INTELLIGENCE]\n"
        combined += compressed.text

        if len(combined) <= max_total_chars:
            return combined

        # Truncate memory section: drop from end (lowest priority)
        excess = len(combined) - max_total_chars
        mem_lines = compressed.text.split("\n")
        while excess > 0 and len(mem_lines) > 3:
            removed = mem_lines.pop()
            excess -= len(removed) + 1
            if not removed.strip() or removed.startswith("  -"):
                # Keep section header
                pass

        memory_part = "\n".join(mem_lines)
        if len(memory_part) > max_total_chars // 2:
            memory_part = memory_part[: max_total_chars // 2] + "\n[...memory truncated]"

        # Rebuild
        combined = existing_text
        if combined and not combined.endswith("\n\n"):
            combined += "\n\n"
        combined += "[MEMORY INTELLIGENCE]\n"
        combined += memory_part

        if len(combined) > max_total_chars:
            combined = combined[:max_total_chars] + "\n[...output truncated]"

        return combined
