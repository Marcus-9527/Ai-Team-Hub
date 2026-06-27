# PUBLIC API SPEC — AI Team Hub v2.1

## Overview

The AI Team Hub Public API provides a clean, stable interface for executing AI agent tasks. It hides all internal FSM/Kernel/Agent orchestration complexity behind a unified response schema.

**Base URL:** `https://ai-team-hub.wt5371.workers.dev`

## Authentication

All `/v1/*` endpoints require an API key:

```bash
curl -H "X-API-Key: cfut_your_key_here" \
  https://ai-team-hub.wt5371.workers.dev/v1/task/run \
  -d '{"task": "Analyze market trends"}'
```

Or use the `Authorization: Bearer` header:
```bash
curl -H "Authorization: Bearer cfut_your_key_here" \
  https://ai-team-hub.wt5371.workers.dev/v1/task/run \
  -d '{"task": "Analyze market trends"}'
```

## System Modes

| Mode | Description | Use When |
|------|-------------|----------|
| `auto` (default) | Full FSM + agents + cache pipeline | Normal usage, best results |
| `control` | User overrides agent behavior via `agent_config` | You need specific agent settings |
| `debug` | Full trace, FSM states, internal logs visible | Troubleshooting, development |

## Endpoints

### POST /v1/task/run

Execute a task through the AI Runtime.

```json
// Request
{
  "task": "Analyze the market for AI code editors",
  "mode": "auto",
  "provider": "openrouter",
  "model": "openrouter/owl-alpha",
  "budget": 0.5,
  "timeout": 120
}

// Response
{
  "task_id": "a1b2c3d4",
  "status": "DONE",
  "result": "Market analysis shows...",
  "trace_id": "tr_abc123",
  "cost": "$0",
  "latency": "3456ms",
  "message": "Task completed successfully"
}
```

### POST /v1/workspace/create

Create a workspace for organizing tasks.

```json
// Request
{
  "title": "Data Analysis Project",
  "description": "Team workspace for Q3 data analysis"
}

// Response
{
  "workspace_id": "ws_xyz789",
  "status": "created",
  "title": "Data Analysis Project",
  "created_at": "2026-06-27T10:00:00Z",
  "latency": "45ms"
}
```

### GET /v1/task/{task_id}/status

Get current task status.

```json
// Response
{
  "task_id": "a1b2c3d4",
  "status": "DONE",
  "result": "Final result here...",
  "trace_id": "tr_abc123",
  "cost": "$0",
  "latency": "12ms"
}
```

### GET /v1/task/{task_id}/trace

Get full execution trace with FSM transitions, agent calls, and cache hits.

```json
// Response
{
  "trace_id": "tr_abc123",
  "task_id": "a1b2c3d4",
  "status": "complete",
  "steps": [
    {"step": "init", "agent": "system", "latency_ms": 0},
    {"step": "classify", "agent": "planner", "latency_ms": 1200},
    {"step": "plan", "agent": "planner", "latency_ms": 2100},
    {"step": "execute", "agent": "executor", "latency_ms": 5400},
    {"step": "review", "agent": "reviewer", "latency_ms": 1800}
  ],
  "fsm_transitions": [
    {"from": "INIT", "to": "CLASSIFY"},
    {"from": "CLASSIFY", "to": "PLAN"},
    {"from": "PLAN", "to": "EXECUTE"},
    {"from": "EXECUTE", "to": "REVIEW"},
    {"from": "REVIEW", "to": "DONE"}
  ],
  "agent_calls": [
    {"agent": "planner", "input_preview": "Analyze the market...", "output_preview": "...", "latency_ms": 1200}
  ],
  "cache_hits": 3,
  "total_cost": "$0",
  "total_latency": "10500ms"
}
```

### POST /v1/agent/chat

Simple one-shot agent chat (no FSM lifecycle).

```json
// Request
{
  "message": "Summarize our current progress",
  "mode": "auto"
}

// Response
{
  "session_id": "sess_abc",
  "status": "ok",
  "response": "Task submitted, ID: a1b2c3d4",
  "agent_used": "executor",
  "latency": "2345ms"
}
```

## Observability Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /v1/timeline/{task_id}` | Task execution timeline |
| `GET /v1/agent-graph/{task_id}` | Agent execution graph (nodes + edges) |
| `GET /v1/cost/{task_id}` | Cost breakdown per agent |
| `GET /v1/cache/vis` | Cache hit/miss visualization |
| `GET /v1/fsm-transitions/{task_id}` | FSM state transitions |
| `GET /v1/system/summary` | Overall system dashboard data |

## Response Schema

All endpoints return the same shape:

```json
{
  "task_id": "string",
  "status": "string",
  "result": "string",
  "trace_id": "string",
  "cost": "$0",
  "latency": "1234ms",
  "message": "string"
}
```

## Error Codes

| HTTP | Meaning |
|------|---------|
| 400 | Bad request (missing required fields) |
| 401 | Missing X-API-Key header |
| 403 | Invalid API key |
| 404 | Task/workspace not found |
| 500 | Internal server error |
| 503 | Service not initialized |

## SDK Usage

### Python
```python
from ai_team_hub import Client

client = Client(api_key="cfut_your_key")
result = client.run("Analyze market trends")
print(result.result)
```

### TypeScript
```typescript
import { Client } from 'ai-team-hub';

const client = new Client({ apiKey: 'cfut_your_key' });
const result = await client.run('Analyze market trends');
console.log(result.result);
```

## Rate Limiting

- Default: 100 requests/minute per API key
- Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`

## Versioning

The API is versioned via URL prefix (`/v1/`). Backward-compatible changes don't change the version number. Breaking changes introduce a new version (`/v2/`).
