"""
runtime/tool_runtime.py — Minimal Tool Runtime (no MCP).

Three tools, one interface, single permission gate:
    ToolCall {tool, args} → ToolRouter → PermissionCheck → Workspace → Result

Tools:
    file_read   — read a workspace file
    file_write  — write a workspace file
    shell_exec  — run an allow-listed shell command inside the workspace

Workspace isolation: every path is resolved under
    <repo>/workspaces/{workspace_id}
and containment is enforced (no `..` escapes). Shell runs with cwd set to the
workspace root. ponytail: no chroot/sandbox; path containment is the only wall.
"""

import asyncio
import os
import shlex
from typing import Any, Optional

# Repo-root-relative base for all workspaces
_BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "workspaces")
)

# Commands the Engineer is allowed to run (no arbitrary shell).
_ALLOWED_SHELL = {
    "npm test": ["npm", "test"],
    "pytest": ["pytest"],
    "git status": ["git", "status"],
    "git diff": ["git", "diff"],
    "git log": ["git", "log"],
    "git add": ["git", "add"],
    "git commit": ["git", "commit"],
}

# Language → interpreter mapping for code_exec sandbox.
_CODE_EXEC_RUNNERS = {
    "python": ["python3"],
    "python3": ["python3"],
    "node": ["node"],
    "nodejs": ["node"],
    "bash": ["bash"],
    "sh": ["sh"],
}


class ToolError(Exception):
    """Raised when a tool call is rejected or fails (non-zero exit)."""


def workspace_root(workspace_id: str) -> str:
    """Absolute, safe workspace directory for a workspace_id."""
    if not workspace_id:
        raise ToolError("workspace_id required")
    # ponytail: flat dirs keyed by id; no tree traversal from user input.
    safe = workspace_id.replace("/", "_").replace("\\", "_").replace("..", "_")
    return os.path.join(_BASE_DIR, safe)


def _resolve(workspace_id: str, path: str) -> str:
    """Resolve `path` inside the workspace and refuse escapes."""
    root = workspace_root(workspace_id)
    if os.path.isabs(path):
        # still must live under root
        target = os.path.normpath(path)
    else:
        target = os.path.normpath(os.path.join(root, path))
    if target != root and not target.startswith(root + os.sep):
        raise ToolError(f"path escapes workspace: {path}")
    return target


async def file_read(workspace_id: str, path: str, max_bytes: int = 200_000) -> str:
    """Read a workspace file, truncated to max_bytes."""
    target = _resolve(workspace_id, path)
    if not os.path.isfile(target):
        raise ToolError(f"file not found: {path}")
    with open(target, "r", encoding="utf-8", errors="replace") as f:
        data = f.read(max_bytes)
    return data


