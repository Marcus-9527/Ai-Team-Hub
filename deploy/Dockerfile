# AI Team Hub — Production Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies from the backend requirements first (better layer caching)
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r backend/requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY worker/ ./worker/
COPY deploy/.env.example ./deploy/.env.example

# Expose port
EXPOSE 8910

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8910/api/health').raise_for_status()"

# Start
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8910"]
