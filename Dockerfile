# ─────────────────────────────────────────────────────
# Voice-to-SQL  —  Multi-stage production Dockerfile
# ─────────────────────────────────────────────────────

# ── Stage 1: Builder (installs deps, creates wheel) ─
FROM python:3.10-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libportaudio2 \
    portaudio19-dev \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY pyproject.toml README.md ./
COPY vtsql/ vtsql/
COPY voicetosqldatabase/ voicetosqldatabase/
COPY api/ api/
COPY app.py run_api.py ./

RUN pip install --no-cache-dir --prefix=/install -e .


# ── Stage 2: Runtime (lean final image) ─────────────
FROM python:3.10-slim AS runtime

# Install only runtime libs (no compilers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libportaudio2 \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root app user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY pyproject.toml README.md ./
COPY vtsql/ vtsql/
COPY voicetosqldatabase/ voicetosqldatabase/
COPY api/ api/
COPY app.py run_api.py ./

# Copy Streamlit theme config (dark mode + brand colors)
COPY .streamlit/ .streamlit/

# Install the package itself (editable so vtsql is on the path)
RUN pip install --no-cache-dir -e .

# Persistent volume mount point for the SQLite semantic cache
RUN mkdir -p /app/data && chown appuser:appuser /app/data
VOLUME /app/data
ENV VTSQL_CACHE_DIR=/app/data

# Expose both service ports
EXPOSE 8000
EXPOSE 8502

ENV PYTHONUNBUFFERED=1

# Healthcheck — the API responds on /healthz
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || curl -f http://localhost:8502/_stcore/health || exit 1

# Default: run the Streamlit dashboard
USER appuser
CMD ["streamlit", "run", "app.py", "--server.port=8502", "--server.address=0.0.0.0"]
