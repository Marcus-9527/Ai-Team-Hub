"""OrganizationContextBuilder — unified context from a run_id.

Provides goal/history/memory/events/members for both Chat and Task runs.
Includes resolved capabilities per role for tool resolution.

Moved from context_builder.py (Phase 1.5).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.organization import OrganizationRunService


class OrganizationContext:
    """Unified context object exposed to consumers."""

    def __init__(self, data: dict):
        self.run_id = data.get("run_id", "")
        self.run_type = data.get("run_type", "")
        self.title = data.get("title", "")
        self.channel_id = data.get("channel_id", "")
        self.workspace_id = data.get("workspace_id", "")
        self.status = data.get("status", "")
        self.created_at = data.get("created_at")
        self.members = data.get("members", [])
        self.channel_name = data.get("channel_name", "")
        # chat-specific
        self.recent_turns = data.get("recent_turns", [])
        # task-specific
        self.goal = data.get("goal", "")
        self.task_id = data.get("task_id", "")
        self.task_status = data.get("task_status", "")
        self.steps_count = data.get("steps_count", 0)
        # capabilities
        self.capabilities = data.get("capabilities", {})
        # memory — populated by builder or externally, for decision engine
        self.memory = data.get("memory", {})
        # enriched identity per member (teammate_id → identity dict)
        self.members_info = data.get("members_info", {})
        # organization learning experience
        self.experience = data.get("experience", {})

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_type": self.run_type,
            "title": self.title,
            "channel_id": self.channel_id,
            "workspace_id": self.workspace_id,
            "status": self.status,
            "created_at": self.created_at,
            "members": self.members,
            "channel_name": self.channel_name,
            "goal": self.goal,
            "task_id": self.task_id,
            "task_status": self.task_status,
            "steps_count": self.steps_count,
            "recent_turns": self.recent_turns,
            "capabilities": self.capabilities,
            "memory": self.memory,
            "members_info": self.members_info,
            "experience": self.experience,
        }


class OrganizationContextBuilder:
    """Assembles OrganizationContext from a run_id."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build(self, run_id: str) -> OrganizationContext:
        data = await OrganizationRunService.get_run_context(self.db, run_id)
        # Expose default role→capability mappings so downstream context consumers
        # know which roles get which tools without re-importing the registry.
        from backend.services.organization.registry import DEFAULT_ROLE_CAPABILITIES
        data["capabilities"] = {
            role: list(caps)
            for role, caps in DEFAULT_ROLE_CAPABILITIES.items()
        }
        # Enrich member list with identity data
        from backend.services.organization.identity import TeammateIdentityService
        svc = TeammateIdentityService(self.db)
        members_info = {}
        for mid in data.get("members", []):
            members_info[mid] = await svc.get_identity(mid)
        data["members_info"] = members_info
        return OrganizationContext(data)

    async def build_from_source(
        self,
        *,
        run_type: str,
        source_id: str,
        workspace_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> OrganizationContext:
        """Find or create a run for a source, then build context."""
        from sqlalchemy import select
        from backend.models.organization_run import OrganizationRun

        result = await self.db.execute(
            select(OrganizationRun)
            .where(
                OrganizationRun.run_type == run_type,
                OrganizationRun.source_id == source_id,
            )
            .limit(1)
        )
        run = result.scalar_one_or_none()

        if not run:
            run = await OrganizationRunService.create_run(
                self.db,
                run_type=run_type,
                source_id=source_id,
                workspace_id=workspace_id,
                channel_id=channel_id,
                title=title,
            )

        return await self.build(run.id)
