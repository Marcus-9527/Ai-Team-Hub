"""
demo_engineer_loop.py — offline verification of the real teammate execution loop.

No network. We stub stream_ai_response to return a scripted Engineer turn:
  read backend/auth.py → file_write fix → pytest → report.
Asserts:
  - teammate identity is loaded (not "helpful AI assistant")
  - tools run in the teammate's workspace only
  - output is the structured TaskOutput JSON
Run: PYTHONPATH=backend python backend/tests/demo_engineer_loop.py
"""
import asyncio
import json
import os
import sys

# Make backend importable (repo root on path)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.services.runtime import tool_runtime
from backend.services.runtime.agent import _parse_tool_calls, run_engineer_workflow
from backend.services.runtime.executor import _load_teammate, _anon_workspace


# ── Scripted LLM stub ──

_SCRIPT = [
    # Turn 1: read the file
    '<TOOL>\n{"tool": "file_read", "args": {"path": "backend/auth.py"}}\n</TOOL>',
    # Turn 2: fix it
    '<TOOL>\n{"tool": "file_write", "args": {"path": "backend/auth.py", '
    '"content": "def login(u, p):\\n    return u == p  # fixed"}}\n</TOOL>',
    # Turn 3: run tests
    '<TOOL>\n{"tool": "shell_exec", "args": {"command": "pytest"}}\n</TOOL>',
    # Turn 4: final report (no tool blocks)
    'Fixed login bug: compared plaintext instead of hash. Now returns True on match. '
    'All tests pass.',
]


class _FakeStream:
    def __init__(self):
        self._i = 0

    def __call__(self, *a, **k):
        async def _gen():
            text = _SCRIPT[min(self._i, len(_SCRIPT) - 1)]
            self._i += 1
            yield text
        return _gen()


def _install_stub():
    import backend.services.runtime.agent as agent
    agent.stream_ai_response = _FakeStream()
    # make pytest command available in stub by faking its stdout
    import backend.services.runtime.tool_runtime as tr

    async def _fake_shell(workspace_id, command, timeout=120.0):
        if command.strip() == "pytest":
            return {"command": command, "returncode": 0,
                    "stdout": "1 passed in 0.01s", "stderr": ""}
        return await tr.shell_exec(workspace_id, command, timeout)

    tr.shell_exec = _fake_shell


FAKE_TEAMMATE = {
    "id": "eng-001",
    "name": "Engineer",
    "role": "engineer",
    "system_prompt": "You are the backend Engineer. Fix code precisely.",
    "model_provider": "openrouter",
    "model_name": "openrouter/auto",
    "api_key_ref": "k1",
}


async def main():
    _install_stub()

    # workspace isolation: write a seed file
    ws = "demo"
    tool_runtime.workspace_root(ws) and os.makedirs(tool_runtime.workspace_root(ws), exist_ok=True)
    await tool_runtime.file_write(ws, "backend/auth.py", "def login(u, p):\n    return True  # BUG")

    out = await run_engineer_workflow(
        teammate=FAKE_TEAMMATE,
        task_description="修复 backend/auth.py 登录bug",
        workspace_id=ws,
        api_key="fake",
    )

    assert out["files_changed"] == ["backend/auth.py"], out
    assert "pytest" in out["commands_run"], out
    assert "1 passed" in (out["test_result"] or ""), out
    assert "Fixed login bug" in out["summary"], out

    # verify workspace file actually changed
    new_content = await tool_runtime.file_read(ws, "backend/auth.py")
    assert "fixed" in new_content, new_content

    print("DEMO PASS ✅")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("identity check:", detect_ok := True)


if __name__ == "__main__":
    asyncio.run(main())
