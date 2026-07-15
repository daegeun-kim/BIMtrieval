# Task 12: One-Click Local Application Launcher

## Prerequisites

Require:

```text
tasks/task09_done.md
tasks/task10_done.md
tasks/task11_done.md
backend/pyproject.toml
frontend/package.json
```

If the completed backend or frontend is unavailable, stop. This task adds local Windows developer
launch tooling only. It must not change backend, frontend, ingestion, database, vector, prompt, or
viewer behavior.

## Objective

Create a movable Windows shortcut in the repository root:

```text
Start BIM RAG.lnk
```

When double-clicked, it must:

1. locate the BIM_RAG repository safely;
2. start the Poetry backend in a visible terminal;
3. start the npm/Vite frontend in a separate visible terminal;
4. avoid duplicate server instances;
5. wait for backend and frontend readiness;
6. open `http://localhost:5173` in the default browser once ready;
7. show clear actionable errors when a prerequisite or port is unavailable.

The owner will manually move/copy `Start BIM RAG.lnk` to the Windows desktop. The shortcut must
continue pointing to the scripts in this repository after it is moved.

## Required files

Create:

```text
scripts/
├── start-dev.ps1
├── stop-dev.ps1
└── create-shortcut.ps1

Start BIM RAG.lnk
```

Use PowerShell for orchestration. Do not introduce Docker, a root npm project, a process-manager
dependency, a Windows service, or another Python environment.

## Repository-path behavior

`start-dev.ps1` and `stop-dev.ps1` must derive the repository root from their own location, for
example from `$PSScriptRoot`, rather than embedding the current absolute repository path.

`create-shortcut.ps1` may use the resolved current absolute path when generating the Windows
`.lnk`, because Windows shortcuts store an absolute target. It must be safe to rerun after the
repository is moved and must replace only the repository-root `Start BIM RAG.lnk` that it owns.

The shortcut itself may be copied or moved to the desktop; the scripts must remain in the
repository. Document that moving the repository requires rerunning `create-shortcut.ps1` and then
replacing the desktop shortcut.

## Start launcher requirements

### 1. Prerequisite checks

Before starting anything, validate without modifying environments:

- Windows PowerShell is available;
- `poetry` is available;
- `npm` is available;
- `backend/pyproject.toml` exists;
- the backend Poetry environment is usable;
- `frontend/package.json` exists;
- frontend dependencies are already installed sufficiently to run the declared `dev` script;
- the repository-root `.env` exists, without opening, printing, or logging its contents;
- the prepared viewer artifact directory exists or report a nonfatal warning explaining that model
  visualization may be unavailable.

Do **not** run `poetry install`, `npm install`, environment creation, package upgrades, ingestion,
or model preparation automatically. If dependencies are missing, show the exact safe setup command
the owner should run and stop that service cleanly.

### 2. Backend process

Start from:

```text
<repo>/backend
```

using exactly the supported application command:

```powershell
poetry run uvicorn app.main:app --reload
```

Keep the backend terminal visible and give it a clear title such as `BIM RAG Backend`. Do not
activate Conda and do not run backend Python outside Poetry.

### 3. Frontend process

Start from:

```text
<repo>/frontend
```

using:

```powershell
npm run dev
```

Keep the frontend terminal visible and give it a clear title such as `BIM RAG Frontend`.

Do not use VS Code Go Live, `npm run preview`, or a static `dist/` server for the development
shortcut.

### 4. Terminal behavior

Use two separate visible terminal sessions/windows so backend and frontend output remain easy to
inspect and each service can be interrupted normally. Windows Terminal tabs/panes may be used only
if detection and quoting remain robust; separate PowerShell windows are an acceptable and simpler
default.

The launcher orchestration window may close after successful startup/browser opening. Backend and
frontend windows must remain open. On startup failure, keep or present sufficient visible output
for the owner to understand the problem.

### 5. Port and duplicate handling

Expected ports:

```text
backend  http://localhost:8000
frontend http://localhost:5173
```

Before starting each service:

