"""CapabilityRegistry — maps role → capabilities → tool schemas.

Single source of truth for which tools each role can use.
Defaults are in-memory; optional DB-backed customization via OrganizationCapability table.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Built-in capability → tool-name mapping ──
# ponytail: 4 tools, 5 roles — a dict is cheaper than a DB table for defaults.
# Add when admins need per-workspace tool customization via UI.
BUILTIN_TOOL_NAMES: dict[str, list[str]] = {
    "code_execution": ["shell_exec", "code_exec"],
    "file_edit": ["file_read", "file_write"],
    "git": ["shell_exec"],
    "git_diff": ["shell_exec"],
    "test_runner": ["shell_exec"],
}

# ponytail: role → capabilities. Non-tool roles (analyst/designer/pm) get []
# explicitly so resolve_tools returns [] for them rather than the fallback.
DEFAULT_ROLE_CAPABILITIES: dict[str, list[str]] = {
    "engineer": ["code_execution", "file_edit", "git"],
    "engineer_lead": ["code_execution", "file_edit", "git"],
    "techlead": ["code_execution", "file_edit", "git"],
    "reviewer": ["git_diff", "test_runner"],
    # analyst, designer, product_manager, etc → no tools
}

# Schema cache: lazily loaded from TOOL_SCHEMAS
_TOOL_SCHEMA_CACHE: dict[str, dict] | None = None


def _tool_schemas() -> dict[str, dict]:
    """Lazy-load tool schemas keyed by tool name."""
    global _TOOL_SCHEMA_CACHE
    if _TOOL_SCHEMA_CACHE is not None:
        return _TOOL_SCHEMA_CACHE
    # ponytail: single import, avoid circular on first load
    from backend.services.runtime.llm_client_and_tools import TOOL_SCHEMAS
    _TOOL_SCHEMA_CACHE = {s["name"]: s for s in TOOL_SCHEMAS}
    return _TOOL_SCHEMA_CACHE


class CapabilityRegistry:
    """Resolve tools for a role via its capabilities.

    Usage:
        registry = CapabilityRegistry()
        tools = registry.resolve_tools("engineer")  # → [...tool schemas]
        tools = registry.resolve_tools("analyst")   # → []

    register_capability() stores overrides at instance level so tests
    don't contaminate the module-global defaults.
    """

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db
        # Instance-level overrides (mutate these, not the module globals)
        self._cap_overrides: dict[str, list[str]] = {}
        self._role_overrides: dict[str, list[str]] = {}

    # ── helpers ──

    def _resolve_cap_tools(self, cap: str) -> list[str]:
        """Tool names for a capability, merging defaults + overrides."""
        if cap in self._cap_overrides:
            return self._cap_overrides[cap]
        return BUILTIN_TOOL_NAMES.get(cap, [])

    def _role_caps(self, role: str) -> list[str]:
        """Capability names for a role, merging defaults + overrides."""
        if role in self._role_overrides:
            return self._role_overrides[role]
        return DEFAULT_ROLE_CAPABILITIES.get(role, [])

    def resolve_tools(self, role: str) -> list[dict]:
        """Return tool schemas available to *role* based on its capabilities.

        Non-tool roles (analyst, designer, pm, etc.) return [].
        """
        cap_names = self._role_caps(role)
        if not cap_names:
            return []

        schemas = _tool_schemas()
        result: list[dict] = []
        seen: set[str] = set()
        for cap in cap_names:
            tool_names = self._resolve_cap_tools(cap)
            for name in tool_names:
                if name not in seen and name in schemas:
                    result.append(schemas[name])
                    seen.add(name)
        return result

    def get_capability(self, role: str, capability: str) -> Optional[list[str]]:
        """Return tool names for a specific (role, capability), or None."""
        # Check role has this capability first
        role_caps = self._role_caps(role)
        if capability not in role_caps:
            return None
        # Then return tool names
        if capability in self._cap_overrides:
            return self._cap_overrides[capability]
        return BUILTIN_TOOL_NAMES.get(capability)

    def register_capability(
        self,
        role: str,
        capability: str,
        tools: list[str],
        *,
        workspace_id: str = "",
    ) -> None:
        """Register or override a capability for a role (instance-level).

        Does NOT mutate module-level globals — safe for test isolation.
        For persistent DB-backed registration, use register_capability_db().
        """
        # Store tool names under this capability
        if capability in self._cap_overrides:
            existing = set(self._cap_overrides[capability])
            existing.update(tools)
            self._cap_overrides[capability] = list(existing)
        else:
            self._cap_overrides[capability] = list(tools)

        # Ensure role has this capability
        if role in self._role_overrides:
            if capability not in self._role_overrides[role]:
                self._role_overrides[role].append(capability)
        else:
            # Copy defaults + add new
            base = list(DEFAULT_ROLE_CAPABILITIES.get(role, []))
            if capability not in base:
                base.append(capability)
            self._role_overrides[role] = base

    async def register_capability_db(
        self,
        role: str,
        capability: str,
        tools: list[str],
        *,
        workspace_id: str = "",
    ) -> None:
        """Register a capability in the DB (persistent, per-workspace override)."""
        if self.db is None:
            logger.warning("[CapRegistry] no DB session, registering in-memory only")
            self.register_capability(role, capability, tools, workspace_id=workspace_id)
            return

        from sqlalchemy import select
        from backend.models.organization_capability import OrganizationCapability

        result = await self.db.execute(
            select(OrganizationCapability).where(
                OrganizationCapability.workspace_id == (workspace_id or None),
                OrganizationCapability.role == role,
                OrganizationCapability.capability == capability,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.tools = tools
        else:
            self.db.add(
                OrganizationCapability(
                    workspace_id=workspace_id or None,
                    role=role,
                    capability=capability,
                    tools=tools,
                )
            )
        await self.db.flush()

    def has_tool_roles(self, role: str) -> bool:
        """Check if a role has any tools assigned."""
        caps = self._role_caps(role)
        return bool(caps)


# Module-level singleton (stateless)
_registry: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    global _registry
    if _registry is None:
        _registry = CapabilityRegistry()
    return _registry
