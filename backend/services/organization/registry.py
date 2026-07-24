"""CapabilityRegistry — maps role → capabilities → tool schemas.
OrganizationStateService — run-scoped key-value state store.

Merged from capability.py + state.py (Phase 1.5).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.organization_state import OrganizationState

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# CapabilityRegistry
# ════════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════════
# OrganizationStateService
# ════════════════════════════════════════════════════════════════

def _utcnow():
    return datetime.now(timezone.utc)


class OrganizationStateService:
    """CRUD for OrganizationState with optional SessionEvent emission."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Write ──

    async def set_state(
        self,
        run_id: str,
        state_type: str,
        key: str,
        value: dict,
        *,
        trigger_id: Optional[str] = None,
    ) -> OrganizationState:
        """Upsert a state entry. Emits state.updated if trigger_id given."""
        existing = await self.get_state(run_id, state_type, key)
        if existing:
            existing.value = value
            existing.updated_at = _utcnow()
            self.db.add(existing)
        else:
            existing = OrganizationState(
                run_id=run_id,
                state_type=state_type,
                key=key,
                value=value,
            )
            self.db.add(existing)
        await self.db.flush()

        if trigger_id:
            await self._emit_state_event(
                trigger_id, run_id, state_type, key, value,
            )
        return existing

    async def update_state(
        self,
        run_id: str,
        state_type: str,
        key: str,
        value: dict,
        *,
        trigger_id: Optional[str] = None,
    ) -> OrganizationState:
        """Merge value into existing state. Emits state.updated if trigger_id given."""
        existing = await self.get_state(run_id, state_type, key)
        if existing:
            merged_val = {**(existing.value or {}), **value}
            existing.value = merged_val
            existing.updated_at = _utcnow()
            self.db.add(existing)
        else:
            merged_val = value
            existing = OrganizationState(
                run_id=run_id,
                state_type=state_type,
                key=key,
                value=value,
            )
            self.db.add(existing)
        await self.db.flush()

        if trigger_id:
            await self._emit_state_event(
                trigger_id, run_id, state_type, key, merged_val,
            )
        return existing

    # ── Read ──

    async def get_state(
        self,
        run_id: str,
        state_type: str,
        key: str,
    ) -> Optional[OrganizationState]:
        """Fetch a single state entry by (run_id, state_type, key)."""
        r = await self.db.execute(
            select(OrganizationState).where(
                OrganizationState.run_id == run_id,
                OrganizationState.state_type == state_type,
                OrganizationState.key == key,
            )
        )
        return r.scalar_one_or_none()

    async def list_states(
        self,
        run_id: str,
        state_type: Optional[str] = None,
    ) -> list[OrganizationState]:
        """List all states for a run, optionally filtered by state_type."""
        q = select(OrganizationState).where(
            OrganizationState.run_id == run_id,
        ).order_by(OrganizationState.state_type, OrganizationState.key)
        if state_type:
            q = q.where(OrganizationState.state_type == state_type)
        r = await self.db.execute(q)
        return list(r.scalars().all())

    async def delete_state(
        self,
        run_id: str,
        state_type: str,
        key: str,
    ) -> bool:
        """Delete a state entry. Returns True if something was deleted."""
        existing = await self.get_state(run_id, state_type, key)
        if existing:
            await self.db.delete(existing)
            await self.db.flush()
            return True
        return False

    # ── Internal ──

    async def _emit_state_event(
        self,
        trigger_id: str,
        run_id: str,
        state_type: str,
        key: str,
        value: dict,
    ) -> None:
        """Emit a state.updated SessionEvent."""
        try:
            from backend.services.session.session_hooks import SessionHooks
            hooks = SessionHooks(self.db)
            await hooks.emit_event(
                trigger_id,
                event_type="state.updated",
                payload={
                    "run_id": run_id,
                    "state_type": state_type,
                    "key": key,
                    "value": value,
                },
            )
        except Exception as e:
            logger.warning(
                "[OrgState] Failed to emit state.updated event (non-fatal): %s", e
            )