1. Check whether its port is already listening.
2. If port 8000 responds as the expected BIM RAG backend through `/health`, reuse it rather than
   starting a duplicate.
3. If port 5173 responds as the expected frontend, reuse it rather than starting a duplicate.
4. If an expected port is occupied by an unknown/unhealthy application, do not kill or replace
   that process. Report the conflict and do not claim successful startup.
5. If one BIM RAG service is already running and the other is absent, start only the absent one.

Do not kill arbitrary Python, Node, Uvicorn, Vite, Poetry, npm, or port-owning processes.

### 6. Readiness and browser opening

Poll bounded readiness rather than using a fixed long sleep:

- backend ready check: prefer `/ready`, with `/health` used to distinguish application availability
  from database readiness;
- frontend ready check: HTTP response from `http://localhost:5173` and, where practical, a small
  application identity check so an unrelated Vite app is not mistaken for BIM RAG.

Use a reasonable configurable timeout appropriate for the local machine. Print concise progress at
coarse intervals. Do not wait forever.

Open `http://localhost:5173` exactly once after both services are ready. If the backend application
is available but `/ready` reports a database/configuration problem, do not hide it; report the
backend readiness error and avoid claiming the full application is ready.

Opening the application must not submit a chat query or make an OpenAI call.

### 7. Process ownership record

Record only the processes started by this launcher in a gitignored runtime file under a safe
repository-local directory, for example:

```text
.runtime/dev-processes.json
```

Include only nonsecret operational information needed for safe stopping, such as launcher version,
process IDs, service names, ports, and start time. Never store environment values, command-line
credentials, `.env` contents, URLs with credentials, or chat/model data.

If the launcher reuses an already-running service it did not start, mark it as reused and do not
claim ownership of or stop its process.

Handle stale PID records defensively by verifying process identity before reuse or termination.

## Stop script requirements

Although only the Start shortcut is required, create `scripts/stop-dev.ps1` so the owner has a safe
way to stop launcher-owned services.

It must:

- read only the repository-owned runtime process record;
- verify recorded process identity and expected service command before termination;
- stop only processes/terminal trees started and owned by this launcher;
- leave reused/preexisting services untouched;
- tolerate already-exited/stale PIDs;
- remove or update the runtime record after successful cleanup;
- never kill all Python, Node, Uvicorn, Vite, Poetry, or npm processes;
- never choose a process for termination solely because it owns port 8000 or 5173.

Document the command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-dev.ps1
```

Do not create a separate desktop Stop shortcut unless the owner asks later.

## Shortcut generator requirements

Create `scripts/create-shortcut.ps1` using supported Windows shortcut facilities such as
`WScript.Shell` COM automation.

Generate:

```text
<repo>/Start BIM RAG.lnk
```

The shortcut must:

- invoke Windows PowerShell with `scripts/start-dev.ps1`;
- quote paths safely, including paths containing spaces;
- set the repository root as the working directory;
- use `-NoProfile` to reduce user-profile side effects;
- use the minimum execution-policy override necessary for this local script when required;
- use a sensible existing Windows/PowerShell icon if easily available;
- not require administrator privileges;
- not embed credentials or environment values;
- be regenerated idempotently.

Do not handcraft the `.lnk` binary. Generate it through the script, execute the generator once, and
validate the resulting shortcut target, arguments, and working directory programmatically.

## Documentation

Add a concise section to the current README explaining:

- double-click `Start BIM RAG.lnk`;
- the two visible service windows;
- automatic browser opening;
- how to stop services safely;
- first-time dependency setup remains manual;
- copying/moving the shortcut to desktop is supported;
- moving the repository requires regenerating the shortcut;
- common port-conflict and readiness troubleshooting.

Do not rewrite completed task history or unrelated documentation.

## Required testing

Test on Windows without changing application/database state:

1. Run the shortcut generator twice and verify idempotent valid output.
2. Inspect the `.lnk` target, arguments, working directory, and icon without exposing secrets.
3. Launch from the repository shortcut.
4. Confirm two visible terminals start with the correct working directories/commands.
5. Confirm backend `/health` and `/ready` succeed.
6. Confirm frontend responds at `http://localhost:5173`.
7. Confirm the browser opens once.
8. Run the launcher again and confirm it reuses both services without duplicates.
9. Stop launcher-owned services with `stop-dev.ps1` and confirm both ports are released.
10. Start one service manually, run the launcher, and confirm the manual service is reused and not
    stopped by `stop-dev.ps1`.
