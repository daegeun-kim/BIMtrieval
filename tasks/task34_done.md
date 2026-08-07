# Task 34: Portable configuration, database setup, and local IFC import

## Goal

Make first-time configuration and IFC ingestion obvious and reproducible without accessing the user's secrets or requiring users to discover an internal folder convention.

Shared session context and constraints are defined in Task 32.

## Work

- Add a root `.env.example` with safe placeholders and concise comments for exactly these required names:

```dotenv
db_url=
OPENAI_API_KEY=
DATABASE_URL=
```

- Clearly distinguish the ingestion/write database connection from the backend's dedicated read-only connection.
- Never inspect or derive values from `.env`. The user will create their own local `.env` and supply their own OpenAI key.
- Give local IFC files one obvious user-facing import location near the repository root, or an equally clear CLI path-based workflow. Claude may reorganize the current `ifc_original` layout if that makes the process simpler.
- Update every affected path, test, script, ignore rule, and document together. Keep large user IFC files out of Git and retain only genuinely small, licensed fixtures needed for automated tests.
- Provide one clear ingestion command that accepts a local IFC path and performs the existing idempotent import/vectorization workflow.
- Make database schema creation, migrations, catalog setup, and read-only-role bootstrap versioned and repeatable.
- Do not add frontend or public API file upload.

## Validation

Verify the setup from placeholders and test fixtures only. Confirm that no secret or large local IFC file becomes tracked and that the documented database/import commands match the actual entry points.

