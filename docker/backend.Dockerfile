# syntax=docker/dockerfile:1.7
#
# Read-only query backend (FastAPI + uvicorn).
#
# Two stages so the builder's compilers and Poetry never reach the runtime
# image. Nothing here reads or bakes a credential: every secret arrives as an
# environment variable at `docker compose up` time.

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=2.1.4 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

WORKDIR /app

# Dependency layer first: it changes far less often than application code, so a
# source edit does not re-resolve or re-download anything.
COPY backend/pyproject.toml backend/poetry.lock ./
RUN poetry install --only main --no-root

# The embedding runtime, CPU-only.
#
# `pyproject.toml`'s optional `embedding` group pins the owner's CUDA build,
# which would be a multi-gigabyte download that cannot run on a reviewer's
# machine anyway. Installed here from the PyTorch CPU index instead, so the
# default container path works on any x86-64 host with no GPU and no drivers.
RUN . /app/.venv/bin/activate \
 && pip install --no-cache-dir torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir "sentence-transformers>=2.7"

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    # Keep tokenizer/BLAS thread pools bounded so one embedding call cannot
    # saturate every core the container is allowed to use.
    OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    TOKENIZERS_PARALLELISM=false \
    # Cache downloaded model weights on the mounted volume, not in the image.
    HF_HOME=/app/.cache/huggingface

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 bimtrieval

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY backend/app ./app

RUN mkdir -p /app/logs /app/.cache/huggingface \
 && chown -R bimtrieval:bimtrieval /app

USER bimtrieval

EXPOSE 8000

# `/health` answers even when the database is unreachable — that is the point of
# the split from `/ready`. Liveness must not depend on Postgres, or a database
# blip would restart a perfectly healthy API.
#
# Probes 127.0.0.1 rather than `localhost`: uvicorn binds IPv4 only, and a base
# image whose resolver prefers ::1 would fail the probe against a healthy app.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