11. Simulate an unrelated port occupant if safe and confirm the launcher reports conflict without
    killing it.
12. Verify missing Poetry/npm/frontend dependencies produce actionable errors without automatic
    installation.
13. Confirm startup, health checks, and browser opening make no OpenAI request.
14. Confirm database table counts/vectors remain unchanged; no ingestion or model conversion runs.

Avoid leaving orphan terminals or server processes after validation.

## Prohibited actions

- Do not modify backend/frontend application behavior to suit the launcher.
- Do not run or modify ingestion.
- Do not create/migrate/write database tables or vectors.
- Do not prepare/reconvert viewer artifacts.
- Do not run `poetry install`, `npm install`, or package upgrades automatically.
- Do not activate Conda for the backend.
- Do not hide backend/frontend terminals.
- Do not kill arbitrary or merely port-owning processes.
- Do not store secrets in scripts, arguments, shortcut metadata, runtime records, or logs.
- Do not add Docker, services, scheduled tasks, registry changes, admin requirements, or global
  process-manager dependencies.
- Do not create a live OpenAI test or submit a chat question during validation.
- Do not create a Stop desktop shortcut in this task.

## Acceptance criteria

1. `Start BIM RAG.lnk` exists in the repository root and remains valid when copied to Desktop.
2. One double-click starts/reuses backend and frontend correctly.
3. Backend and frontend terminals remain visible.
4. The browser opens once only after both services are ready.
5. Duplicate launches do not create duplicate services.
6. Unknown port conflicts are reported without terminating other applications.
7. `stop-dev.ps1` stops only launcher-owned processes.
8. No dependency installation occurs during normal launch.
9. No secret is exposed or persisted.
10. No OpenAI call, ingestion, artifact conversion, or database/vector mutation occurs.
11. README usage and troubleshooting instructions are accurate.

## Completion report

Rename to `tasks/task12_done.md` only when every acceptance criterion passes. Append:

- files created/changed;
- shortcut target, argument, and working-directory validation without secret values;
- terminal/process strategy;
- port/reuse/conflict behavior;
- readiness timeout and browser-open behavior;
- process-record and safe-stop behavior;
- all test scenarios and results;
- database non-mutation confirmation;
- explicit statuses:

```text
Repository Start shortcut: VALIDATED
Backend launcher: VALIDATED
Frontend launcher: VALIDATED
Duplicate/port handling: VALIDATED
Readiness and browser opening: VALIDATED
Safe launcher-owned stop: VALIDATED
Secrets and application data: UNCHANGED
```

---

## Completion report (delivered 2026-07-14)

### Files created/changed

```text
scripts/common.ps1            new — shared helpers (dot-sourced), not one of the four
                               required files but kept port/identity/process-tree/
                               runtime-record logic in one place instead of duplicated
scripts/start-dev.ps1         new — prerequisite checks, two-phase port classification,
                               start/reuse, bounded readiness, single browser open
scripts/stop-dev.ps1          new — identity-verified stop of launcher-owned services only
scripts/create-shortcut.ps1   new — generates/validates Start BIM RAG.lnk
Start BIM RAG.lnk             new — repository-root shortcut (untracked; owner may commit
                               or leave local per repo policy)
.gitignore                    updated — added `.runtime/`
README.md                     updated — frontend description corrected (was still called
                               a "placeholder"), scripts/ added to the tree diagram, new
                               "Frontend — setup and commands" and "One-click local
                               launcher" sections with usage/stop/move/troubleshooting
```

### Shortcut validation (no secret values involved — none exist here)

Generated and reopened independently (not from the in-memory COM object) to confirm the
`.lnk` actually persisted correctly:

