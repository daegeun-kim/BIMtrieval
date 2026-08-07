# Task 33: Continuous integration gates

## Goal

Turn the green local baseline into automatic GitHub Actions enforcement so the repository publicly demonstrates that its tests and quality checks run on every change.

Shared session context and constraints are defined in Task 32.

## Work

- Add a professional GitHub Actions CI workflow for pull requests and the main branch.
- Provide clear jobs for ingestion, backend, and frontend using clean dependency installation and supported runtime versions.
- Run the fast offline checks established in Task 32: Python tests and Ruff, plus frontend tests, typecheck, lint, and production build.
- Keep CI secret-free. Do not use `.env`, `OPENAI_API_KEY`, a private database, a downloaded embedding model, or a live OpenAI call in the required gate.
- Use caching and cancellation of superseded runs where useful, but keep the workflow readable and maintainable.
- Make live/database/model checks optional and explicitly separated if they are represented at all.
- Add the CI status badge only where it will remain accurate.

## Validation

Validate workflow syntax and run the same commands locally in clean/offline conditions. Do not push the workflow or change GitHub branch-protection settings; list those as manual owner actions if needed.

