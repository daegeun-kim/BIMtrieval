# Task 40: Portfolio-grade README and visual evidence

## Goal

Make the README a complete, visually compelling, and technically accurate entry point for both a hiring reviewer and a user running BIMtrieval locally.

Shared session context and constraints are defined in Task 32.

## Work

- Lead with the project problem, AEC-specific value, hybrid retrieval approach, and a strong real screenshot or short demo visual.
- Include several clear screenshots covering the 3D viewer, chat/query result, selection/highlighting, floor-plan mode, and explanation/evidence experience. Use real application output, not fabricated mockups.
- Include or link a concise 60-second demo video if a real recording can be produced; do not leave a broken placeholder.
- Add a compact architecture explanation and the standardized headline evaluation table from Task 36, with a link to the detailed benchmark report when present.
- Provide complete usage instructions: prerequisites, cloning, `.env.example` to user-owned `.env`, database setup, Docker Compose quick start, manual setup, local IFC placement/import, ingestion/vectorization, backend/frontend startup, testing, shutdown/reset, and common failure recovery.
- Make the local IFC workflow easy to discover. Do not document browser upload.
- Explain the read-only backend boundary, user-owned API key policy, major limitations, evaluation scope, and cost expectations honestly.
- Keep deep implementation material in professional linked docs while ensuring the README itself contains everything required to get the app running.
- Remove the Windows `.lnk` workflow and any obsolete setup path from the README.

## Validation

Follow every README command from a clean-reader perspective, verify every image and link, and confirm the benchmark summary matches the canonical results exactly.

