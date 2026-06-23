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

# System dependencies for TA-Lib (compiled C lib)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        wget \
    && rm -rf /var/lib/apt/lists/*

# Install TA-Lib C library (needed by ta-lib python package)
RUN wget -qO- https://sourceforge.net/projects/ta-lib/files/ta-lib/0.4.0/ta-lib-0.4.0-src.tar.gz/download \
    | tar -xz -C /tmp/ \
    && cd /tmp/ta-lib \
    && ./configure --prefix=/usr \
    && make -j$(nproc) \
    && make install \
    && rm -rf /tmp/ta-lib

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Persistent data dir (Railway mounts a volume here)
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=5).read()" || exit 1

# Expose port (Railway sets $PORT automatically)
EXPOSE 8000

# Run
CMD ["python", "-m", "src.main"]