async def file_write(workspace_id: str, path: str, content: str) -> dict:
    """Write (create/overwrite) a workspace file. Returns a receipt."""
    target = _resolve(workspace_id, path)
    os.makedirs(os.path.dirname(target) or workspace_root(workspace_id), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return {"path": path, "bytes": len(content.encode("utf-8"))}


async def shell_exec(workspace_id: str, command: str, timeout: float = 120.0) -> dict:
    """Run an allow-listed command with cwd = workspace root."""
    argv = _ALLOWED_SHELL.get(command.strip())
    if argv is None:
        raise ToolError(f"command not permitted: {command}")
    root = workspace_root(workspace_id)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise ToolError(f"command timed out: {command}")
    return {
        "command": command,
        "returncode": proc.returncode,
        "stdout": out.decode("utf-8", "replace")[:8000],
        "stderr": err.decode("utf-8", "replace")[:2000],
    }


# ── Sync git helpers (must be defined before async wrappers below) ──
import subprocess


def _run_git(workspace_id: str, *argv: str, timeout: float = 30.0) -> dict:
    root = workspace_root(workspace_id)
    os.makedirs(root, exist_ok=True)
    proc = subprocess.run(
        ["git", *argv], cwd=root,
        capture_output=True, text=True, timeout=timeout,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def git_ensure(workspace_id: str, branch: str = None) -> dict:
    """Init repo if needed (baseline commit), optionally switch to a feature branch."""
    root = workspace_root(workspace_id)
    os.makedirs(root, exist_ok=True)
    if not os.path.isdir(os.path.join(root, ".git")):
        _run_git(workspace_id, "init", "-q")
        _run_git(workspace_id, "config", "user.email", "ai@teamhub.local")
        _run_git(workspace_id, "config", "user.name", "AI Team Hub")
        _run_git(workspace_id, "add", "-A")
        _run_git(workspace_id, "commit", "-q", "-m", "baseline")
    if branch:
        _run_git(workspace_id, "checkout", "-q", "-b", branch)
    return {"ok": True, "branch": branch or "main"}


def git_commit(workspace_id: str, message: str = "update") -> dict:
    """Stage all + commit. Returns the short hash, or ok=False if nothing to commit."""
    _run_git(workspace_id, "add", "-A")
    res = _run_git(workspace_id, "commit", "-q", "-m", message)
    if res["returncode"] != 0:
        return {"ok": False, "hash": "", "detail": res["stderr"].strip()}
    out = _run_git(workspace_id, "rev-parse", "--short", "HEAD")
    return {"ok": True, "hash": out["stdout"].strip()}


def git_work_diff(workspace_id: str) -> str:
    """Full diff of all engineer work since the baseline commit.

    This is the real artifact the Reviewer reads.
    Handles the single-commit (baseline) case by diffing against the empty tree.
    """
    root_r = _run_git(workspace_id, "rev-list", "--max-parents=0", "HEAD")
    root = root_r["stdout"].strip().split("\n")[0]
    if not root:
        return ""
    # If HEAD is the baseline (no engineer commits yet), diff against empty tree.
    is_root = root == _run_git(workspace_id, "rev-parse", "HEAD")["stdout"].strip()
    if is_root:
        d = _run_git(workspace_id, "diff", "--stat", "4b825dc642cb6eb9a060e54bf8d69288fbee490")
        body = _run_git(workspace_id, "diff", "4b825dc642cb6eb9a060e54bf8d69288fbee490")
    else:
        d = _run_git(workspace_id, "diff", f"{root}..HEAD", "--stat")
        body = _run_git(workspace_id, "diff", f"{root}..HEAD")
    log = _run_git(workspace_id, "log", "--oneline")
    return f"# git log\n{log['stdout']}\n# diff --stat\n{d['stdout']}\n# diff\n{body['stdout']}"


# ── Async wrappers for git operations (so execute_tool can be uniform) ──


async def _git_commit_async(workspace_id: str, message: str = "update") -> dict:
    """Async wrapper around sync git_commit."""
    return await asyncio.to_thread(git_commit, workspace_id, message)


async def _git_merge_async(workspace_id: str, branch: str) -> dict:
    """Merge a branch into the current branch.
    
    ponytail: simple merge with no conflict resolution. If merge fails,
    the error is returned and the caller can handle it.
    """
    root = workspace_root(workspace_id)
    proc = await asyncio.create_subprocess_exec(
        "git", "merge", branch,
        cwd=root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        return {"ok": False, "error": err.decode("utf-8", "replace")[:1000]}
    return {"ok": True, "output": out.decode("utf-8", "replace")[:2000]}


async def code_exec(workspace_id: str, code: str, language: str = "python",
                   timeout: float = 30.0) -> dict:
    """Run arbitrary code in a sandbox subprocess (timeout + output limit).

    Writes code to a temp file under the workspace, runs it with the
    appropriate interpreter, captures stdout/stderr, cleans up.

    ponytail: no chroot/docker — the only isolation is:
      - timeout (prevents runaway loops)
      - output cap (prevents OOM from huge print)
      - runs inside the workspace cwd (not a separate jail)
    """
    import tempfile

    argv_head = _CODE_EXEC_RUNNERS.get(language)
    if argv_head is None:
        raise ToolError(f"unsupported language: {language}")

    ext_map = {"python": ".py", "python3": ".py",
               "node": ".js", "nodejs": ".js",
               "bash": ".sh", "sh": ".sh"}
    ext = ext_map.get(language, ".py")
    root = workspace_root(workspace_id)
    sandbox = os.path.join(root, ".code_sandbox")
    os.makedirs(sandbox, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=ext, dir=sandbox, mode="w",
                                     delete=False, encoding="utf-8") as f:
        f.write(code)
        script_path = f.name

    argv = [*argv_head, script_path]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "language": language,
            "returncode": proc.returncode,
            "stdout": out.decode("utf-8", "replace")[:8000],
            "stderr": err.decode("utf-8", "replace")[:2000],
        }
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise ToolError(f"code_exec timed out ({timeout}s)")
    finally:
        # Clean up temp file even on error.
        try:
            os.unlink(script_path)
        except OSError:
            pass


async def execute_tool(
    call: dict, workspace_id: str, subject: str = "unknown",
    task_id: str = "", channel_id: str = "",
) -> dict:
    """
    Unified tool entry point. `call` = {"tool": str, "args": dict}.

    Gates dangerous actions through Policy.check() before execution.

    Returns a normalized result dict:
        {"tool", "ok": bool, "output": <data>, "error": str}
    When approval is required, returns:
        {"tool", "ok": False, "requires_approval": True, "output": None, "error": str}
    """
    tool = (call or {}).get("tool")
    args = (call or {}).get("args") or {}

    # ── Policy Gate: check before dangerous actions ──
    _dangerous = {"file_write", "shell_exec", "code_exec", "git_commit", "git_merge",
                  "task_create", "message_send"}
    if tool in _dangerous:
        resource = args.get("command") or args.get("path") or args.get("branch") or "*"
        # Load a fresh DB session for the policy check.
        from backend.database import async_session as _get_session
        try:
            async with _get_session() as sess:
                from backend.services.task.task_policy import check_tool_action
                allowed, reason = await check_tool_action(
                    sess, subject, tool, resource,
                    task_id=task_id, channel_id=channel_id,
                )
                if not allowed:
                    if reason.startswith("APPROVAL_REQUIRED:"):
                        return {
                            "tool": tool, "ok": False,
                            "requires_approval": True,
                            "output": None, "error": reason,
                        }
                    return {
                        "tool": tool, "ok": False, "output": None,
                        "error": reason,
                    }
                await sess.commit()
        except Exception:
            # ponytail: DB not available → allow (degraded mode)
            pass

    try:
        if tool == "file_read":
            out = await file_read(workspace_id, args["path"])
        elif tool == "file_write":
            out = await file_write(workspace_id, args["path"], args["content"])
        elif tool == "shell_exec":
            out = await shell_exec(workspace_id, args["command"])
        elif tool == "code_exec":
            out = await code_exec(workspace_id, args["code"], args.get("language", "python"),
                                  timeout=args.get("timeout", 30.0))
        elif tool == "git_commit":
            msg = args.get("message", "update")
            out = await _git_commit_async(workspace_id, msg)
        elif tool == "git_merge":
            branch = args.get("branch", "")
            out = await _git_merge_async(workspace_id, branch)
        else:
            raise ToolError(f"unknown tool: {tool}")
        return {"tool": tool, "ok": True, "output": out, "error": ""}
    except ToolError as e:
        return {"tool": tool, "ok": False, "output": None, "error": str(e)}
    except KeyError as e:
        return {"tool": tool, "ok": False, "output": None, "error": f"missing arg: {e}"}
