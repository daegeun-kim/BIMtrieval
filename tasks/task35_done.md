# Task 35: One-command Docker Compose environment

## Goal

Replace the Windows-only launcher as the primary entry point with a portable container workflow that a reviewer can start predictably.

Shared session context and constraints are defined in Task 32.

## Work

- Add maintainable container definitions and a root Compose configuration for PostgreSQL with pgvector, ingestion/setup, the read-only FastAPI backend, and the frontend.
- `docker compose up --build` must start a coherent local environment with health checks and persistent database storage.
- Use the user's root `.env`, created from `.env.example`, at runtime only. Never bake or echo credentials into images.
- Keep the default path CPU-compatible. Do not require the reviewer's machine to have the owner's CUDA/GPU setup.
- Integrate the repeatable schema/role setup from Task 34 and provide a simple Compose command for importing a local IFC file.
- A missing IFC or OpenAI key must produce a clear setup/degraded state rather than a crash. Do not commit a large IFC merely to make the default stack look populated.
- Remove `Start BIM RAG.lnk` as the documented primary launcher. A narrowly scoped optional Windows helper may remain only if it is portable, professional, and secondary to Compose.
- Keep development and production behavior understandable; avoid an unnecessary orchestration platform.

## Validation

Test build, first startup, health/readiness, database persistence, local IFC import, backend read-only access, frontend/API connectivity, and clean shutdown from the documented commands. Use only temporary non-secret test values derived from `.env.example`; do not read the user's `.env` during validation.
