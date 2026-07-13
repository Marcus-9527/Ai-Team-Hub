"""Guardrail for tool-runtime terminal execution.

When an LLM agent driving a task via ReAct passes natural-language prose
instead of a real shell command (e.g. "检查 AI Team Hub 状态"), we must NOT
just execute garbage or silently end the task. Instead we return a structured
error so the agent retries with a proper shell command.

Public API
----------
- is_shell_command(cmd) -> bool
- classify(cmd)        -> dict | None   (None = looks like a shell command)
- maybe_run(cmd, runner, timeout=180) -> str
"""
from __future__ import annotations

import json
import re

# Shell commands that unambiguously mark the input as a real command even if
# the rest of the line looks like prose (e.g. `echo 你好`).
SHELL_COMMANDS = {
    # shells / interpreters
    "sh", "bash", "zsh", "python", "python3", "py", "node", "npm", "npx",
    "pnpm", "yarn", "deno", "bun", "uv", "poetry", "pip", "pip3", "go",
    "cargo", "rustc", "java", "javac", "ruby", "perl", "php", "phpunit",
    # vcs / build
    "git", "svn", "hg", "make", "cmake", "gcc", "g++", "clang", "docker",
    "docker-compose", "kubectl", "systemctl", "service", "apt", "apt-get",
    "yum", "dnf", "brew", "gradle", "mvn",
    # filesystem / inspection
    "ls", "ll", "la", "pwd", "cd", "cat", "head", "tail", "less", "more",
    "echo", "printf", "touch", "mkdir", "rmdir", "rm", "cp", "mv", "ln",
    "find", "grep", "egrep", "fgrep", "rg", "sed", "awk", "sort", "uniq",
    "wc", "cut", "tr", "tee", "diff", "patch", "file", "stat", "readlink",
    "realpath", "basename", "dirname",
    # network / download
    "curl", "wget", "scp", "rsync", "ssh", "telnet", "nc", "ping",
    # process / system
    "ps", "kill", "killall", "top", "htop", "df", "du", "free", "uname",
    "whoami", "id", "env", "export", "set", "which", "whereis", "type",
    "command", "xargs", "jobs", "fg", "bg", "history",
    # archive / misc
    "tar", "zip", "unzip", "gzip", "gunzip", "chmod", "chown", "chgrp",
    "ln", "mount", "umount", "date", "sleep", "watch", "timeout",
    # databases
    "sqlite3", "redis-cli", "psql", "mysql", "mongosh",
}

# CJK ranges — natural-language Chinese input is never a shell command itself
# (Chinese may appear as an argument to `echo`/`grep`, but the leading token is
# then an ascii command and is caught by SHELL_COMMANDS above).
_CJK = re.compile(r"[一-鿿㐀-䶿]")

# Structural shell syntax — if present, the line is a command regardless of the
# first token.
_SHELL_SYNTAX = re.compile(r"[|&;<>()]|&&|\|\||>>|<<")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.")


def _first_token(cmd: str) -> str:
    s = cmd.strip()
    if not s:
        return ""
    return s.split()[0].strip("\"'")


def is_shell_command(cmd: str) -> bool:
    """Heuristic: does `cmd` look like a real shell command?"""
    s = cmd.strip()
    if not s:
        return False
    first = _first_token(s)
    # Accept absolute / relative paths to known interpreters or scripts by
    # basename (e.g. `/usr/bin/git`, `./deploy.sh`).
    base = first.rsplit("/", 1)[-1].lower()
    if base in SHELL_COMMANDS:
        return True
    if base.endswith((".sh", ".py", ".bash", ".zsh")):
        return True
    if _SHELL_SYNTAX.search(s):
        return True
    if _ENV_ASSIGN.match(s):
        return True
    return False


def classify(cmd: str) -> dict | None:
    """If `cmd` is natural language, return a structured error dict.

    Returns None when the input looks like a valid shell command.
    """
    if is_shell_command(cmd):
        return None
    return {
        "type": "invalid_tool_intent",
        "reason": "natural_language_not_shell",
        "suggestion": "convert_request_to_shell_command_or_use_other_tool",
    }


def maybe_run(cmd: str, runner, timeout: int = 180) -> str:
    """Guard a terminal call.

    If `cmd` is natural language, returns a JSON string with the structured
    error (so a ReAct agent retries) and `runner` is NOT invoked. Otherwise
    runs `runner(cmd, timeout=...)` and returns its output.
    """
    err = classify(cmd)
    if err is not None:
        return json.dumps(err, ensure_ascii=False)
    return runner(cmd, timeout=min(timeout, 600))
