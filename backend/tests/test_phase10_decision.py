"""Phase 10: Organization Decision Layer — tests.

Verifies:
1. Chat (short Q&A) → RESPOND
2. Code/debug request → EXECUTE
3. Long/multi-step task → DELEGATE
4. Memory field accessible on context (role selection hook)
5. Chat/Task share same DecisionEngine
"""

import pytest

from backend.services.organization.context_builder import OrganizationContext
from backend.services.organization.runtime import OrganizationAction
from backend.services.organization.decision import OrganizationDecisionEngine


@pytest.fixture
def engine():
    return OrganizationDecisionEngine()


@pytest.fixture
def chat_ctx():
    return OrganizationContext({
        "run_id": "run-1",
        "run_type": "chat",
        "channel_id": "ch-1",
        "members": ["tm-1", "tm-2"],
    })


@pytest.fixture
def task_ctx():
    return OrganizationContext({
        "run_id": "run-2",
        "run_type": "task",
        "task_id": "task-1",
        "goal": "Refactor auth module",
        "steps_count": 5,
    })


class TestDecisionChat:
    """Short/chatty inputs → RESPOND."""

    def test_short_question(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "Hello") == OrganizationAction.RESPOND

    def test_very_short(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "Hi") == OrganizationAction.RESPOND

    def test_greeting(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "早上好") == OrganizationAction.RESPOND

    def test_empty_input(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "") == OrganizationAction.RESPOND

    def test_short_follow_up(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "什么意思") == OrganizationAction.RESPOND


class TestDecisionCode:
    """Code blocks / debug keywords → EXECUTE."""

    def test_markdown_code_block(self, engine, chat_ctx):
        inp = "```python\nprint('hello')\n```\nCan you run this?"
        assert engine.decide(chat_ctx, inp) == OrganizationAction.EXECUTE

    def test_inline_function_call(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "Call `foo()` for me") == OrganizationAction.EXECUTE

    def test_debug_keyword(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "Fix this bug in auth") == OrganizationAction.EXECUTE

    def test_error_mention(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "I got a traceback error") == OrganizationAction.EXECUTE

    def test_chinese_debug(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "修复登录页面的报错") == OrganizationAction.EXECUTE


class TestDecisionMultiStep:
    """Long / planning inputs → DELEGATE."""

    def test_long_text(self, engine, chat_ctx):
        inp = "We need to " + "x" * 301
        assert engine.decide(chat_ctx, inp) == OrganizationAction.DELEGATE

    def test_step_keyword(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "Plan: step 1 research, step 2 implement") == OrganizationAction.DELEGATE

    def test_bullet_list(self, engine, chat_ctx):
        inp = "Do these:\n- task A\n- task B\n- task C"
        assert engine.decide(chat_ctx, inp) == OrganizationAction.DELEGATE

    def test_chinese_multi_step(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "第一步调研，第二步实现，第三步测试") == OrganizationAction.DELEGATE


class TestDecisionToolCall:
    """Tool command keywords → TOOL_CALL."""

    def test_run_command(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "Run the migration script") == OrganizationAction.TOOL_CALL

    def test_tool_prefix(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "tool: search for files") == OrganizationAction.TOOL_CALL


class TestDecisionComplete:
    """Completion signals → COMPLETE."""

    def test_done_keyword(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "All done") == OrganizationAction.COMPLETE

    def test_chinese_complete(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "任务完成") == OrganizationAction.COMPLETE


class TestMemoryAccess:
    """OrganizationContext.memory is accessible to decision engine."""

    def test_memory_empty_default(self, engine):
        ctx = OrganizationContext({"run_id": "r1"})
        assert ctx.memory == {}

    def test_memory_passed_through(self, engine):
        ctx = OrganizationContext({"run_id": "r1", "memory": {"role": "engineer"}})
        assert ctx.memory["role"] == "engineer"

    def test_memory_in_to_dict(self, engine):
        ctx = OrganizationContext({"run_id": "r1", "memory": {"pref": "fast"}})
        d = ctx.to_dict()
        assert d["memory"] == {"pref": "fast"}


class TestSharedEngine:
    """Same DecisionEngine used for both Chat and Task contexts."""

    def test_chat_ctx_respond(self, engine, chat_ctx):
        assert engine.decide(chat_ctx, "Hello") == OrganizationAction.RESPOND

    def test_task_ctx_respond(self, engine, task_ctx):
        assert engine.decide(task_ctx, "Hello") == OrganizationAction.RESPOND

    def test_both_execute_code(self, engine, chat_ctx, task_ctx):
        inp = "```python\nx=1\n```"
        assert engine.decide(chat_ctx, inp) == OrganizationAction.EXECUTE
        assert engine.decide(task_ctx, inp) == OrganizationAction.EXECUTE

    def test_both_delegate_long(self, engine, chat_ctx, task_ctx):
        inp = "We need to " + "x" * 301
        assert engine.decide(chat_ctx, inp) == OrganizationAction.DELEGATE
        assert engine.decide(task_ctx, inp) == OrganizationAction.DELEGATE
