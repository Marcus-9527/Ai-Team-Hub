# Architecture Overview — AI Team Hub

## System Architecture (Simplified)

```
┌─────────────────────────────────────────────────�
│                  Your Application                │
│          (TypeScript SDK / Python SDK / HTTP)    │
└─────────────────�───────────────────────────────┘
                  │  X-API-Key header
                  ▼
┌─────────────────────────────────────────────────�
│          Public API Layer (/v1/*)                │
│    Unified response • Auth • Rate limiting      │
└─────────────────�───────────────────────────────┘
                  │
        ┌─────────┼─────────�
        ▼         ▼         ▼
   ┌────────┐ ┌────────� ┌────────────┐
   │ AUTO   │ │CONTROL │ │  DEBUG     │
   │ (FSM)  │ │(Custom)│ │(Full trace)│
   └───┬────� └───�────┘ └─────�──────�
       │          │            │
       ▼          ▼            ▼
┌─────────────────────────────────────────────────�
│              Agent Execution Layer               │
│   Planner → Executor → Reviewer → Diversity     │
└─────────────────�───────────────────────────────┘
                  │
        ┌─────────┼─────────�
        ▼         ▼         ▼
    ┌───────┐ ┌───────┐ �──────────�
    │ Cache │ │Memory │ │   LLM    │
    │Kernel │ │Kernel │ │ Provider │
    └───────┘ └───────┘ └──────────┘
```

## Key Components

### 1. Public API Layer (v1)

The only thing external users interact with. Hides all internal complexity behind a unified response schema.

- Standardized JSON responses
- API Key authentication
- Mode routing (auto/control/debug)

### 2. Agent Execution Layer

Three specialized agents work together:

| Agent | Role |
|-------|------|
| **Planner** | Decomposes tasks, determines approach |
| **Executor** | Runs the actual task |
| **Reviewer** | Validates output quality |

### 3. Cache Kernel

Multi-layer caching to reduce LLM calls:

- Teammate cache (94% hit rate)
- Channel cache (91% hit rate)
- Message cache (88% hit rate)
- Semantic cache

### 4. Memory Kernel

Persistent memory across sessions:
- Per-workspace isolation
- Thread-level context
- Long-term recall

### 5. Observability

Structured trace events for every execution:
- FSM state transitions
- Agent call timings
- Cache hit/miss tracking
- Cost estimation

## Data Flow

```
1. User sends: v1/task/run + task description
2. API layer validates auth, routes to mode handler
3. FSM classifies task complexity
4. Agents execute (with caching between steps)
5. Result validated and returned
6. Trace stored for observability
```

## Security Model

- API key authentication (X-API-Key header)
- Workspace isolation (tenant separation)
- Request-ID tracking per call
- Input validation (Pydantic models)
- Output validation gate per agent

## Deployment Options

| Target | Method | Scale |
|--------|--------|-------|
| Cloudflare Workers | `wrangler deploy` | Serverless, auto-scale |
| Docker | `docker-compose up` | Single node |
| Bare metal | `uvicorn backend.main:app` | Manual |

## What's NOT exposed

External users never see:
- FSM internal state machine
- Agent orchestration logic
- Kernel implementation details
- Internal memory structure
- Database schema

## Performance

| Metric | Value |
|--------|-------|
| Cache hit latency | <2ms |
| Simple task | ~1-2s |
| Complex pipeline | ~5-15s |
| Concurrent tasks | 4 workers |
