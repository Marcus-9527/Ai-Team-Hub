# DEPLOYMENT GUIDE — AI Team Hub

## Quick Start (1 command)

```bash
cd deploy/
./start.sh
```

This builds the Docker image, starts the container, and runs health checks.

## Manual Docker

```bash
cd deploy/
# Copy and edit env
cp .env.example .env
# Edit .env with your API keys

# Start
docker-compose up --build -d

# Check health
curl http://localhost:8910/api/health

# View logs
docker-compose logs -f api

# Stop
docker-compose down
```

## Deployment Targets

### Option A: Cloudflare Workers (Current — Recommended)

Already live at `ai-team-hub.wt5371.workers.dev`.

```bash
cd ..
npx wrangler deploy
```

### Option B: Local / VM with Docker

```bash
cd deploy/
docker-compose up -d
```

### Option C: Self-hosted (bare metal)

```bash
python3 -m pip install -r requirements.txt
cd backend/
python3 main.py
# Or with gunicorn:
# gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8910
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///data/ai_team_hub.db` | Database connection |
| `WORKER_ENV` | `production` | Environment name |
| `LOG_LEVEL` | `info` | Logging level |
| `PORT` | `8910` | Server port |
| `CORS_ORIGINS` | `*` | Allowed origins |
| `DEFAULT_PROVIDER` | `openrouter` | Default AI provider |
| `DEFAULT_MODEL` | `openrouter/owl-alpha` | Default model |

## Database Setup

For SQLite (default, zero config):
```
DATABASE_URL=sqlite+aiosqlite:///data/ai_team_hub.db
```

For PostgreSQL:
```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/ai_team_hub
```

The database is auto-created on first run.

## API Key Management

### Create a key (via legacy API — no auth needed)
```bash
curl -X POST http://localhost:8910/api/apikeys/ \
  -H "Content-Type: application/json" \
  -d '{"provider": "openrouter", "label": "My App", "api_key": "cfut_..."}'
```

### Use the key
```bash
curl -H "X-API-Key: cfut_y..." \
  http://localhost:8910/v1/task/run \
  -d '{"task": "Hello world"}'
```

## Health Monitoring

```bash
# Health endpoint
curl http://localhost:8910/api/health

# Cache stats
curl http://localhost:8910/api/cache/stats

# System summary (requires API key)
curl -H "X-API-Key: cfut_..." \
  http://localhost:8910/v1/system/summary
```

## Scaling

### Vertical (single VM)
Increase Docker resources:
```yaml
# docker-compose.override.yml
services:
  api:
    deploy:
      resources:
        limits:
          cpus: "4"
          memory: 4G
```

### Horizontal (multiple instances)
Behind a load balancer:
```nginx
upstream ai_team_hub {
    server api1:8910;
    server api2:8910;
}
```

Note: observability data is per-instance (in-memory). For multi-instance, use centralized logging.

### Cloudflare Workers (serverless)
Workers auto-scale. Current deployment uses D1 for persistent data.

## Troubleshooting

### Container won't start
```bash
docker-compose logs api
# Check: database path exists, port not in use
```

### 401 Unauthorized
- Missing `X-API-Key` header on `/v1/*` routes
- Verify key exists in database

### 403 Forbidden
- API key doesn't exist in DB
- Key may be expired or revoked

### 503 from MAEOS
- MAEOS singleton not initialized (happens on first request)
- Restart the service

### High latency
- Check cache hit rate: `GET /api/cache/stats`
- Enable debug mode to see agent-level latency
- Consider changing model or provider
