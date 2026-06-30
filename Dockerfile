# Unified Trading Intelligence — minimal production image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/app/data

WORKDIR /app

# Minimal system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Persistent data — Railway already mounts a Volume at /app/data,
# so the Dockerfile must NOT declare its own VOLUME (Railway rejects
# this at build validation). The mkdir is still safe to keep.
RUN mkdir -p /app/data

# Health
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/health || exit 1

EXPOSE 8000

CMD ["python", "-m", "src.main"]