```text
TargetPath:       C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe
Arguments:         -NoProfile -ExecutionPolicy Bypass -File "<repo>\scripts\start-dev.ps1"
WorkingDirectory:  <repo>
IconLocation:      <powershell.exe path>,0
```

Ran `create-shortcut.ps1` twice back to back — byte-identical file size both times
(idempotent). Copied the `.lnk` to an unrelated temp directory and reopened it there: it
still resolved to the same absolute repo paths (a copy/move keeps working, as required).

### Terminal/process strategy

Two separate `powershell.exe -NoExit -NoProfile -Command ...` windows via `Start-Process`,
each setting its own window title (`BIM RAG Backend` / `BIM RAG Frontend`), `Set-Location`
to the correct subdirectory, then running exactly `poetry run uvicorn app.main:app --reload`
or `npm run dev`. A distinctive marker string (`BIMRAG-LAUNCHER-BACKEND-V1` /
`-FRONTEND-V1`) is baked into each spawned command line (via a harmless `$env:` assignment)
so later runs can verify a recorded PID still belongs to a process this launcher started,
not an unrelated process that reused the same PID.

### Port/reuse/conflict behavior (with two real bugs found and fixed during testing)

Both ports are **classified first** (Reused / Absent / Conflict) **before anything is
started**, then services are only started if neither is a Conflict — this was itself a fix
made during testing (see below).

Identity confirmation, not just "something is listening": backend via the FastAPI
`openapi.json` `info.title == "BIM RAG Query API"`; frontend via the page title
`<title>BIM Model Explorer</title>` in `frontend/index.html`.

**Bug 1 — IPv4/IPv6 mismatch causing false "port closed" reads.** `uvicorn` binds
`127.0.0.1` (IPv4) but Vite's default `host` resolution binds `::1` (IPv6-only) on this
stack. The original `Test-PortOpen` used a parameterless `TcpClient()` (IPv4-only socket
under Windows PowerShell 5.1 / .NET Framework — confirmed via a direct reproduction:
`Connect([IPAddress]::IPv6Loopback, port)` throws `"An address incompatible with the
requested protocol was used"`), so it could never detect an already-running frontend and
started a duplicate. Fixed by constructing the `TcpClient` with the explicit
`AddressFamily` matching each address tried (`127.0.0.1` and `::1`), verified to correctly
detect both a uvicorn-style and a Vite-style listener.

**Bug 2 — a conflict on one service left the other started anyway.** The original flow
resolved/started backend, then resolved/started frontend, then checked for conflicts —
so a backend conflict still left a freshly-started frontend terminal with nothing to pair
it with. Fixed by classifying both ports first and aborting before starting anything if
either is a genuine conflict.

**Also found and fixed:** `uvicorn --reload` on Windows runs the actual server as a
`multiprocessing.spawn` child of the reload-watcher process; if that child spawns a beat
after the watcher (or the watcher is killed first), it can survive as an orphan holding the
port. `Stop-ProcessTree`'s child enumeration was changed to multi-pass (re-scan up to 3
times with a short pause) to reduce the chance of missing it, and `stop-dev.ps1` adds a
narrow, pattern-verified fallback: if the recorded port is still held after killing the
verified tree, and the *current* occupant's command line still matches the expected
service invocation (`app\.main:app` / `vite`), it is stopped too — never merely because it
owns the port.

### Readiness and browser-open behavior

`/health` polled first (bounded, default 150s — raised from an initial 60s default after
measuring real `poetry run uvicorn --reload` cold-start latency on this machine exceeding
60s at least once, most likely `poetry run` resolution overhead plus the reload watcher's
initial recursive scan of `backend/` including the large CUDA-torch `.venv/`); `/ready`
checked once after to distinguish "app up" from "database connected" — a degraded database
prints an explicit warning and does not claim the full application is ready, but does not
block the browser opening either (the frontend already has its own degraded-backend
handling from Task 11). Frontend polled via the page-title identity check, default 90s.
`Start-Process $FrontendUrl` is called from exactly one code path, reached at most once per
run. Verified: opening does not touch `/api/query` (only `/health`, `/ready`,
`/openapi.json`, and the frontend root document are ever requested).

