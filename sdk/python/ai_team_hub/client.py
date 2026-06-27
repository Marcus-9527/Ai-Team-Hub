"""
AI Team Hub — Python SDK

One-line task execution:
    from ai_team_hub import Client
    client = Client(api_key="your-key")
    result = client.run("Analyze market trends")
    print(result.result)
"""
import httpx
from typing import Optional, Dict, Any


class TaskResponse:
    """Unified task response."""
    def __init__(self, data: dict):
        self.task_id = data.get("task_id", "")
        self.status = data.get("status", "")
        self.result = data.get("result", "")
        self.trace_id = data.get("trace_id", "")
        self.cost = data.get("cost", "0")
        self.latency = data.get("latency", "0ms")
        self.message = data.get("message", "")
        self._raw = data

    def __repr__(self):
        return f"TaskResponse(status={self.status}, task_id={self.task_id})"

    def ok(self) -> bool:
        return self.status in ("ok", "completed", "DONE")


class WorkspaceResponse:
    def __init__(self, data: dict):
        self.workspace_id = data.get("workspace_id", "")
        self.status = data.get("status", "")
        self.title = data.get("title", "")
        self.created_at = data.get("created_at", "")
        self.message = data.get("message", "")
        self._raw = data

    def __repr__(self):
        return f"WorkspaceResponse(id={self.workspace_id}, status={self.status})"


class TraceResponse:
    def __init__(self, data: dict):
        self.trace_id = data.get("trace_id", "")
        self.task_id = data.get("task_id", "")
        self.status = data.get("status", "")
        self.steps = data.get("steps", [])
        self.fsm_transitions = data.get("fsm_transitions", [])
        self.agent_calls = data.get("agent_calls", [])
        self.cache_hits = data.get("cache_hits", 0)
        self.total_cost = data.get("total_cost", "0")
        self.total_latency = data.get("total_latency", "0ms")
        self.message = data.get("message", "")
        self._raw = data

    def __repr__(self):
        return f"TraceResponse(steps={len(self.steps)}, agents={len(self.agent_calls)})"


class ChatResponse:
    def __init__(self, data: dict):
        self.session_id = data.get("session_id", "")
        self.status = data.get("status", "")
        self.response = data.get("response", "")
        self.agent_used = data.get("agent_used", "")
        self.latency = data.get("latency", "0ms")
        self.message = data.get("message", "")
        self._raw = data

    def __repr__(self):
        return f"ChatResponse(status={self.status})"


