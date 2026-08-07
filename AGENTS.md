# Agent instructions

The single source of truth for any AI coding assistant working in this
repository. `CLAUDE.md` imports this file; there is no second copy to drift.

## Project

**BIMtrieval** — LLM-integrated BIM information access and visualization. An IFC
building model is ingested into PostgreSQL (structured facts + pgvector
embeddings); a read-only FastAPI backend answers BIM questions over that data via
SQL, graph traversal, semantic retrieval, and a hybrid orchestration of the
three; a React/Three.js frontend provides a 3D viewer and chat.

Three independently managed applications. **PostgreSQL is the only runtime
integration boundary between them.** The backend never imports ingestion code and
never writes BIM corpus data.

## Scope constraints

- Operate only within this repository and its PostgreSQL database.
- Do not read, modify, or access parent directories or external folders.
- Do not go beyond the active spec or task. Do not introduce additional tools,
  frameworks, or datasets unless asked.
- Do not perform GitHub-side actions — push, release, settings, branch
  protection. Prepare the repository and document the manual owner steps.

## Secrets

- **Never open, read, print, copy, or inspect `.env`.** Work from documented
  configuration names and the placeholders in `.env.example`.
- Never place a real credential in a file, image, log, test, container layer, or
  command output.
- Every user supplies their own `OPENAI_API_KEY`. There is no shared-key demo,
  and the frontend never collects a key.

## Environments

| Project | Environment | Offline gate |
| --- | --- | --- |
| `ingestion/` | Conda `bim_rag` (Python 3.11) | `pytest`, `ruff check .`, `ruff format --check .` |
| `backend/` | pyenv-win + Poetry (Python 3.11) | `poetry run pytest`, `poetry run ruff check .` |
| `frontend/` | npm (Node 22) | `npm test`, `npm run typecheck`, `npm run lint`, `npm run build` |

Install only what the current spec requires.

Route work between CPU and GPU by workload: CPU is an Intel Core Ultra 9 285H,
GPU an RTX 5080 Laptop. Containers and CI are CPU-only by design.

## Testing contract

The default command in each project is its **fast offline gate**: no database,
no embedding model, no browser, no network, no OpenAI. Anything else is
separately named and must never enter the default path silently:

```
cd backend;    poetry run pytest -m live     # read-only PostgreSQL
cd ingestion;  pytest tests_live             # manifest generation
cd frontend;   npx playwright test           # critical-path browser suite
```

No test in any suite calls OpenAI. The live benchmark that spends tokens is an
explicit owner-run command, never a test.

## Working method

- Before coding, make a plan. After coding, run the tests.
- Follow `specs/` — the project blueprints — one spec version at a time.
- `tasks/` holds smaller updates and fixes.
- Format and lint with `ruff format .` and `ruff check .`.

### The task ledger

After a task in `tasks/` is complete:

1. Merge its content into the appropriate `specs/` file.
2. Rename it by appending `_done` — `task01.md` becomes `task01_done.md`.

Naming: `tasks/taskNN.md`, `specs/spec_vNNN_short_name.md`. No descriptive
suffixes on task filenames unless asked. Task numbers are execution order;
assume every lower-numbered task is complete rather than adding prerequisite
checks.

### Experiment output

Keep experiment outputs, generated artifacts, and user IFC models out of Git
unless explicitly approved. Local building models go in `ifc/`, which is ignored.

## Documentation

All Markdown — README, specs, tasks, docs — is managed as a single source of
truth. Keep it current and non-contradictory: when something is superseded, say
so or remove it rather than leaving two versions that disagree. Do not preserve
obsolete material merely because it already exists.

## Judgment

Evaluate feasibility, efficiency, alignment with intent, and workload. Push back
with reasons when an instruction is a bad idea, and ask for clarification rather
than guessing when a request is genuinely ambiguous.
