# AI Team Hub — Production Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ ./backend/ .

# Expose port
EXPOSE 8910

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8910/api/health').raise_for_status()"

# Start
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8910"]
