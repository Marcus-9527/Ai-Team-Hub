#!/usr/bin/env python3
"""
MCP Server for AI Team Hub development.
Allows ChatGPT (desktop) to control this environment via MCP protocol.

Usage:
  # stdio mode (ChatGPT desktop starts process directly)
  python3 mcp-server.py

  # SSE mode (server listens on port, e.g. for remote connection)
  python3 mcp-server.py --sse --port 8100
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# ── config ──────────────────────────────────────────────────────────────
WORKSPACE = Path("/home/liunx/workspace")
PROJECT   = WORKSPACE / "ai-team-hub"

mcp = FastMCP("ai-team-hub-dev", log_level="WARNING")

# ── helpers ─────────────────────────────────────────────────────────────
def _run(cmd: str, timeout: int = 180, workdir: str | None = None) -> str:
    """Run a shell command and return stdout+stderr."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=workdir or str(PROJECT), executable="/bin/bash",
        )
        out = r.stdout or ""
        err = r.stderr or ""
        if err:
            out += f"\n[stderr]\n{err}"
        if r.returncode != 0:
            out += f"\n[exit code: {r.returncode}]"
        return out.strip() or "(empty output)"
    except subprocess.TimeoutExpired:
        return f"[TIMEOUT after {timeout}s]"
    except Exception as e:
        return f"[ERROR] {e}"

def _safe_path(path: str) -> Path:
    """Resolve path preventing directory traversal."""
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT / p
    p = p.resolve()
    if not (str(p).startswith(str(PROJECT)) or str(p).startswith(str(WORKSPACE))):
        raise ValueError(f"Path outside allowed workspace: {p}")
    return p

# ── tools ───────────────────────────────────────────────────────────────

@mcp.tool()
def read_file(path: str, offset: int = 1, limit: int = 500) -> str:
    """Read a file with line numbers. offset=1 starts at line 1, limit=max lines."""
    fp = _safe_path(path)
    if not fp.is_file():
        return f"File not found: {fp}"
    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    total = len(lines)
    start = max(0, offset - 1)
    end   = min(total, start + limit)
    out = f"--- {fp} (lines {start+1}-{end}/{total}) ---\n"
    for i, line in enumerate(lines[start:end], start=start+1):
        out += f"{i:>6}|{line}"
    return out

@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Write content to a file (overwrites existing). Creates parent dirs."""
    fp = _safe_path(path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    return f"Written {len(content)} bytes to {fp}"

@mcp.tool()
def patch_file(path: str, old_string: str, new_string: str) -> str:
    """Find-and-replace in a file. Returns diff or error."""
    fp = _safe_path(path)
    if not fp.is_file():
        return f"File not found: {fp}"
    content = fp.read_text(encoding="utf-8")
    if old_string not in content:
        return f"old_string not found in {fp}"
    if content.count(old_string) > 1:
        return f"old_string appears {content.count(old_string)} times — not unique"
    new_content = content.replace(old_string, new_string, 1)
    fp.write_text(new_content, encoding="utf-8")
    return f"Patched {fp}"

# ── terminal guardrail ─────────────────────────────────────────────────
from terminal_guardrail import maybe_run

@mcp.tool()
def terminal(command: str, timeout: int = 180) -> str:
    """Execute a shell command in the project directory. Use for git, npm, pip, builds, tests.

    Natural-language prose (e.g. "检查 AI Team Hub 状态") is rejected with a
    structured error so the calling agent retries with a real shell command.
    """
    return maybe_run(command, _run, timeout=timeout)

@mcp.tool()
def search_files(pattern: str, target: str = "content", path: str = ".", file_glob: str | None = None) -> str:
    """Search files. target='content' = grep inside files, 'files' = find by name."""
    search_path = _safe_path(path)
    flag = "-rn" if target == "content" else ""
    if target == "files":
        cmd = f'find {shlex.quote(str(search_path))} -maxdepth 5 -type f -name {shlex.quote(pattern)} 2>/dev/null | head -50'
    else:
        inc = f'--include={shlex.quote(file_glob)}' if file_glob else ""
        cmd = f'grep {flag} {inc} {shlex.quote(pattern)} {shlex.quote(str(search_path))} 2>/dev/null | head -80'
    return _run(cmd, timeout=30)

@mcp.tool()
def list_dir(path: str = ".") -> str:
    """List directory contents (files and dirs)."""
    fp = _safe_path(path)
    if not fp.is_dir():
        return f"Not a directory: {fp}"
    items = []
    for f in sorted(fp.iterdir()):
        suffix = "/" if f.is_dir() else ""
        items.append(f.name + suffix)
    return "\n".join(items) if items else "(empty)"

@mcp.tool()
def run_python(code: str, timeout: int = 60) -> str:
    """Execute Python code in the ai-team-hub venv and return stdout."""
    venv_python = str(PROJECT / "backend" / "venv" / "bin" / "python3")
    if not os.path.isfile(venv_python):
        venv_python = "python3"
    cmd = f"cd {shlex.quote(str(PROJECT))} && {venv_python} -c {shlex.quote(code)}"
    return _run(cmd, timeout=min(timeout, 120))

@mcp.tool()
def project_info() -> str:
    """Get AI Team Hub project structure overview."""
    return _run("""echo "=== Project Structure ===" && find . -maxdepth 3 -type f \\
  -not -path './node_modules/*' -not -path './backend/venv/*' \\
  -not -path './.git/*' -not -path './__pycache__/*' -not -path '*/__pycache__/*' \\
  -not -name '*.pyc' -not -name '*.log' -not -path './deploy/*' \\
  | head -120 && echo && echo "=== Git Status ===" && git status --short && echo && echo "=== Branch ===" && git branch --show-current""")

# ── run ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Team Hub MCP Server")
    parser.add_argument("--sse", action="store_true", help="Run in SSE mode (HTTP server)")
    parser.add_argument("--port", type=int, default=8100, help="SSE port (default: 8100)")
    parser.add_argument("--host", default="0.0.0.0", help="SSE bind host (default: 0.0.0.0)")
    parser.add_argument("--ssl", action="store_true", help="Enable HTTPS with self-signed certs from certs/")
    args = parser.parse_args()

    if args.sse:
        import uvicorn
        from starlette.applications import Starlette
        from starlette.middleware.trustedhost import TrustedHostMiddleware
        app: Starlette = mcp.sse_app()
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

        ssl_kw = {}
        if args.ssl:
            cert_dir = Path(__file__).parent / "certs"
            ssl_kw = {
                "ssl_keyfile": str(cert_dir / "mcp-key.pem"),
                "ssl_certfile": str(cert_dir / "mcp-cert.pem"),
            }
            proto = "https"
        else:
            proto = "http"
        print(f"Starting MCP {proto} SSE server on {proto}://{args.host}:{args.port}/sse", file=sys.stderr)
        uvicorn.run(app, host=args.host, port=args.port,
                    log_level="info", proxy_headers=False, **ssl_kw)
    else:
        mcp.run(transport="stdio")