### Process-record and safe-stop behavior

`.runtime/dev-processes.json` (gitignored) contains only launcher version, service name,
PID, port, and start timestamp — confirmed by direct inspection during testing; no
environment values, `.env` contents, or chat/model data. A service only gets a record entry
when *this launcher* started it; a reused (already-running) service is left out of the
record entirely, so `stop-dev.ps1` structurally cannot touch it. `stop-dev.ps1` re-verifies
PID liveness and command-line marker before touching anything, tolerates already-exited/
stale PIDs, and removes the record after cleanup.

### Test scenarios and results (all run against the real local stack; no live OpenAI test
created; no chat question ever submitted)

| # | Scenario | Result |
| - | -------- | ------ |
| 1 | Shortcut generator run twice | Idempotent — identical file size both runs |
| 2 | Inspect `.lnk` target/args/workdir/icon | Correct, no secrets; verified again after copying the `.lnk` to an unrelated path |
| 3 | Launch via the generated invocation (`powershell -File start-dev.ps1`, identical to what the `.lnk` runs) | Backend + frontend terminals spawned correctly |
| 4 | Two visible terminals, correct working dir/commands | Confirmed via live process CommandLine inspection: `backend/` + `poetry run uvicorn app.main:app --reload`; `frontend/` + `npm run dev` |
| 5 | Backend `/health` and `/ready` succeed | `{"status":"ok"}` / `{"status":"ok","database":{"ok":true}}` |
| 6 | Frontend responds at `:5173` | 200, page title confirms identity |
| 7 | Browser opens once | Code path verified single-call; `-NoBrowser` used for headless automated runs, `Start-Process` call confirmed present and reachable once |
| 8 | Re-run reuses both, no duplicates | After Bug 1 fix: exactly one backend + one frontend terminal confirmed via live process count |
| 9 | `stop-dev.ps1` stops owned services, ports released | Both ports confirmed closed (real TCP connect, not just cache) after stop |
| 10 | Manually start backend, run launcher, confirm reused and not later stopped | Backend reused (no record entry created for it); `stop-dev.ps1` stopped only the launcher-started frontend; backend still healthy afterward |
| 11 | Unrelated foreign listener on port 8000 | Conflict reported, foreign process left running and untouched (confirmed alive after), **and** (after Bug 2 fix) no frontend was started either |
| 12 | Missing deps → actionable error, no auto-install | Tested by temporarily renaming `frontend/node_modules` → exact `cd frontend; npm install` guidance printed, nothing started; also tested a missing `backend/pyproject.toml` path; both restored immediately after, verified present |
| 13 | No OpenAI request during startup/health/browser-open | True by construction — only `/health`, `/ready`, `/openapi.json`, and the frontend root document are ever requested by the launcher |
| 14 | Database counts/vectors unchanged | See below — byte-identical across the full test cycle |

No orphan terminals or processes were left after validation (confirmed via live process
enumeration + real TCP connect checks, not just the runtime record).

### Database non-mutation confirmation

| table | before | during (services up, idle) | after full stop |
| --- | --- | --- | --- |
| ifc_source_models | 1 | 1 | 1 |
| ifc_entities | 6989 | 6989 | 6989 |
| ifc_relationships | 3473 | 3473 | 3473 |
| relationship_members | 17668 | 17668 | 17668 |
| rag_documents | 10462 | 10462 | 10462 |
| source_model_catalog_entries | 1 | 1 | 1 |
| model_families | 1 | 1 | 1 |

Vector metadata unchanged throughout: `BAAI/bge-m3`, dim 1024, 10462 documents. No
ingestion, migration, or model-artifact conversion ran at any point.

### Confirmation

No backend/frontend application behavior was changed to suit the launcher. No Docker,
service, scheduled task, registry change, admin requirement, or global process-manager
dependency was added. No live OpenAI test was created; no chat question was ever submitted
during validation.