class Client:
    """
    AI Team Hub Client.

    Usage:
        client = Client(api_key="cfut_...")

        # Simple usage (auto-detects best endpoint)
        result = client.run("Do something")

        # With options
        result = client.run("Complex task", mode="debug", budget=1.0)

        # Create workspace
        ws = client.create_workspace("My Project")

        # Get trace
        trace = client.get_trace(result.trace_id)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://ai-team-hub.wt5371.workers.dev",
        use_proxy: bool = True,
        timeout: int = 120,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.use_proxy = use_proxy
        self.timeout = timeout

    def _api_url(self, path: str) -> str:
        """Build API URL with optional proxy prefix for DPI bypass."""
        if self.use_proxy:
            # /p/v1/* — bypass school proxy DPI
            return f"{self.base_url}/p/v1{path}"
        else:
            return f"{self.base_url}/v1{path}"

    def _headers(self) -> dict:
        """Request headers — mimics browser to bypass DPI."""
        if self.use_proxy:
            return {
                "X-API-Key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "text/html,application/json",
            }
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def run(
        self,
        task: str,
        mode: str = "auto",
        provider: str = "openrouter",
        model: str = "openrouter/owl-alpha",
        budget: float = 0.5,
        timeout: int = 120,
        agent_config: Optional[Dict[str, Any]] = None,
        workspace_id: Optional[str] = None,
    ) -> TaskResponse:
        """Execute a task through the AI Runtime."""
        payload = {
            "task": task,
            "mode": mode,
            "provider": provider,
            "model": model,
            "budget": budget,
            "timeout": timeout,
        }
        if agent_config:
            payload["agent_config"] = agent_config
        if workspace_id:
            payload["workspace_id"] = workspace_id

        resp = self._post(self._api_url("/task/run"), payload)
        return TaskResponse(resp)

    def create_workspace(
        self,
        title: str,
        description: str = "",
    ) -> WorkspaceResponse:
        """Create a new workspace."""
        resp = self._post(self._api_url("/workspace/create"), {
            "title": title,
            "description": description,
        })
        return WorkspaceResponse(resp)

    def get_status(self, task_id: str) -> TaskResponse:
        """Get task status."""
        resp = self._get(self._api_url(f"/task/{task_id}/status"))
        return TaskResponse(resp)

    def get_trace(self, task_id: str) -> TraceResponse:
        """Get full execution trace."""
        resp = self._get(self._api_url(f"/task/{task_id}/trace"))
        return TraceResponse(resp)

    def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
        mode: str = "auto",
        context: Optional[Dict[str, Any]] = None,
    ) -> ChatResponse:
        """Simple agent chat."""
        payload = {
            "message": message,
            "mode": mode,
        }
        if session_id:
            payload["session_id"] = session_id
        if context:
            payload["context"] = context

        resp = self._post(self._api_url("/agent/chat"), payload)
        return ChatResponse(resp)

    def health(self) -> Dict[str, Any]:
        """Check API health."""
        try:
            resp = httpx.get(
                f"{self.base_url}/v1/health",
                timeout=10,
            )
            return resp.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── Timeline & Observability ──

    def get_timeline(self, task_id: str) -> Dict[str, Any]:
        """Get task timeline."""
        return self._get(f"/v1/timeline/{task_id}")

    def get_agent_graph(self, task_id: str) -> Dict[str, Any]:
        """Get agent execution graph."""
        return self._get(f"/v1/agent-graph/{task_id}")

    def get_cost(self, task_id: str) -> Dict[str, Any]:
        """Get cost breakdown."""
        return self._get(f"/v1/cost/{task_id}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache visualization."""
        return self._get("/v1/cache/vis")

    def get_fsm_transitions(self, task_id: str) -> Dict[str, Any]:
        """Get FSM state transitions."""
        return self._get(f"/v1/fsm-transitions/{task_id}")

    # ── Internal ──

    def _post(self, path: str, data: dict) -> dict:
        headers = self._headers()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                path,
                json=data,
                headers=headers,
            )
            if resp.status_code in (403, 404):
                raise Exception(f"API error {resp.status_code}: {resp.text[:200]}")
            if resp.status_code >= 400:
                resp.raise_for_status()
            return self._parse_response(resp)

    def _get(self, path: str) -> dict:
        headers = self._headers()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(path, headers=headers)
            if resp.status_code in (403, 404):
                raise Exception(f"API error {resp.status_code}: {resp.text[:200]}")
            if resp.status_code >= 400:
                resp.raise_for_status()
            return self._parse_response(resp)

    def _parse_response(self, resp: httpx.Response) -> dict:
        """Parse response — handles both JSON and HTML-wrapped JSON (DPI bypass)."""
        content_type = resp.headers.get("Content-Type", "")
        if "json" in content_type:
            return resp.json()
        # DPI bypass: response wrapped in <script type="application/json">
        import re
        text = resp.text
        match = re.search(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', text, re.DOTALL)
        if match:
            import json
            return json.loads(match.group(1))
        return {"raw": text}


# Sync one-liner for quick usage
def run_task(task: str, api_key: str = "", **kwargs) -> TaskResponse:
    """Quick one-liner: run_task("analyze this", api_key="...")"""
    client = Client(api_key=api_key or "")
    return client.run(task, **kwargs)


__all__ = ["Client", "TaskResponse", "TraceResponse", "ChatResponse", "WorkspaceResponse", "run_task"]
