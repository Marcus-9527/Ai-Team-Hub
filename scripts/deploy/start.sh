#!/bin/bash
# AI Team Hub — Quick Start Script
# Usage: bash start.sh

set -e

echo "============================================"
echo "  AI Team Hub — Quick Start"
echo "============================================"

# Kill any existing processes on these ports
kill $(lsof -t -i:8910 2>/dev/null) 2>/dev/null || true
kill $(lsof -t -i:5173 2>/dev/null) 2>/dev/null || true

# Start backend
echo "[1/2] Starting backend on port 8910..."
cd "$(dirname "$0")/backend"
python3 -m uvicorn main:app --host 0.0.0.0 --port 8910 --reload &
BACKEND_PID=$!

# Start frontend
echo "[2/2] Starting frontend on port 5173..."
cd "$(dirname "$0")/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "============================================"
echo "  Backend:  http://localhost:8910"
echo "  Frontend: http://localhost:5173"
echo "============================================"
echo ""

# Trap Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM

wait
