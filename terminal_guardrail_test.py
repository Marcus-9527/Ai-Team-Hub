"""Tests for the terminal guardrail used by the MCP `terminal` tool.

Run:
    cd ai-team-hub && PYTHONPATH=ai-team-hub python3 -m pytest \
        terminal_guardrail_test.py -q
"""
from __future__ import annotations

import json

import pytest

import terminal_guardrail as g


# ── natural language → rejected ─────────────────────────────────────────
class TestNaturalLanguageRejected:
    def test_chinese_prose(self):
        assert g.is_shell_command("检查 AI Team Hub 状态") is False
        assert g.classify("检查 AI Team Hub 状态") is not None

    def test_english_prose(self):
        assert g.is_shell_command("Please check the status of the server") is False

    def test_imperative_sentence(self):
        assert g.is_shell_command("列出所有运行中的容器并报告结果") is False

    def test_structured_error_shape(self):
        err = g.classify("检查 AI Team Hub 状态")
        assert err == {
            "type": "invalid_tool_intent",
            "reason": "natural_language_not_shell",
            "suggestion": "convert_request_to_shell_command_or_use_other_tool",
        }

    def test_maybe_run_does_not_invoke_runner(self):
        calls = []
        out = g.maybe_run("检查 AI Team Hub 状态", lambda c, timeout: calls.append(c))
        assert calls == []  # runner never called
        parsed = json.loads(out)
        assert parsed["type"] == "invalid_tool_intent"
        assert parsed["reason"] == "natural_language_not_shell"


# ── legal shell commands → allowed ──────────────────────────────────────
class TestShellAllowed:
    LEGAL = [
        "git status",
        "git status --short",
        "ls",
        "ls -la backend",
        "pwd",
        "cat README.md",
        "echo hello",
        "echo 中文参数",
        "find backend frontend",
        "find . -name '*.py' | head",
        "cat file.txt && echo done",
        "grep -r 'foo' src || true",
        "FOO=bar echo $FOO",
        "./deploy.sh",
        "python3 -m pytest",
        "npm run build",
        "curl https://example.com",
        "rm -rf build",
        "ps aux | grep nginx",
    ]

    @pytest.mark.parametrize("cmd", LEGAL)
    def test_is_shell_command(self, cmd):
        assert g.is_shell_command(cmd) is True
        assert g.classify(cmd) is None

    def test_maybe_run_invokes_runner(self):
        calls = []
        out = g.maybe_run("git status", lambda c, timeout: calls.append(c))
        assert calls == ["git status"]


# ── the concrete scenario from the task ──────────────────────────────────
class TestTaskScenario:
    """Input: '检查 AI Team Hub 状态' must NOT become `terminal: 检查 AI Team Hub 状态`.

    Instead the agent should emit a sequence of real shell commands, e.g.
    `pwd`, `ls`, `git status`, `find backend frontend`.
    """

    PROPOSED = "检查 AI Team Hub 状态"

    def test_proposed_is_rejected(self):
        assert g.classify(self.PROPOSED) is not None

    def test_real_shell_sequence_is_allowed(self):
        for c in ["pwd", "ls", "git status", "find backend frontend"]:
            assert g.is_shell_command(c) is True, c
