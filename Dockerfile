# Unified Trading Intelligence — production image
# Single Python service replacing both TI and HTA.

FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/app/data

WORKDIR /app

# System dependencies (minimal — no TA-Lib compile in production)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements-prod.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Persistent data dir (Railway mounts a volume here)
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/health || exit 1

# Expose port (Railway sets $PORT automatically)
EXPOSE 8000

# Run
CMD ["python", "-m", "src.main"]
