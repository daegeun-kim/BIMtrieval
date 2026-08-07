# syntax=docker/dockerfile:1.7
#
# Ingestion tooling: `bim-db-init` (schema setup) and `bim-import` (IFC import).
#
# This image is not a long-running service. Compose uses it twice: once as the
# short-lived `setup` job that prepares the schema before the backend starts,
# and once as an on-demand `import` job the user invokes with a file path.

FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# CPU torch first, so the `sentence-transformers` dependency below resolves
# against it instead of pulling the default CUDA wheel. The local Conda
# environment uses a CUDA build; a container must run anywhere, so it does not.
RUN pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu

WORKDIR /src
COPY ingestion/pyproject.toml ./ingestion/pyproject.toml
COPY ingestion/src ./ingestion/src
RUN pip install ./ingestion

# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    TOKENIZERS_PARALLELISM=false \
    HF_HOME=/app/.cache/huggingface \
    # `bim-import` resolves a bare filename here; compose mounts the host's
    # ifc/ folder read-only at this path.
    ifc_dir=/app/ifc

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 bimtrieval

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

RUN mkdir -p /app/ifc /app/model_semantics /app/.cache/huggingface \
 && chown -R bimtrieval:bimtrieval /app

USER bimtrieval

# Overridden per compose service (`bim-db-init`, or `bim-import <file>`).
CMD ["bim-db-init"]
