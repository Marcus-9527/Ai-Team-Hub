#!/bin/bash
# AI Team Hub — One-command startup
set -e

echo "🚀 Starting AI Team Hub..."

# Create .env if missing
if [ ! -f .env ]; then
  echo "� Creating .env from template..."
  cp .env.example .env
  echo "⚠️  Edit .env with your API keys before first run!"
fi

# Start
docker-compose up --build -d

echo ""
echo "✅ AI Team Hub running at http://localhost:8910"
echo "   API docs: http://localhost:8910/docs"
echo "   Health:   http://localhost:8910/api/health"
echo ""
echo "   Stop: docker-compose down"
echo "   Logs: docker-compose logs -f api"
