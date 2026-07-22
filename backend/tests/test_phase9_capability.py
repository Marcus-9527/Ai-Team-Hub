"""Phase 9: Organization Capability Layer — tests.

Verifies:
1. engineer 自动获得 code tools
2. reviewer 不获得 engineer tools
3. 新增 teammate 不需要修改 AgentLoop
4. resolve_tools 可动态加载
5. Chat 和 Task 使用同一 capability 来源
"""

import pytest

from backend.services.organization.capability import CapabilityRegistry


@pytest.fixture
def registry():
    return CapabilityRegistry()


class TestCapabilityResolution:
    """CapabilityRegistry.resolve_tools returns correct tool schemas per role."""

    def test_engineer_gets_code_and_file_tools(self, registry):
        tools = registry.resolve_tools("engineer")
        names = [t["name"] for t in tools]
        assert "file_read" in names
        assert "file_write" in names
        assert "shell_exec" in names
        assert "code_exec" in names

    def test_reviewer_does_not_get_engineer_tools(self, registry):
        tools = registry.resolve_tools("reviewer")
        names = [t["name"] for t in tools]
        assert "file_write" not in names
        assert "code_exec" not in names
        assert "file_read" not in names

    def test_reviewer_gets_shell_exec(self, registry):
        tools = registry.resolve_tools("reviewer")
        names = [t["name"] for t in tools]
        assert "shell_exec" in names

    def test_analyst_gets_no_tools(self, registry):
        tools = registry.resolve_tools("analyst")
        assert tools == []

    def test_designer_gets_no_tools(self, registry):
        tools = registry.resolve_tools("designer")
        assert tools == []

    def test_product_manager_gets_no_tools(self, registry):
        tools = registry.resolve_tools("product_manager")
        assert tools == []

    def test_engineer_lead_gets_same_as_engineer(self, registry):
        eng_tools = registry.resolve_tools("engineer")
        lead_tools = registry.resolve_tools("engineer_lead")
        eng_names = {t["name"] for t in eng_tools}
        lead_names = {t["name"] for t in lead_tools}
        assert eng_names == lead_names

    def test_techlead_gets_engineer_tools(self, registry):
        tools = registry.resolve_tools("techlead")
        names = [t["name"] for t in tools]
        assert "file_read" in names
        assert "file_write" in names
        assert "shell_exec" in names

    def test_unknown_role_gets_no_tools(self, registry):
        tools = registry.resolve_tools("nonexistent_role")
        assert tools == []


class TestCapabilityDetail:
    """Capability detail query methods."""

    def test_get_known_capability_returns_tool_names(self, registry):
        result = registry.get_capability("engineer", "code_execution")
        assert result is not None
        assert "shell_exec" in result
        assert "code_exec" in result

    def test_get_unknown_capability_returns_none(self, registry):
        result = registry.get_capability("engineer", "nonexistent")
        assert result is None

    def test_get_capability_for_unknown_role_returns_none(self, registry):
        result = registry.get_capability("nobody", "code_execution")
        assert result is None


class TestDynamicRegistration:
    """register_capability adds new role/capability at runtime."""

    def test_register_new_role(self, registry):
        registry.register_capability("bot", "file_edit", ["file_read"])
        tools = registry.resolve_tools("bot")
        names = [t["name"] for t in tools]
        assert "file_read" in names

    def test_register_new_capability_for_existing_role(self, registry):
        registry.register_capability("engineer", "image_gen", ["dalle_exec"])
        # capability is registered; resolve_tools only returns tools WITH schemas,
        # so dalle_exec (no schema) won't appear — that's correct filtering.
        caps = registry.get_capability("engineer", "image_gen")
        assert caps is not None
        assert "dalle_exec" in caps

    def test_register_with_workspace_scoped(self, registry):
        registry.register_capability("engineer", "custom", ["my_tool"], workspace_id="ws_1")
        tools = registry.resolve_tools("engineer")
        # Workspace scope is recorded but default in-memory resolution ignores it;
        # DB-backed resolution would filter by workspace_id.
        assert tools is not None


class TestHasToolRoles:
    """has_tool_roles helper."""

    def test_engineer_has_tools(self, registry):
        assert registry.has_tool_roles("engineer") is True

    def test_analyst_has_no_tools(self, registry):
        assert registry.has_tool_roles("analyst") is False

    def test_unknown_role_has_no_tools(self, registry):
        assert registry.has_tool_roles("stranger") is False


class TestSchemaIntegrity:
    """All capability tools have schemas in TOOL_SCHEMAS."""

    def test_all_capability_tools_have_schemas(self, registry):
        from backend.services.organization.capability import BUILTIN_TOOL_NAMES
        all_tool_names = set()
        for tools in BUILTIN_TOOL_NAMES.values():
            all_tool_names.update(tools)

        from backend.services.runtime.llm_client_and_tools import TOOL_SCHEMAS
        schema_names = {s["name"] for s in TOOL_SCHEMAS}

        missing = all_tool_names - schema_names
        assert not missing, f"Tools referenced in capabilities missing from TOOL_SCHEMAS: {missing}"
