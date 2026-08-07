# syntax=docker/dockerfile:1.7
#
# Schema setup only: `bim-db-init`.
#
# Deliberately separate from ingestion.Dockerfile. Preparing a schema needs a
# database driver and the SQLAlchemy models; it does not need IfcOpenShell to
# parse geometry or torch to embed anything. Sharing the ingestion image meant
# every `docker compose up` pulled ~463 MB to run a handful of DDL statements.
#
# The dependencies are installed explicitly and the package with `--no-deps`,
# so this image cannot silently regain the heavy stack when ingestion's
# dependency list grows. `bim_rag/__init__.py` is empty and
# `db_admin/init_db.py` imports only config, schema.models and db_admin, so the
# import chain genuinely stays light -- a test asserts it.

FROM python:3.11-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Only what schema setup actually uses.
RUN pip install \
      "sqlalchemy>=2.0" \
      "psycopg2-binary" \
      "pgvector>=0.5" \
      "python-dotenv"

WORKDIR /src
COPY ingestion/pyproject.toml ./ingestion/pyproject.toml
COPY ingestion/src ./ingestion/src
# --no-deps: the console script and the migrations, without ifcopenshell,
# sentence-transformers or torch.
RUN pip install --no-deps ./ingestion

# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 bimtrieval

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
RUN chown -R bimtrieval:bimtrieval /app
USER bimtrieval

CMD ["bim-db-init"]
