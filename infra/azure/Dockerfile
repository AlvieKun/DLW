# ─────────────────────────────────────────────────────
# Learning Navigator AI — FastAPI Container Image
# ─────────────────────────────────────────────────────
# Build:  docker build -t learning-navigator -f infra/azure/Dockerfile .
# Run:    docker run -p 8000:8000 --env-file .env learning-navigator
# ─────────────────────────────────────────────────────

FROM python:3.10-slim AS base

LABEL maintainer="Learning Navigator Team"
LABEL description="Multi-Agent Learning GPS — FastAPI server"

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir ".[azure]"

# Non-root user
RUN useradd --create-home appuser
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "learning_navigator.api.server:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-level", "info"]
